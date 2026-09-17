"""The FlowMind consultant: interview, work profile, evidence, scoring, chat.

The design principle throughout: FlowMind combines two sources of evidence and
always keeps them apart.

    OBSERVED   measured from stored activity events
    REPORTED   what the employee told FlowMind, quoted back
    INFERRED   FlowMind's conclusion, always hedged, never stated as fact

The opportunity score is deterministic (section "SCORING"). An LLM may improve
the wording, never the numbers.
"""

import csv
import io
import re
from datetime import datetime, timezone

from . import ai, db, detection

# ============================================================== vocabulary

TOOL_ALIASES = {
    "Outlook": ["outlook"],
    "Gmail": ["gmail"],
    "Email": ["email", "e-mail", "inbox", "mailbox", "emails"],
    "Excel": ["excel"],
    "Google Sheets": ["google sheets", "gsheet", "google sheet"],
    "Spreadsheet": ["spreadsheet", "spreadsheets", "sheet", "sheets"],
    "HubSpot": ["hubspot"],
    "Salesforce": ["salesforce"],
    "Zoho": ["zoho"],
    "Dynamics": ["dynamics"],
    "CRM": ["crm", "customer record", "customer database"],
    "Zendesk": ["zendesk"],
    "Freshdesk": ["freshdesk"],
    "Intercom": ["intercom"],
    "Help Scout": ["help scout", "helpscout"],
    "Helpdesk": ["helpdesk", "help desk", "ticketing", "tickets", "support inbox",
                 "customer service", "customer support"],
    "Slack": ["slack"],
    "Microsoft Teams": ["teams"],
    "WhatsApp": ["whatsapp"],
    "Notion": ["notion"],
    "Trello": ["trello"],
    "Asana": ["asana"],
    "Jira": ["jira"],
    "QuickBooks": ["quickbooks"],
    "Xero": ["xero"],
    "SAP": ["sap"],
    "FlowMail": ["flowmail"],
    "FlowSheet": ["flowsheet"],
    "FlowCRM": ["flowcrm"],
}

TOOL_CATEGORY = {
    "Outlook": "Email", "Gmail": "Email", "Email": "Email", "FlowMail": "Email",
    "Excel": "Spreadsheet", "Google Sheets": "Spreadsheet", "Spreadsheet": "Spreadsheet",
    "FlowSheet": "Spreadsheet",
    "HubSpot": "CRM", "Salesforce": "CRM", "Zoho": "CRM", "Dynamics": "CRM",
    "CRM": "CRM", "FlowCRM": "CRM",
    "Zendesk": "Support", "Freshdesk": "Support", "Intercom": "Support",
    "Help Scout": "Support", "Helpdesk": "Support",
    "Slack": "Messaging", "Microsoft Teams": "Messaging", "WhatsApp": "Messaging",
    "Notion": "Project", "Trello": "Project", "Asana": "Project", "Jira": "Project",
    "QuickBooks": "Finance", "Xero": "Finance", "SAP": "ERP",
}

TRANSFER_WORDS = [
    "transfer", "copy", "copies", "copying", "paste", "pasting", "re-enter", "reenter",
    "re-type", "retype", "enter it", "entering", "type it", "typing it", "input",
    "duplicate", "move the information", "move information", "move data", "fill in",
    "put it into", "puts it into", "put each one", "put them in", "add it to",
    "add them to", "log it", "record it", "into our", "into the", "re-key", "rekey",
    "copy and paste", "cut and paste",
]
MANUAL_WORDS = ["manual", "manually", "by hand", "myself", "one by one", "one at a time"]
FREQUENCY_WORDS = [
    "every day", "each day", "daily", "every week", "weekly", "times a day",
    "times per day", "times a week", "all day", "constantly", "repeatedly",
    "again and again", "over and over", "multiple times", "every time", "each time",
    "several times", "throughout the day",
]
FRUSTRATION_WORDS = [
    "tedious", "boring", "annoying", "frustrating", "waste", "wasting", "wasted",
    "takes too long", "takes forever", "too long", "slow", "painful", "hate",
    "dread", "mind-numbing", "repetitive", "soul",
]
WORKAROUND_WORDS = ["template", "macro", "shortcut", "saved view", "copy of", "checklist", "workaround"]

CATEGORY_PHRASE = {
    "Email": "an email inbox",
    "Spreadsheet": "a spreadsheet",
    "CRM": "a customer record system",
    "Support": "a customer service desk",
    "Project": "a project or task tool",
    "Messaging": "a messaging tool",
    "Finance": "a finance system",
    "ERP": "an ERP system",
    "Other": "another application",
}

WORKFLOW_TITLES = {
    ("CRM", "Email", "Spreadsheet"): "Customer Request Processing",
    ("CRM", "Spreadsheet", "Support"): "Support Ticket Handling",
    ("CRM", "Support"): "Ticket to CRM Update",
    ("Spreadsheet", "Support"): "Ticket to Spreadsheet Entry",
    ("Email", "Support"): "Inbox to Ticket Handover",
    ("CRM", "Email"): "Inbox to CRM Update",
    ("Email", "Spreadsheet"): "Inbox to Spreadsheet Entry",
    ("CRM", "Spreadsheet"): "Spreadsheet to CRM Update",
    ("CRM", "Project", "Email"): "Request to Task Handover",
    ("Email", "Project"): "Inbox to Task Handover",
    ("Project", "Spreadsheet"): "Spreadsheet to Task Handover",
    ("Email", "Messaging"): "Inbox to Messaging Handover",
}


def _lower(text):
    return (text or "").lower()


def find_terms(text, words):
    low = _lower(text)
    return [w for w in words if w in low]


def find_tools(text):
    low = _lower(text)
    found = []
    for tool, aliases in TOOL_ALIASES.items():
        if any(re.search(r"\b" + re.escape(a), low) for a in aliases):
            found.append(tool)
    # prefer the specific product over the generic category word
    generic = {"Email", "Spreadsheet", "CRM"}
    specific_categories = {TOOL_CATEGORY[t] for t in found if t not in generic}
    kept = [t for t in found if not (t in generic and TOOL_CATEGORY[t] in specific_categories)]
    # name the actual product before the generic category word
    return sorted(kept, key=lambda t: (t in generic, found.index(t)))


def extract_number(text):
    """First plausible count in a sentence: '15-20 times a day' -> 20."""
    low = _lower(text)
    nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b", low) if int(n) <= 500]
    words = {"once": 1, "twice": 2, "a couple": 2, "a few": 3, "several": 5,
             "dozens": 24, "hundreds": 100}
    for w, v in words.items():
        if w in low:
            nums.append(v)
    return max(nums) if nums else None


HOUR_PHRASES = {
    "half my day": 4, "half the day": 4, "half my morning": 2, "most of my day": 6,
    "most of the day": 6, "most of my morning": 3, "all morning": 3, "all day": 7,
    "a couple of hours": 2, "a few hours": 3,
}
WORKING_DAYS_PER_WEEK = 5


def extract_hours(text, allow_phrases=False):
    """Self-REPORTED hours per week, plus the sentence it came from.

    Never presented as a measurement — it is what the employee said, and FlowMind
    labels it that way everywhere it is used.

    `allow_phrases` is only true for the answer to the explicit hours question.
    Phrases like "all morning" are ambiguous in ordinary speech ("emails arrive
    all morning" is not "I spend all morning on it"), so outside that question
    FlowMind requires an actual number rather than inventing one.
    """
    if not text:
        return None, None
    low = _lower(text)
    per_day = any(w in low for w in ("a day", "per day", "each day", "daily", "every day"))
    per_week = any(w in low for w in ("a week", "per week", "each week", "weekly", "every week"))

    hours = None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|\u2013)\s*(\d+(?:\.\d+)?)\s*(?:hour|hr)", low)
    if match:
        hours = float(match.group(2))
    else:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr)", low)
        if match:
            hours = float(match.group(1))
        else:
            minutes = re.search(r"(\d+(?:\.\d+)?)\s*(?:minute|min)", low)
            if minutes:
                hours = float(minutes.group(1)) / 60
                per_day = per_day or not per_week
    if hours is None and allow_phrases:
        for phrase, value in HOUR_PHRASES.items():
            if phrase in low:
                hours, per_day = value, True
                break
    if hours is None:
        return None, None

    weekly = hours * WORKING_DAYS_PER_WEEK if (per_day or not per_week) else hours
    return round(min(weekly, 60), 1), text.strip()


def fmt_duration(ms):
    if not ms or ms < 0:
        return "0m"
    seconds = round(ms / 1000)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s" if s else f"{m}m"
    return f"{s}s"


def fmt_minutes(ms):
    minutes = ms / 60000
    if minutes < 1:
        return f"{round(ms / 1000)} seconds"
    if minutes < 10:
        return f"{minutes:.1f} minutes"
    return f"{round(minutes)} minutes"


# ============================================================== THE INTERVIEW

OPENING = "Tell me what you normally do during a typical workday."

QUESTIONS = {
    "workday": OPENING,
    "company": "And what does your company actually do \u2014 and how big is the team you work in?",
    "tools": "Which applications or systems do you spend the most time in?",
    "repetitive": "Which of those tasks do you find yourself repeating — every day or every week?",
    "transfer": "Is there information you regularly move from one system into another?",
    "frequency": "Roughly how many times a day does that happen?",
    "duration": "About how long does one of those take you, start to finish?",
    "hours": "Across a whole week, roughly how many hours do you think that work takes you?",
    "slow": "Which task takes longer than you think it should?",
    "workaround": "Have you built any shortcut or workaround for it — a template, a saved view, anything like that?",
    "wish": "If you could remove one repetitive task from tomorrow's workday, which would it be?",
}

MIN_QUESTIONS = 5
MAX_QUESTIONS = 8


def transcript_signals(transcript):
    """Everything FlowMind has learned from what the employee actually said."""
    answers = [m for m in transcript if m["role"] == "employee"]
    joined = " ".join(m["text"] for m in answers)
    asked = [m["slot"] for m in transcript if m["role"] == "consultant" and m["slot"]]
    answered = [m["slot"] for m in answers if m["slot"]]
    return {
        "asked": asked,
        "answered": answered,
        "answers": answers,
        "text": joined,
        "tools": find_tools(joined),
        "transfer": find_terms(joined, TRANSFER_WORDS),
        "manual": find_terms(joined, MANUAL_WORDS),
        "frequency": find_terms(joined, FREQUENCY_WORDS),
        "frustration": find_terms(joined, FRUSTRATION_WORDS),
        "workaround": find_terms(joined, WORKAROUND_WORDS),
        "count": extract_number(" ".join(
            m["text"] for m in answers if m["slot"] in ("frequency", "transfer", "repetitive"))),
        "hours": _first_hours(answers),
    }


def _first_hours(answers):
    """Prefer the answer to the hours question, then anything else that mentions hours."""
    for m in answers:
        if m["slot"] == "hours":
            hours, quote = extract_hours(m["text"], allow_phrases=True)
            if hours:
                return {"per_week": hours, "quote": quote}
    for m in answers:
        hours, quote = extract_hours(m["text"])      # a stated number, anywhere
        if hours:
            return {"per_week": hours, "quote": quote}
    return None


def interview_complete(signals):
    asked = [s for s in signals["asked"] if s]
    if len(asked) >= MAX_QUESTIONS:
        return True
    enough_topic = bool(signals["transfer"] or signals["frustration"]
                        or "repetitive" in signals["answered"])
    enough_detail = bool(signals["count"] or signals["frequency"]
                         or signals["hours"] or "duration" in signals["answered"])
    knows_company = "company" in signals["answered"]
    if not knows_company and len(asked) < MAX_QUESTIONS:
        return False
    if not signals["hours"] and "hours" not in signals["asked"] and len(asked) < MAX_QUESTIONS:
        return False
    return len(asked) >= MIN_QUESTIONS and enough_topic and enough_detail


def acknowledge(last_answer, signals):
    """One short consultant-style line that proves FlowMind listened."""
    if not last_answer:
        return ""
    tools = find_tools(last_answer)
    count = extract_number(last_answer)
    hours, _ = extract_hours(last_answer)
    if hours:
        return (f"About {hours:g} hours a week on one task is the kind of number a business "
                f"can act on.")
    if count and (find_terms(last_answer, TRANSFER_WORDS) or find_terms(last_answer, FREQUENCY_WORDS)):
        return f"Around {count} times a day is significant — that adds up over a week."
    if find_terms(last_answer, TRANSFER_WORDS) and find_terms(last_answer, MANUAL_WORDS):
        return "So information is being moved between systems by hand."
    if len(tools) >= 2:
        return f"Understood — {tools[0]} and {tools[1]} are both central to your day."
    if tools:
        return f"Understood — {tools[0]} is central to your day."
    if find_terms(last_answer, FRUSTRATION_WORDS):
        return "That kind of task is usually where the best opportunities hide."
    return "Thank you, that helps."


def next_question(signals):
    """Adaptive: what a consultant would sensibly ask next, given what was said."""
    asked, answered = signals["asked"], signals["answered"]

    def unasked(slot):
        return slot not in asked

    # the employee described moving information -> chase the specifics
    if (signals["transfer"] or signals["manual"]) and unasked("transfer"):
        tools = signals["tools"]
        if len(tools) >= 2:
            return "transfer", (f"You mentioned {tools[0]} and {tools[1]}. Is there information "
                                f"you regularly move from one of them into the other?")
        return "transfer", QUESTIONS["transfer"]

    if unasked("company"):
        return "company", QUESTIONS["company"]

    if (signals["transfer"] or "transfer" in answered or "repetitive" in answered) \
            and not signals["count"] and unasked("frequency"):
        return "frequency", QUESTIONS["frequency"]

    if not signals["hours"] and unasked("hours"):
        if signals["count"]:
            return "hours", ("You mentioned about "
                             f"{signals['count']} times a day \u2014 across a whole week, roughly "
                             "how many hours do you think that adds up to?")
        return "hours", QUESTIONS["hours"]

    for slot in ("repetitive", "tools", "slow", "wish", "workaround", "duration"):
        if unasked(slot):
            if slot == "repetitive" and signals["tools"]:
                return slot, (f"Which tasks in {signals['tools'][0]} do you find yourself "
                              f"repeating — every day or every week?")
            return slot, QUESTIONS[slot]

    return "wish", QUESTIONS["wish"]


AI_INTERVIEW_SYSTEM = ai.GUARDRAILS + """

You are conducting a short discovery interview (4-7 questions total) to understand
how one employee's work actually happens. Ask exactly ONE question. Build on what
they just said rather than moving to an unrelated topic. Keep it under 30 words.
Do not greet, do not thank them twice, do not number the question.
Return JSON: {"acknowledgement": "<one short sentence reacting to their last answer>",
"question": "<your single next question>", "slot": "<one of: workday, tools, repetitive,
transfer, frequency, duration, slow, workaround, wish>"}"""


def compose_next_turn(session_id):
    """Returns (done, acknowledgement, question, slot)."""
    transcript = db.interview_transcript(session_id)
    signals = transcript_signals(transcript)

    if not transcript:
        return False, "", OPENING, "workday"

    last_answer = signals["answers"][-1]["text"] if signals["answers"] else ""

    if interview_complete(signals):
        return True, "Thanks. I have enough context to start looking for opportunities.", "", None

    slot, question = next_question(signals)
    ack = acknowledge(last_answer, signals)

    if ai.available():
        convo = "\n".join(
            f"{'CONSULTANT' if m['role'] == 'consultant' else 'EMPLOYEE'}: {m['text']}"
            for m in transcript)
        already = ", ".join(sorted(set(s for s in signals["asked"] if s))) or "none"
        result = ai.call_json(
            AI_INTERVIEW_SYSTEM,
            f"Interview so far:\n{convo}\n\nTopics already covered: {already}.\n"
            f"Ask the single most useful next question.",
            required_keys=("acknowledgement", "question", "slot"))
        if result and str(result["question"]).strip():
            ai_slot = str(result["slot"]).strip()
            return (False, str(result["acknowledgement"]).strip(),
                    str(result["question"]).strip(),
                    ai_slot if ai_slot in QUESTIONS else slot)

    return False, ack, question, slot


# ============================================================ WORK PROFILE

def build_work_profile(session):
    transcript = db.interview_transcript(session["id"])
    signals = transcript_signals(transcript)
    answers = {m["slot"]: m["text"] for m in signals["answers"] if m["slot"]}

    def tidy(fragment):
        text = fragment.strip(" ,.-")
        text = text[:1].upper() + text[1:]
        text = re.sub(r"\bi\b", "I", text)
        for acronym in ("crm", "erp", "sap", "api"):
            text = re.sub(r"\b" + acronym + r"\b", acronym.upper(), text, flags=re.I)
        return text

    def sentences(text):
        parts = re.split(r"[.\n;]|,\s*(?:then|and then)\s+", text or "")
        return [tidy(p) for p in parts if len(p.strip()) > 12][:4]

    recurring, pains = [], []
    for slot in ("repetitive", "transfer", "workday"):
        recurring.extend(sentences(answers.get(slot, "")))
    for slot in ("slow", "wish"):
        pains.extend(sentences(answers.get(slot, "")))

    if signals["transfer"] and signals["manual"]:
        pains.append("Manual information transfer between systems")
    if signals["frustration"]:
        pains.append("Tasks the employee described as repetitive or frustrating")

    def dedupe(items):
        seen, out = set(), []
        for i in items:
            k = i.lower()[:40]
            if k not in seen:
                seen.add(k)
                out.append(i)
        return out[:6]

    return {
        "role": session.get("role") or "",
        "industry": session.get("industry") or "",
        "company_size": session.get("company_size") or "",
        "company_context": (answers.get("company") or "").strip(),
        "hours_per_week": (signals["hours"] or {}).get("per_week"),
        "hours_quote": (signals["hours"] or {}).get("quote"),
        "primary_tools": signals["tools"][:6],
        "recurring_tasks": dedupe(recurring),
        "pain_points": dedupe(pains),
        "reported_frequency": signals["count"],
        "generated_at": db.now_iso(),
        "edited": False,
    }


def ensure_work_profile(session):
    profile = db.load_work_profile(session["id"])
    if profile and profile.get("edited"):
        return profile
    profile = build_work_profile(session)
    db.save_work_profile(session["id"], profile)
    return profile


# ========================================= AUTOMATION SUGGESTIONS (REPORTED)
#
# These come from the conversation ALONE, before FlowMind has observed anything.
# They are always labelled REPORTED: the employee said it, FlowMind did not
# measure it. When observed activity later supports one, the finding it produces
# carries the observed evidence as well and the confidence rises.

REPORT_WORDS = ["report", "reporting", "summary", "weekly report", "monthly report",
                "dashboard", "figures", "numbers for"]
STATUS_WORDS = ["status", "update the customer", "follow up", "follow-up", "chase",
                "remind", "confirmation", "notify", "let them know"]
SCHEDULE_WORDS = ["schedule", "scheduling", "calendar", "appointment", "booking",
                  "rota", "shift", "meeting invite"]
FINANCE_WORDS = ["invoice", "invoicing", "quote", "quotation", "payment", "receipt",
                 "billing", "expenses", "purchase order"]
CLEANUP_WORDS = ["clean", "cleaning", "tidy", "format", "formatting", "duplicate",
                 "duplicates", "merge", "deduplicate", "fix the data"]
APPROVAL_WORDS = ["approve", "approval", "sign off", "sign-off", "authorise", "authorize"]


def _systems(categories):
    phrases = [CATEGORY_PHRASE.get(c, "another application") for c in categories]
    if len(phrases) >= 2:
        return phrases[0], phrases[-1]
    if phrases:
        return phrases[0], "the system it ends up in"
    return "one system", "another"


def reported_time_line(signals):
    """What the employee said about volume — never a FlowMind measurement."""
    hours = signals.get("hours")
    if hours:
        return (f"You reported roughly {hours['per_week']:g} hours a week on this.", hours["quote"])
    if signals.get("count"):
        return (f"You reported doing this about {signals['count']} times a day.", None)
    return (None, None)


def interview_suggestions(session):
    """Deterministic automation suggestions derived from the interview."""
    transcript = db.interview_transcript(session["id"])
    signals = transcript_signals(transcript)
    text = signals["text"]
    if not text.strip():
        return []

    tools = signals["tools"]
    categories = list(dict.fromkeys(
        TOOL_CATEGORY.get(t, "Other") for t in tools if TOOL_CATEGORY.get(t) != "Other"))
    first, last = _systems(categories)
    transfer = bool(signals["transfer"] or signals["manual"])
    time_line, time_quote = reported_time_line(signals)

    def quotes(*word_sets):
        out = []
        for m in signals["answers"]:
            low = _lower(m["text"])
            if any(any(w in low for w in words) for words in word_sets):
                out.append(m["text"].strip())
        if time_quote and time_quote not in out:
            out.append(time_quote)
        return out[:3]

    found = []

    if transfer and len(categories) >= 2:
        found.append({
            "key": "cross_system_transfer",
            "title": f"Connect {first} to {last} instead of re-typing",
            "what": (f"You described moving the same information between {first} and {last} "
                     "by hand."),
            "how": ("Write down the exact fields that travel across — it is usually five to "
                    f"eight. Then check what {last} already accepts: a CSV or spreadsheet "
                    "import, an API, an email parser, or a no-code connector such as Zapier, "
                    "Make or Power Automate. Start with one direction only."),
            "effort": "Medium",
            "based_on": quotes(TRANSFER_WORDS, MANUAL_WORDS),
        })
    elif transfer:
        found.append({
            "key": "manual_entry",
            "title": "Get the information in structured instead of typed",
            "what": "You described entering the same kind of information by hand each time.",
            "how": ("Look at where the data comes from. A short intake form, a shared template "
                    "or an import file usually removes the typing entirely, and it removes the "
                    "typos with it."),
            "effort": "Low",
            "based_on": quotes(TRANSFER_WORDS, MANUAL_WORDS),
        })

    if "Support" in categories or find_terms(text, ["ticket", "customer service",
                                                    "customer support", "help desk"]):
        found.append({
            "key": "support_desk",
            "title": "Stop the ticket being re-typed after it is answered",
            "what": "You described handling customer requests that then have to be recorded "
                    "somewhere else as well.",
            "how": ("Most help desks can push a resolved ticket into a spreadsheet or CRM by "
                    "themselves — check for a native integration first, then an export or "
                    "webhook. The fields worth carrying across are usually customer, "
                    "reference, what changed and when."),
            "effort": "Low",
            "based_on": quotes(["ticket", "customer service", "customer support", "help desk"],
                               TRANSFER_WORDS),
        })

    if find_terms(text, REPORT_WORDS) and "Spreadsheet" in categories:
        found.append({
            "key": "recurring_report",
            "title": "Produce the recurring report automatically",
            "what": "You mentioned building a report that comes round again and again.",
            "how": ("Freeze the format first — a report can only be automated once its shape "
                    "stops changing. Then point a saved query, pivot or scheduled export at the "
                    "system that already holds the numbers."),
            "effort": "Low",
            "based_on": quotes(REPORT_WORDS),
        })

    if find_terms(text, STATUS_WORDS):
        found.append({
            "key": "status_updates",
            "title": "Trigger status updates from the field that already changes",
            "what": "You described telling people where things stand, repeatedly.",
            "how": ("Turn the message into a saved template, then fire it from the status field "
                    "you are already updating. Most CRMs and helpdesks can send it themselves "
                    "once the status changes."),
            "effort": "Low",
            "based_on": quotes(STATUS_WORDS),
        })

    if find_terms(text, FINANCE_WORDS):
        found.append({
            "key": "finance_documents",
            "title": "Generate the recurring documents from existing data",
            "what": "You mentioned preparing invoices, quotes or similar documents by hand.",
            "how": ("Check whether the tool that holds the customer and the amount can already "
                    "produce the document. If it cannot, a template plus a merge from the "
                    "spreadsheet is usually a one-afternoon change."),
            "effort": "Low",
            "based_on": quotes(FINANCE_WORDS),
        })

    if find_terms(text, SCHEDULE_WORDS):
        found.append({
            "key": "scheduling",
            "title": "Let the calendar do the back-and-forth",
            "what": "You described arranging times or appointments as part of the routine.",
            "how": ("A booking link or shared availability page removes most of the messages. "
                    "Where slots are fixed, a recurring template is enough."),
            "effort": "Low",
            "based_on": quotes(SCHEDULE_WORDS),
        })

    if find_terms(text, CLEANUP_WORDS):
        found.append({
            "key": "data_cleanup",
            "title": "Fix the data where it enters, not where it hurts",
            "what": "You mentioned cleaning, reformatting or de-duplicating data.",
            "how": ("Cleaning is a symptom. Find the step that lets bad data in — usually a free "
                    "text field or a manual paste — and constrain it there. Validation at entry "
                    "removes the cleanup entirely."),
            "effort": "Medium",
            "based_on": quotes(CLEANUP_WORDS),
        })

    if find_terms(text, APPROVAL_WORDS):
        found.append({
            "key": "approvals",
            "title": "Make the approval step stop being a waiting step",
            "what": "You described work that pauses while someone approves it.",
            "how": ("Route approvals automatically and set a rule for the small cases that do "
                    "not need one. The waiting is usually more expensive than the decision."),
            "effort": "Medium",
            "based_on": quotes(APPROVAL_WORDS),
        })

    if not found and (signals["frustration"] or signals["frequency"]):
        found.append({
            "key": "document_first",
            "title": "Write the task down before automating anything",
            "what": "You described work that repeats, but not yet a step a tool could take over.",
            "how": ("Note each step once, in order, with who touches it. Nine times out of ten "
                    "the automatable part becomes obvious on paper, and the rest turns out to "
                    "be judgement that should stay with a person."),
            "effort": "Low",
            "based_on": quotes(FRUSTRATION_WORDS, FREQUENCY_WORDS),
        })

    for item in found:
        item["evidence"] = "REPORTED"
        item["reported_time"] = time_line
        item["tools"] = tools[:4]
    return found[:4]


# ==================================================== REPORTED EVIDENCE CORPUS

def reported_corpus(session_id):
    """Everything the employee has told FlowMind, as quotable statements."""
    out = []
    for m in db.interview_transcript(session_id):
        if m["role"] == "employee" and m["text"].strip():
            out.append({"text": m["text"].strip(), "source": "interview"})
    for m in db.consultant_thread(session_id):
        if m["role"] == "employee" and m["text"].strip():
            out.append({"text": m["text"].strip(), "source": "consultant chat"})
    return out


# ================================================================== SCORING
#
# Deterministic, transparent, and stored. The LLM never touches these numbers.
#
#   Repetition frequency   0-25
#   Time associated        0-25
#   Application switching  0-15
#   Copy/paste activity    0-15
#   Employee context       0-20
#                          -----
#                          0-100

SCORE_SPEC = [
    ("repetition", "Repetition frequency", "repetitions", 25, 8),
    ("time", "Time associated", "% of analysed work time", 25, 50),
    ("switching", "Application switching", "switches per repetition", 15, 4),
    ("clipboard", "Copy/paste activity", "copy/paste per repetition", 15, 4),
    ("context", "Employee context", "context match", 20, 20),
]
HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 45


def context_match(pattern, corpus):
    """How strongly what the employee said supports THIS workflow. 0-20, explained."""
    text = " ".join(c["text"] for c in corpus)
    categories = [c for c in dict.fromkeys(pattern["categories"]) if c != "Other"]
    points, evidence = 0, []

    matched_categories = []
    for cat in categories:
        tools_in_cat = [t for t, c in TOOL_CATEGORY.items() if c == cat]
        hits = [t for t in find_tools(text) if TOOL_CATEGORY.get(t) == cat]
        if hits or cat.lower() in _lower(text):
            matched_categories.append(cat)
    if matched_categories:
        gained = min(len(matched_categories) * 4, 8)
        points += gained
        evidence.append({
            "label": "Mentioned these systems",
            "detail": ", ".join(matched_categories),
            "points": gained,
        })

    transfer_hits = find_terms(text, TRANSFER_WORDS) + find_terms(text, MANUAL_WORDS)
    if transfer_hits:
        points += 6
        evidence.append({
            "label": "Described moving information by hand",
            "detail": ", ".join(sorted(set(transfer_hits))[:4]),
            "points": 6,
        })

    freq_hits = find_terms(text, FREQUENCY_WORDS)
    count = extract_number(text)
    if freq_hits or count:
        points += 4
        detail = ", ".join(sorted(set(freq_hits))[:3]) or f"about {count} times"
        evidence.append({"label": "Described it as recurring", "detail": detail, "points": 4})

    frustration_hits = find_terms(text, FRUSTRATION_WORDS)
    if frustration_hits:
        points += 2
        evidence.append({
            "label": "Described it as repetitive or frustrating",
            "detail": ", ".join(sorted(set(frustration_hits))[:3]),
            "points": 2,
        })

    return min(points, 20), evidence


def quote_support(pattern, corpus):
    """The employee's own sentences that relate to this workflow, for REPORTED."""
    categories = {c for c in pattern["categories"] if c != "Other"}
    quotes = []
    for item in corpus:
        low = _lower(item["text"])
        relevant = (
            any(t for t in find_tools(item["text"]) if TOOL_CATEGORY.get(t) in categories)
            or any(c.lower() in low for c in categories)
            or find_terms(item["text"], TRANSFER_WORDS)
            or find_terms(item["text"], MANUAL_WORDS)
        )
        if relevant:
            quotes.append(item)
    return quotes[:4]


def score_finding(pattern, analysed_ms, context_points):
    share = (pattern["total_time_ms"] / analysed_ms * 100) if analysed_ms else 0.0
    reps = max(1, pattern["repetitions"])
    raw = {
        "repetition": pattern["repetitions"],
        "time": round(min(share, 100), 1),
        "switching": round(pattern["transitions"] / reps, 1),
        "clipboard": round((pattern["copy_events"] + pattern["paste_events"]) / reps, 1),
        "context": context_points,
    }
    components, total = [], 0.0
    for key, label, unit, weight, cap in SCORE_SPEC:
        value = raw[key]
        points = round(min(value, cap) / cap * weight, 1)
        total += points
        components.append({
            "key": key, "label": label, "unit": unit, "value": value,
            "cap": cap, "weight": weight, "points": points,
        })
    score = int(round(total))
    band = "HIGH" if score >= HIGH_THRESHOLD else ("MEDIUM" if score >= MEDIUM_THRESHOLD else "LOW")
    return score, band, components


def assess_confidence(pattern, context_points):
    reps = pattern["repetitions"]
    if reps >= 3 and context_points >= 12:
        return "HIGH", ("Observed workflow repetition and the employee's own description of "
                        "this work agree with each other.")
    if reps >= 3 and context_points >= 6:
        return "MEDIUM", ("The repetition was clearly observed and the employee's description "
                          "partly supports it, but some of the purpose is still unknown.")
    if reps >= 2 and context_points >= 12:
        return "MEDIUM", ("The employee described this work clearly, but FlowMind has observed "
                          "the sequence only a few times so far.")
    return "LOW", ("Repeated application switching was observed, but FlowMind does not yet know "
                   "what the employee was doing.")


def open_question_for(pattern, context_points, confidence):
    if confidence == "HIGH":
        return None
    apps = list(dict.fromkeys(pattern["sequence"]))
    joined = ", ".join(apps[:-1]) + " and " + apps[-1] if len(apps) > 1 else apps[0]
    if context_points < 12:
        return (f"I can see you moved between {joined} repeatedly, but I don't yet know what "
                f"you were doing. What information are you normally moving between them?")
    return (f"I've seen the {joined} sequence {pattern['repetitions']} times so far. "
            f"Is this something you do regularly in a normal week?")


# ================================================================ NARRATIVE

def workflow_title(pattern):
    cats = tuple(sorted({c for c in pattern["categories"] if c != "Other"}))
    if cats in WORKFLOW_TITLES:
        return WORKFLOW_TITLES[cats]
    apps = list(dict.fromkeys(pattern["sequence"]))
    if len(apps) == 2:
        return f"{apps[0]} to {apps[1]} Loop"
    return "Repeated Multi-Application Workflow"


def observed_statements(pattern, analysed_ms):
    apps = " → ".join(pattern["sequence"])
    share = (pattern["total_time_ms"] / analysed_ms * 100) if analysed_ms else 0
    out = [
        f"You moved between {apps} {pattern['repetitions']} times.",
        f"{fmt_minutes(pattern['total_time_ms'])} of analysed work time is associated with this "
        f"sequence ({share:.0f}% of everything FlowMind analysed).",
        f"{pattern['transitions']} application switches were recorded inside those repetitions.",
    ]
    clipboard = pattern["copy_events"] + pattern["paste_events"]
    if clipboard:
        out.append(f"{pattern['copy_events']} copy and {pattern['paste_events']} paste events "
                   f"were recorded during them (counts only — no content was read).")
    else:
        out.append("No clipboard activity was recorded during those repetitions.")
    return out


def deterministic_narrative(pattern, analysed_ms, quotes, context_points, confidence):
    apps = " → ".join(pattern["sequence"])
    categories = [c for c in dict.fromkeys(pattern["categories"]) if c != "Other"]
    phrases = [CATEGORY_PHRASE.get(c, "another application") for c in categories]
    systems = (", ".join(phrases[:-1]) + " and " + phrases[-1]) if len(phrases) > 1 \
        else (phrases[0] if phrases else "several applications")
    clipboard = pattern["copy_events"] + pattern["paste_events"]
    per_rep = clipboard / max(1, pattern["repetitions"])

    why = (f"The sequence {apps} repeated {pattern['repetitions']} times during the analysed "
           f"period, and {fmt_minutes(pattern['total_time_ms'])} of work time is associated with it.")
    if quotes:
        why += " The employee also described this part of their work during the interview."

    if clipboard and len(categories) >= 2:
        issue = ("Repeated switching between these systems combined with frequent copy/paste "
                 "activity may indicate that the same information is being entered by hand in "
                 "more than one place.")
    elif clipboard:
        issue = ("Frequent copy/paste activity inside a repeating sequence may indicate manual "
                 "information transfer.")
    elif len(categories) >= 2:
        issue = ("A repeating sequence across separate systems may indicate a process that has "
                 "to be carried out one record at a time.")
    else:
        issue = "A repeating manual sequence may be consuming more time than it appears to."

    impact = (f"Up to {fmt_minutes(pattern['total_time_ms'])} of activity is associated with this "
              f"workflow in the analysed period, at roughly {fmt_minutes(pattern['avg_duration_ms'])} "
              f"per repetition. FlowMind cannot claim all of that time would be saved — it is the "
              f"time in which the opportunity sits.")

    if len(categories) >= 2:
        step = (f"Map the specific fields that move between {phrases[0]} and {phrases[-1]}, then "
                f"check whether those systems support an API, an import, email parsing or a "
                f"built-in workflow rule that could carry them across automatically.")
    else:
        step = ("Walk through this sequence with the person who performs it and establish which "
                "steps are genuinely required and which are repeated out of habit.")

    if confidence == "HIGH":
        potential = ("Worth investigating first: the repetition was measured and the employee's "
                     "description of the work agrees with it.")
    elif confidence == "MEDIUM":
        potential = ("Worth investigating, though FlowMind would be more confident with either "
                     "more observed repetitions or more detail from the employee.")
    else:
        potential = ("Too early to recommend. FlowMind observed the pattern but does not yet know "
                     "its purpose — a short answer from the employee would settle it.")

    return {
        "why_flagged": why,
        "possible_issue": issue,
        "business_impact": impact,
        "recommended_next_step": step,
        "automation_potential": potential,
        "inferred": [issue],
    }


AI_FINDING_SYSTEM = ai.GUARDRAILS + """

Write the consultant's narrative for one detected workflow. You are given the
OBSERVED metadata and the employee's REPORTED statements. Return JSON with keys:
why_flagged, possible_issue, business_impact, recommended_next_step,
automation_potential. One to two sentences each. Reference only the numbers and
quotes supplied. Never claim time will definitely be saved — say the time is
"associated with" the workflow."""


def build_narrative(pattern, analysed_ms, quotes, context_points, confidence):
    fallback = deterministic_narrative(pattern, analysed_ms, quotes, context_points, confidence)
    if not ai.available():
        return fallback, "deterministic"

    payload = {
        "workflow": pattern["sequence"],
        "categories": pattern["categories"],
        "repetitions": pattern["repetitions"],
        "total_time_minutes": round(pattern["total_time_ms"] / 60000, 1),
        "average_repetition_minutes": round(pattern["avg_duration_ms"] / 60000, 1),
        "copy_events": pattern["copy_events"],
        "paste_events": pattern["paste_events"],
        "application_switches": pattern["transitions"],
        "share_of_analysed_time_percent": round(
            pattern["total_time_ms"] / analysed_ms * 100, 1) if analysed_ms else 0,
        "confidence": confidence,
        "employee_statements": [q["text"] for q in quotes],
    }
    result = ai.call_json(
        AI_FINDING_SYSTEM, "Workflow evidence:\n" + _json(payload),
        required_keys=("why_flagged", "possible_issue", "business_impact",
                       "recommended_next_step", "automation_potential"))
    if not result:
        return fallback, "deterministic"
    result["inferred"] = [str(result["possible_issue"])]
    return {k: str(v) if not isinstance(v, list) else v for k, v in result.items()}, "ai"


def _json(obj):
    import json as _j
    return _j.dumps(obj, indent=2)


# ================================================================== FINDINGS

def build_findings(session):
    """Detect -> combine with what the employee said -> score -> store."""
    events = db.session_events(session["id"])
    stats = detection.stream_stats(events)
    patterns = detection.detect(events)
    corpus = reported_corpus(session["id"])
    analysed_ms = stats["time_analysed_ms"]

    findings = []
    for pattern in patterns:
        context_points, context_evidence = context_match(pattern, corpus)
        quotes = quote_support(pattern, corpus)
        score, band, components = score_finding(pattern, analysed_ms, context_points)
        confidence, reason = assess_confidence(pattern, context_points)
        narrative, source = build_narrative(pattern, analysed_ms, quotes, context_points, confidence)

        findings.append({
            "pattern_key": pattern["pattern_key"],
            "title": workflow_title(pattern),
            "sequence": pattern["sequence"],
            "cyclic": pattern["cyclic"],
            "repetitions": pattern["repetitions"],
            "app_count": pattern["app_count"],
            "total_time_ms": pattern["total_time_ms"],
            "avg_duration_ms": pattern["avg_duration_ms"],
            "copy_events": pattern["copy_events"],
            "paste_events": pattern["paste_events"],
            "transitions": pattern["transitions"],
            "score": score,
            "band": band,
            "confidence": confidence,
            "confidence_reason": reason,
            "open_question": open_question_for(pattern, context_points, confidence),
            "components": components,
            "occurrences": pattern["occurrences"],
            "observed": observed_statements(pattern, analysed_ms),
            "reported": {
                "quotes": quotes,
                "context_points": context_points,
                "context_evidence": context_evidence,
            },
            "narrative": narrative,
            "analysis_source": source,
            "first_seen": pattern["first_seen"],
            "last_seen": pattern["last_seen"],
        })

    findings.sort(key=lambda f: (-f["score"], -f["repetitions"]))
    db.save_findings(session["id"], findings)
    return db.load_findings(session["id"])   # re-read so rows carry their stored id


# ================================================================ CONSULTANT CHAT

SUGGESTED_QUESTIONS = [
    "Where am I spending the most time?",
    "What should I automate first?",
    "Why did you flag this workflow?",
    "Show me the evidence.",
    "Is there anything you need to ask me?",
]


def _time_answer(stats, findings):
    if not stats["by_category"]:
        return ("I haven't analysed any work activity yet, so I can't tell you where your time "
                "is going. Start a work analysis and I'll be able to answer this properly.")
    lines = [f"Across {fmt_duration(stats['time_analysed_ms'])} of analysed work time:"]
    for row in stats["by_category"][:5]:
        share = row["duration_ms"] / stats["time_analysed_ms"] * 100
        lines.append(f"• {row['category']} — {fmt_duration(row['duration_ms'])} ({share:.0f}%)")
    if findings:
        top = findings[0]
        share = (top["total_time_ms"] / stats["time_analysed_ms"] * 100) if stats["time_analysed_ms"] else 0
        lines.append("")
        lines.append(f"{share:.0f}% of that time sits inside one repeating sequence — "
                     f"{' → '.join(top['sequence'])} — which I've flagged as {top['title']}.")
    return "\n".join(lines)


def _automate_answer(findings, suggestions=()):
    if not findings:
        if suggestions:
            top = suggestions[0]
            lines = [f"From what you've told me, I'd start with **{top['title']}**.", ""]
            if top.get("reported_time"):
                lines += [f"REPORTED: {top['reported_time']}"]
            lines += [f"REPORTED: {top['what']}", "",
                      f"How to approach it: {top['how']}", "",
                      "I haven't observed your activity yet, so this rests on what you told me "
                      "alone. Run a work analysis and I can check whether it shows up in "
                      "practice too."]
            return "\n".join(lines)
        return ("I haven't identified a repeated workflow yet, and you haven't described one to "
                "me either, so recommending something to automate would be guesswork. Tell me "
                "about a task you repeat, or run a work analysis.")
    top = findings[0]
    return "\n".join([
        f"I'd start with **{top['title']}** — opportunity score {top['score']}/100, "
        f"confidence {top['confidence']}.",
        "",
        f"OBSERVED: {top['observed'][0]} {top['observed'][1]}",
        f"REPORTED: {top['reported']['quotes'][0]['text']}" if top["reported"]["quotes"]
        else "REPORTED: you haven't yet told me what this sequence is for.",
        f"INFERRED: {top['narrative']['possible_issue']}",
        "",
        f"Next step: {top['narrative']['recommended_next_step']}",
    ])


def _evidence_answer(findings):
    if not findings:
        return "There is no finding to show evidence for yet."
    top = findings[0]
    lines = [f"Evidence behind **{top['title']}**:", "", "OBSERVED"]
    lines += [f"• {s}" for s in top["observed"]]
    lines += ["", "REPORTED"]
    if top["reported"]["quotes"]:
        lines += [f"• “{q['text']}” ({q['source']})" for q in top["reported"]["quotes"]]
    else:
        lines.append("• Nothing yet — you haven't described this part of your work to me.")
    lines += ["", "INFERRED", f"• {top['narrative']['possible_issue']}", "",
              f"Confidence: {top['confidence']} — {top['confidence_reason']}"]
    return "\n".join(lines)


def _impact_answer(findings, stats):
    if not findings:
        return "I need a detected workflow before I can talk about time impact."
    top = findings[0]
    return "\n".join([
        f"{fmt_minutes(top['total_time_ms'])} of activity is associated with {top['title']} in "
        f"the analysed period, across {top['repetitions']} repetitions "
        f"(about {fmt_minutes(top['avg_duration_ms'])} each).",
        "",
        "I want to be careful here: that is the time the opportunity sits inside, not a saving. "
        "Some of it is work that still has to happen. The honest way to put it to a business is "
        f"“up to {fmt_minutes(top['total_time_ms'])} of activity in this period may contain "
        "automation potential”.",
    ])


def _why_answer(findings):
    if not findings:
        return "I haven't flagged anything yet."
    top = findings[0]
    n = top["narrative"]
    return "\n".join([
        f"**{top['title']}** — {top['score']}/100, confidence {top['confidence']}.",
        "", f"Why I flagged it: {n['why_flagged']}",
        "", f"Possible issue: {n['possible_issue']}",
        "", f"Business impact: {n['business_impact']}",
        "", f"Recommended next step: {n['recommended_next_step']}",
    ])


def _open_questions_answer(findings):
    questions = [f for f in findings if f.get("open_question")]
    if not questions:
        if findings:
            return ("Nothing outstanding — the workflow I flagged is supported by both what I "
                    "observed and what you told me. If your week looks different from the period "
                    "I analysed, tell me and I'll take that into account.")
        return ("Yes — I don't have any activity to work from yet. Once you've run a work "
                "analysis I'll know what to ask.")
    top = questions[0]
    return f"Yes, one thing would sharpen this:\n\n{top['open_question']}"


INTENTS = [
    ("time", ["time", "waste", "wasting", "workday go", "where is my", "spending", "busy"]),
    ("automate", ["automate", "automation", "first", "priority", "start with", "recommend"]),
    ("evidence", ["evidence", "proof", "how do you know", "show me", "based on", "data"]),
    ("impact", ["save", "saving", "how much", "impact", "roi", "worth", "value"]),
    ("why", ["why", "explain", "reason", "flag"]),
    ("questions", ["ask me", "need to ask", "anything you need", "question for me",
                   "what do you need", "more information"]),
]


def classify_intent(message):
    low = _lower(message)
    best, best_hits = None, 0
    for intent, keywords in INTENTS:
        hits = sum(1 for k in keywords if k in low)
        if hits > best_hits:
            best, best_hits = intent, hits
    return best


AI_CHAT_SYSTEM = ai.GUARDRAILS + """

You are answering the employee in the FlowMind consultant chat. You are given a
JSON context containing: their work profile, what they told you in the interview,
the measured activity summary, and the findings with their evidence.

Answer only from that context. Label evidence as OBSERVED (measured), REPORTED
(they told you) or INFERRED (your conclusion) whenever you use it. If the context
does not contain what is needed to answer, say so plainly and ask the one question
that would let you answer — do not invent anything. Keep it under 160 words."""


def answer(session, message):
    """The consultant's reply. Deterministic router, optionally phrased by an LLM."""
    events = db.session_events(session["id"])
    stats = detection.stream_stats(events)
    findings = db.load_findings(session["id"])
    profile = db.load_work_profile(session["id"]) or {}

    suggestions = interview_suggestions(session)
    intent = classify_intent(message)
    if intent == "time":
        fallback = _time_answer(stats, findings)
    elif intent == "automate":
        fallback = _automate_answer(findings, suggestions)
    elif intent == "evidence":
        fallback = _evidence_answer(findings)
    elif intent == "impact":
        fallback = _impact_answer(findings, stats)
    elif intent == "why":
        fallback = _why_answer(findings)
    elif intent == "questions":
        fallback = _open_questions_answer(findings)
    elif not findings:
        fallback = _automate_answer(findings, suggestions) if suggestions else (
            "I don't have enough analysed activity to answer that yet. "
            "Once you've run a work analysis I can tell you where the time goes and "
            "which sequence repeats most.")
    else:
        top = findings[0]
        fallback = "\n".join([
            f"Here's where things stand. I analysed {fmt_duration(stats['time_analysed_ms'])} of "
            f"approved work activity and flagged **{top['title']}** "
            f"({top['score']}/100, confidence {top['confidence']}).",
            "", f"OBSERVED: {top['observed'][0]}",
            f"INFERRED: {top['narrative']['possible_issue']}",
            "", "Ask me “show me the evidence”, “what should I automate first?” or "
                "“is there anything you need to ask me?”.",
        ])
        if top.get("open_question"):
            fallback += f"\n\nOne thing I'd still like to know: {top['open_question']}"

    if not ai.available():
        return fallback, "deterministic"

    context = {
        "work_profile": profile,
        "automation_suggestions_from_interview": suggestions,
        "interview": [{"role": m["role"], "text": m["text"]}
                      for m in db.interview_transcript(session["id"])],
        "activity_summary": {
            "analysed_time": fmt_duration(stats["time_analysed_ms"]),
            "by_category": [{"category": r["category"], "time": fmt_duration(r["duration_ms"])}
                            for r in stats["by_category"]],
            "application_switches": stats["transitions"],
            "copy_events": stats["copy_events"],
            "paste_events": stats["paste_events"],
        },
        "findings": [{
            "title": f["title"], "score": f["score"], "confidence": f["confidence"],
            "sequence": f["sequence"], "repetitions": f["repetitions"],
            "observed": f["observed"],
            "reported": [q["text"] for q in f["reported"]["quotes"]],
            "narrative": f["narrative"],
            "open_question": f.get("open_question"),
        } for f in findings],
    }
    recent = db.consultant_thread(session["id"])[-6:]
    convo = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in recent)
    text = ai.call(AI_CHAT_SYSTEM,
                   f"CONTEXT:\n{_json(context)}\n\nRECENT CHAT:\n{convo}\n\n"
                   f"EMPLOYEE ASKS: {message}", max_tokens=500)
    return (text, "ai") if text else (fallback, "deterministic")


# ================================================================== REPORT

def build_report(session):
    events = db.session_events(session["id"])
    stats = detection.stream_stats(events)
    findings = db.load_findings(session["id"])
    profile = db.load_work_profile(session["id"]) or {}
    corpus = reported_corpus(session["id"])

    if findings:
        top = findings[0]
        reported_line = (f" In your own words: \u201c{top['reported']['quotes'][0]['text'].strip()}\u201d"
                         if top["reported"]["quotes"] else
                         " You have not yet described this part of your work, so the finding rests "
                         "on observed activity alone.")
        summary = (
            f"FlowMind analysed {fmt_duration(stats['time_analysed_ms'])} of approved work "
            f"activity together with your workflow interview. The strongest opportunity "
            f"identified is {top['title']}, scoring {top['score']} of 100 with "
            f"{top['confidence'].lower()} confidence.{reported_line} FlowMind also observed the "
            f"{' → '.join(top['sequence'])} sequence {top['repetitions']} times during the "
            f"analysed period. This workflow should be investigated as a potential automation "
            f"opportunity.")
    else:
        summary = (
            f"FlowMind analysed {fmt_duration(stats['time_analysed_ms'])} of approved work "
            f"activity together with your workflow interview. That is not yet enough evidence to "
            f"identify a repeated workflow with confidence, so FlowMind is not making a "
            f"recommendation. A longer analysis period, or a few more repetitions of a typical "
            f"task, would let it reach a conclusion.")

    return {
        "session": {"code": session["code"], "type": session["session_type"],
                    "industry": session.get("industry"), "role": session.get("role"),
                    "company_size": session.get("company_size")},
        "generated_at": db.now_iso(),
        "executive_summary": summary,
        "time_distribution": stats["by_category"],
        "application_distribution": stats["by_application"],
        "analysed_time_ms": stats["time_analysed_ms"],
        "switches": stats["transitions"],
        "clipboard_events": stats["copy_events"] + stats["paste_events"],
        "profile": profile,
        "top_opportunities": findings[:3],
        "reported_statements": corpus,
        "next_steps": [f["narrative"]["recommended_next_step"] for f in findings[:3]],
        "interview_suggestions": interview_suggestions(session),
        "ai_used": any(f["analysis_source"] == "ai" for f in findings),
    }


# ============================================================ PILOT ANALYTICS

RATING_FIELDS = {
    "understanding_rating": ["Yes", "Partially", "No"],
    "repetition_rating": ["Yes", "Sometimes", "No"],
    "usefulness_rating": ["Very useful", "Somewhat useful", "Not useful"],
    "investigate_rating": ["Yes", "Maybe", "No"],
    "continued_use_rating": ["Yes", "Maybe", "No"],
    "permission_comfort": ["Yes", "Maybe", "No"],
}
POSITIVE = {
    "understanding_rating": ["Yes"],
    "repetition_rating": ["Yes"],
    "usefulness_rating": ["Very useful", "Somewhat useful"],
    "investigate_rating": ["Yes"],
    "continued_use_rating": ["Yes"],
    "permission_comfort": ["Yes"],
}

FUNNEL_STEPS = [
    ("pilot_started", "Started"),
    ("interview_completed", "Completed interview"),
    ("analysis_started", "Started analysis"),
    ("finding_viewed", "Viewed finding"),
    ("feedback_completed", "Completed feedback"),
]


def pilot_results(session_type="REAL_PILOT"):
    rows = db.all_feedback(session_type)
    sessions = db.list_sessions(session_type)

    def distribution(values):
        out = {}
        for v in values:
            if v:
                out[v] = out.get(v, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    # --- funnel: where participants stop. Counts only, never estimated.
    funnel = []
    started = sum(1 for x in sessions if x.get("pilot_started"))
    for field, label in FUNNEL_STEPS:
        reached = sum(1 for x in sessions if x.get(field))
        funnel.append({
            "key": field, "label": label, "count": reached,
            "pct": round(reached / started * 100) if started else None,
        })

    # --- unassisted completion: only sessions explicitly marked count
    marked = [x for x in sessions if x.get("assistance_level")]
    unassisted = [x for x in marked if x["assistance_level"] == "No assistance"]
    completed = [x for x in sessions if x.get("feedback_completed")]

    def minutes_between(a, b):
        if not a or not b:
            return None
        try:
            return round((datetime.fromisoformat(b.replace("Z", "+00:00"))
                          - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 60, 1)
        except ValueError:
            return None

    durations = [d for d in (minutes_between(x.get("pilot_started"), x.get("feedback_completed"))
                             for x in sessions) if d is not None]

    ratings = {}
    for field, options in RATING_FIELDS.items():
        counts = {o: sum(1 for r in rows if r.get(field) == o) for o in options}
        answered = sum(counts.values())
        positive = sum(counts[o] for o in POSITIVE[field])
        ratings[field] = {
            "counts": counts,
            "answered": answered,
            "positive_pct": round(positive / answered * 100) if answered else None,
        }

    # "most commonly reported repetitive tasks" — from profiles, never invented
    reported_tasks, missed_tasks = [], []
    for s in sessions:
        profile = db.load_work_profile(s["id"])
        if profile:
            reported_tasks.extend(profile.get("recurring_tasks", []))
    for r in rows:
        if r.get("wished_task"):
            missed_tasks.append(r["wished_task"])

    def verbatim(field):
        return [{"code": r["code"], "text": r[field].strip(), "created_at": r["created_at"]}
                for r in rows if (r.get(field) or "").strip()]

    return {
        "session_type": session_type,
        "participants": len(sessions),
        "completed_feedback": len(rows),
        "funnel": funnel,
        "completed_count": len(completed),
        "assistance": {
            "marked": len(marked),
            "unassisted": len(unassisted),
            "counts": {level: sum(1 for x in marked if x["assistance_level"] == level)
                       for level in ("No assistance", "Minor assistance", "Significant assistance")},
        },
        "median_minutes": (sorted(durations)[len(durations) // 2] if durations else None),
        "understanding_texts": verbatim("product_understanding_text"),
        "missed_texts": verbatim("missed_or_wrong"),
        "wished_texts": verbatim("wished_task"),
        "permission_texts": verbatim("permission_reason"),
        "investigate_texts": verbatim("investigate_reason"),
        "notes": db.list_notes(),
        "errors": [e for e in db.list_errors()
                   if e.get("session_type") in (None, session_type)],
        "sessions": [{
            "id": x["id"], "code": x["code"], "stage": x["stage"],
            "industry": x.get("industry"), "role": x.get("role"),
            "assistance_level": x.get("assistance_level"),
            "completed": bool(x.get("feedback_completed")),
            "minutes": minutes_between(x.get("pilot_started"), x.get("feedback_completed")),
            "created_at": x["created_at"],
        } for x in sessions],
        "industries": distribution([s.get("industry") for s in sessions]),
        "roles": distribution([s.get("role") for s in sessions]),
        "company_sizes": distribution([s.get("company_size") for s in sessions]),
        "ratings": ratings,
        "reported_repetitive_tasks": reported_tasks[:40],
        "missed_tasks": missed_tasks[:40],
        "qualitative": [{
            "code": r["code"],
            "finding_title": r.get("finding_title"),
            "finding_confidence": r.get("finding_confidence"),
            "missed_or_wrong": r.get("missed_or_wrong"),
            "wished_task": r.get("wished_task"),
            "permission_reason": r.get("permission_reason"),
            "created_at": r["created_at"],
        } for r in rows],
    }


CSV_COLUMNS = [
    "pilot_session_id", "session_type", "industry", "role", "company_size",
    "assistance_level", "minutes_to_complete",
    "finding_title", "finding_confidence", "understanding_rating", "repetition_rating",
    "usefulness_rating", "investigate_rating", "investigate_reason",
    "continued_use_rating", "permission_comfort", "product_understanding_text",
    "missed_task", "feedback", "permission_reason", "submitted_at",
]


def pilot_csv(session_type="REAL_PILOT"):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in db.all_feedback(session_type):
        minutes = None
        if r.get("pilot_started") and r.get("feedback_completed"):
            try:
                minutes = round((datetime.fromisoformat(r["feedback_completed"].replace("Z", "+00:00"))
                                 - datetime.fromisoformat(r["pilot_started"].replace("Z", "+00:00"))
                                 ).total_seconds() / 60, 1)
            except ValueError:
                minutes = None
        writer.writerow([
            r["code"], r["session_type"], r.get("industry"), r.get("role"),
            r.get("company_size"), r.get("assistance_level"), minutes,
            r.get("finding_title"), r.get("finding_confidence"),
            r.get("understanding_rating"), r.get("repetition_rating"),
            r.get("usefulness_rating"), r.get("investigate_rating"),
            r.get("investigate_reason"), r.get("continued_use_rating"),
            r.get("permission_comfort"), r.get("product_understanding_text"),
            r.get("wished_task"), r.get("missed_or_wrong"),
            r.get("permission_reason"), r["created_at"],
        ])
    return buf.getvalue()
