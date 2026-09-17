"""End-to-end acceptance test for the FlowMind AI Business Consultant MVP.

Drives the entire pilot experience in a real Chromium with the real extension
loaded, exactly as a participant would, starting where a real participant starts:

  /pilot -> consent -> context -> interview -> app access -> work analysis
  -> finding (observed / reported / inferred) -> feedback -> dashboard
  -> facilitator's pilot-results page

It also exercises the failure paths the pilot has to survive: going back,
refreshing mid-flow, a second tab, no detected workflow, and a backend fault.

Run with:  xvfb-run -a python3 tests/e2e.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
SHOTS = os.path.join(ROOT, "tests", "screenshots")
REPETITIONS = int(os.environ.get("FM_REPS", "4"))
DWELL = float(os.environ.get("FM_DWELL", "2.2"))

results = []

# Replies keyed by the question FlowMind actually asks, the way a participant answers.
REPLIES = {
    "workday": "I handle customer requests. They come in by email all morning, I put each "
               "order into our operations spreadsheet, and then I update the same customer "
               "in our CRM.",
    "transfer": "Yes — the order details go from the email into the spreadsheet and then into "
                "the CRM, all typed by hand.",
    "company": "We're a small B2B supplier. I work in a team of five.",
    "frequency": "Probably 15 to 20 times a day. It is completely manual and quite tedious.",
    "hours": "Maybe 8 hours a week in total.",
    "repetitive": "The weekly delivery report as well, I rebuild it every Sunday.",
    "tools": "The email inbox, the spreadsheet and the CRM.",
    "duration": "About four or five minutes for each one.",
    "slow": "The report takes far longer than it should.",
    "wish": "Copying the order details into the CRM by hand.",
    "workaround": "No real shortcut, I just keep all three tabs open.",
}
ANSWERS = [REPLIES["workday"]]


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    return ok


def api(path, method="GET", payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


MILESTONES = ["pilot_started", "context_completed", "interview_completed",
              "permissions_completed", "analysis_started", "analysis_completed",
              "finding_viewed", "feedback_started", "feedback_completed"]


def milestones():
    """The funnel timestamps recorded so far for the live session."""
    s = api("/api/state")["session"] or {}
    return {m: s.get(m) for m in MILESTONES}


def reached(name):
    return bool(milestones().get(name))


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, name), full_page=True)


def main():
    os.makedirs(SHOTS, exist_ok=True)
    print("\nFlowMind — AI Business Consultant · acceptance test")
    print("=" * 66)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir="/tmp/claude-0/fm-profile",
            headless=False,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
                  "--no-first-run", "--no-default-browser-check"],
            viewport={"width": 1360, "height": 940},
        )

        deadline, worker = time.time() + 15, None
        while time.time() < deadline and not worker:
            worker = ctx.service_workers[0] if ctx.service_workers else None
            if not worker:
                time.sleep(0.4)
        check("Extension service worker starts", worker is not None)
        ext_id = worker.url.split("/")[2] if worker else None

        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ------------------------------------------------------------ welcome
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector("#start-pilot", timeout=15000)
        body0 = page.inner_text("body").lower()
        check("Welcome answers what FlowMind is and what to do next",
              "ai business consultant" in body0
              and "start my work analysis" in body0
              and "private by design" in body0)
        check("Welcome shows the four-step journey, not a dashboard",
              page.locator(".journey .jstep").count() == 4
              and page.locator("canvas, table").count() == 0)
        check("Extension is detected by the app",
              page.evaluate("document.documentElement.dataset.flowmindExtension") == "active")
        shot(page, "01-welcome.png")

        # ------------------------------------------------------- /pilot entry
        page.goto(BASE + "/pilot", wait_until="load")
        page.wait_for_selector("#start-pilot-run", timeout=15000)
        entry = page.inner_text("body").lower()
        check("A dedicated /pilot entry point exists for real participants",
              "help us test flowmind" in entry and "start pilot" in entry)
        check("The pilot entry collects no identifying details",
              "no name, no email" in entry
              and page.locator("input, textarea").count() == 0)
        shot(page, "01b-pilot-entry.png")
        page.click("#start-pilot-run")
        page.wait_for_selector("#allow", timeout=15000)

        sess = api("/api/state")["session"]
        check("The /pilot route always creates a REAL_PILOT session, never a demo",
              sess["session_type"] == "REAL_PILOT", sess["session_type"])
        check("Participants are identified only by an anonymous code",
              re.fullmatch(r"FM-PILOT-\d{4}", sess["code"]) is not None
              and not any("name" in k or "email" in k for k in sess), sess["code"])
        check("Milestone recorded: pilot started", reached("pilot_started"))

        # ------------------------------------------------------------ consent
        page.wait_for_selector("#allow", timeout=10000)
        consent = page.inner_text("body")
        check("Consent screen lists what is and isn't collected",
              "FlowMind may analyze" in consent and "does not collect" in consent
              and "Passwords" in consent)
        check("Consent screen is honest about prototype scope",
              "does not give FlowMind access to your computer" in consent)
        shot(page, "02-consent.png")
        page.click("#allow")

        # ------------------------------------------------------------ context
        page.wait_for_selector("#role", timeout=10000)
        page.fill("#role", "Sales Operations Coordinator")
        page.click("button.pick[data-industry='Professional Services']")
        page.click("button.option[data-size='11-50']")
        check("Phase indicator names where the participant is",
              "About you" in page.inner_text(".phases")
              and page.locator(".phase.now").count() == 1)
        shot(page, "03-context.png")
        page.click("#context-next")

        # ---------------------------------------------------------- interview
        page.wait_for_selector("#answer", timeout=10000)
        check("Milestone recorded: work context completed", reached("context_completed"))
        asked, slot = 0, "workday"
        for _ in range(9):
            if page.locator("#answer").count() == 0:
                break
            page.fill("#answer", REPLIES.get(slot, "Not really, no."))
            page.click("#send")
            asked += 1
            page.wait_for_timeout(1200)
            if page.locator("#after-interview").count():
                break
            spoken = [m for m in api("/api/interview")["transcript"]
                      if m["role"] == "consultant" and m["slot"]]
            slot = spoken[-1]["slot"] if spoken else "wish"
        check("Interview asked adaptive follow-up questions", asked >= 4, f"{asked} answers")

        # FlowMind must never quote back a figure the participant did not give.
        convo = api("/api/interview")["transcript"]
        first_number = next((i for i, m in enumerate(convo)
                             if m["role"] == "employee" and any(c.isdigit() for c in m["text"])),
                            len(convo))
        check("No number is stated back before the participant gives one",
              not any("hour" in m["text"].lower()
                      for m in convo[:first_number] if m["role"] == "consultant"))

        asked_slots = {m["slot"] for m in api("/api/interview")["transcript"]
                       if m["role"] == "consultant" and m["slot"]}
        check("Interview covers company, work, tasks and hours",
              {"workday", "company"} <= asked_slots
              and bool({"hours", "frequency", "duration"} & asked_slots),
              ", ".join(sorted(asked_slots)))

        check("Interview shows what it has learned so far",
              page.locator("#learned .chip").count() >= 2,
              page.inner_text("#learned")[:70].replace("\n", " "))

        page.wait_for_selector("#after-interview", timeout=15000)
        suggestions = api("/api/suggestions")["suggestions"]
        check("Automation suggestions come out of the conversation alone",
              len(suggestions) >= 1, "; ".join(s["title"] for s in suggestions[:2]))
        check("Suggestions are labelled as reported, not measured",
              all(s["evidence"] == "REPORTED" for s in suggestions)
              and "reported" in page.inner_text("#interview-close").lower())
        check("Suggestions carry a concrete how-to",
              all(len(s["how"]) > 60 for s in suggestions))
        shot(page, "04b-interview-suggestions.png")
        profile = api("/api/profile")["profile"]
        check("Work profile extracted from the conversation",
              bool(profile["role"]) and len(profile["primary_tools"]) >= 2
              and len(profile["recurring_tasks"]) >= 1,
              ", ".join(profile["primary_tools"]))
        check("Profile captures company context and reported hours",
              bool(profile["company_context"]) and profile["hours_per_week"],
              f"{profile['hours_per_week']}h/week")
        check("Milestone recorded: interview completed", reached("interview_completed"))

        # a participant who refreshes mid-flow must land back where they were
        page.reload(wait_until="load")
        page.wait_for_selector("#after-interview", timeout=15000)
        check("Refreshing mid-flow resumes the same step with the answers intact",
              REPLIES["workday"][:40] in page.inner_text("#chat")
              and "#/step/interview" in page.url, page.url)
        page.click("#after-interview")

        # ------------------------------------------------- going back a step
        page.wait_for_selector("#perms-next", timeout=15000)
        check("Each step has its own address", "#/step/permissions" in page.url, page.url)

        page.click("#flow-back")                       # permissions -> interview
        page.wait_for_selector("#chat", timeout=10000)
        check("Back button returns to the previous step",
              len(page.locator(".bubble").all()) >= 2 and "#/step/interview" in page.url)
        check("Going back keeps the interview transcript",
              REPLIES["workday"][:40] in page.inner_text("#chat"))

        # now the browser's own Back button, several steps in a row
        page.go_back()
        page.wait_for_selector("#role", timeout=10000)
        check("Browser Back reaches the work-context step with answers intact",
              page.input_value("#role") == "Sales Operations Coordinator"
              and page.locator("button.pick.selected").count() == 1
              and "#/step/context" in page.url, page.url)

        page.go_back()
        page.wait_for_selector("#allow", timeout=10000)
        check("Browser Back again reaches the consent step",
              "needs your permission" in page.inner_text("body")
              and "#/step/consent" in page.url, page.url)

        page.go_forward()
        page.wait_for_timeout(1200)
        check("Forward does not skip a step the participant has not completed",
              page.locator("#industry").count() == 1 or page.locator("#allow").count() == 1)
        if page.locator("#allow").count():
            page.click("#allow")
        page.wait_for_selector("#role", timeout=10000)
        page.click("#context-next")
        page.wait_for_selector("#answer", timeout=10000)
        page.click("#skip")
        page.wait_for_selector("#after-interview", timeout=10000)
        page.click("#after-interview")

        # -------------------------------------------------------- app access
        page.wait_for_selector("#perms-next", timeout=15000)
        shot(page, "04-interview-then-access.png")
        perms = api("/api/permissions")["permissions"]
        slack = next(p for p in perms if p["app_label"] == "Slack")
        check("Slack is not approved by default", slack["allowed"] == 0)
        check("Demo applications are approved by default",
              all(next(p["allowed"] for p in perms if p["app_label"] == a)
                  for a in ("FlowMail", "FlowSheet", "FlowCRM")))
        page.click(f".toggle[data-perm='{slack['id']}']")
        page.wait_for_timeout(600)
        check("Toggling an application changes the approved list",
              next(p["allowed"] for p in api("/api/permissions")["permissions"]
                   if p["app_label"] == "Slack") == 1)
        page.click(f".toggle[data-perm='{slack['id']}']")
        page.wait_for_timeout(600)
        shot(page, "05-app-access.png")
        check("Customer-service desks are offered as approved apps",
              any(p["category"] == "Support" for p in perms),
              ", ".join(p["app_label"] for p in perms if p["category"] == "Support"))
        page.click("#perms-next")

        # --------------------------------------------------- ready briefing
        page.wait_for_selector("#begin-analysis", timeout=10000)
        ready = page.inner_text("body").lower()
        check("A briefing sets expectations before recording starts",
              "i'm ready" in ready and "what i'll look for" in ready)
        check("Nothing is recorded until the participant starts the analysis",
              api("/api/analysis/status")["recording"] is False)
        check("Milestone recorded: app access completed", reached("permissions_completed"))
        page.wait_for_timeout(500)
        shot(page, "05b-ready.png")
        page.click("#begin-analysis")

        # ------------------------------------------------------- observation
        page.wait_for_selector("#finish", timeout=10000)
        check("Work analysis starts recording", api("/api/analysis/status")["recording"])
        check("Milestone recorded: analysis started", reached("analysis_started"))
        shot(page, "06-observing.png")

        # a second tab must show the same session, not start a competing one
        second = ctx.new_page()
        second.goto(BASE + "/", wait_until="load")
        second.wait_for_timeout(1800)
        check("A second tab joins the same session instead of starting another",
              second.locator("#finish").count() == 1
              and api("/api/pilot-results")["participants"] == 1,
              f"{api('/api/pilot-results')['participants']} participant(s)")
        second.close()

        # pause and resume, the way a participant interrupted by a colleague would
        page.click("#pause")
        page.wait_for_timeout(900)
        paused = api("/api/analysis/status")
        check("Pausing stops recording immediately",
              paused["paused"] is True and paused["recording"] is False)
        page.click("#pause")
        page.wait_for_timeout(900)
        check("Resuming starts recording again, without losing the session",
              api("/api/analysis/status")["recording"] is True
              and api("/api/state")["session"]["code"] == sess["code"])
        page.wait_for_timeout(6000)     # let the extension pick the resumed config up

        print(f"\n  Performing {REPETITIONS} repetitions of the guided test…")
        bubble_at = None
        clipboard_fallbacks = 0
        for rep in range(1, REPETITIONS + 1):
            order = next(o for o in api("/api/demo/orders")["orders"] if not o["mail_done"])
            oid = order["id"]

            page.goto(BASE + "/demo/mail", wait_until="load")
            page.wait_for_selector("button:has-text('Copy address')")
            page.wait_for_timeout(int(DWELL * 1000))
            page.click("button:has-text('Copy address')")
            page.wait_for_timeout(400)
            if rep >= 3 and bubble_at is None and page.locator("#flowmind-bubble-root .fm-orb").count():
                bubble_at = rep
                page.click("#flowmind-bubble-root .fm-orb")
                page.wait_for_timeout(600)
                shot(page, "07-contextual-hint.png")
                page.click("#flowmind-bubble-root .fm-btn-ghost")

            page.click("a.btn:has-text('Open FlowSheet')")
            page.wait_for_url("**/demo/sheet")
            page.wait_for_selector("button:has-text('Edit')")
            page.wait_for_timeout(int(DWELL * 1000))
            page.locator("tr.target").locator("button:has-text('Edit')").click()
            cell = page.locator(f"#addr-{oid}")
            cell.click()
            page.keyboard.press("Control+V")
            page.wait_for_timeout(300)
            if not cell.input_value().strip():
                clipboard_fallbacks += 1
                cell.fill(order["new_value"])
            page.click("button:has-text('Save')")
            page.wait_for_selector(f"button:has-text('Copy {oid}')")
            page.click(f"button:has-text('Copy {oid}')")
            page.wait_for_timeout(400)
            page.click("a.btn:has-text('Open FlowCRM')")

            page.wait_for_url("**/demo/crm")
            page.wait_for_selector("#ref")
            page.wait_for_timeout(int(DWELL * 1000))
            page.click("#ref")
            page.keyboard.press("Control+V")
            page.wait_for_timeout(300)
            if not page.locator("#ref").input_value().strip():
                clipboard_fallbacks += 1
                page.fill("#ref", oid)
            page.select_option("#status", "address_updated")
            page.click("button:has-text('Save customer record')")
            page.wait_for_selector("a.btn:has-text('Back to FlowMail')")
            page.click("a.btn:has-text('Back to FlowMail')")

            page.wait_for_url("**/demo/mail")
            page.wait_for_selector("button:has-text('Mark as handled')")
            page.wait_for_timeout(int(DWELL * 1000))
            page.click("button:has-text('Mark as handled')")
            page.wait_for_timeout(700)
            print(f"    repetition {rep}/{REPETITIONS} complete ({oid})")

        page.goto(BASE + "/", wait_until="load")
        page.wait_for_timeout(2600)

        events = api("/api/activity")["events"]
        visits = [e for e in events if e["type"] == "app_visit"]
        clips = [e for e in events if e["type"] in ("copy", "paste")]
        check("Extension captured real activity", len(visits) >= 8, f"{len(visits)} visits")
        check("Copy/paste events counted", len(clips) > 0, f"{len(clips)} clipboard events")
        check("Only approved applications were stored",
              set(e["application"] for e in events) <= {"FlowMail", "FlowSheet", "FlowCRM"},
              ", ".join(sorted({e["application"] for e in events})))
        check("Stored events carry no content fields",
              all(set(e) <= {"id", "type", "application", "category", "started_at",
                             "ended_at", "duration_ms", "source"} for e in events))
        check("Contextual hint appeared during the analysis", bubble_at is not None,
              f"repetition {bubble_at}" if bubble_at else "not shown")
        by_app = {}
        for e in clips:
            by_app.setdefault((e["application"], e["type"]), 0)
            by_app[(e["application"], e["type"])] += 1
        check("Copy events captured in every app the task copies from",
              by_app.get(("FlowMail", "copy"), 0) >= REPETITIONS
              and by_app.get(("FlowSheet", "copy"), 0) >= REPETITIONS,
              ", ".join(f"{a} {t}={n}" for (a, t), n in sorted(by_app.items())))
        check("Real clipboard carried the values between the demo apps",
              clipboard_fallbacks == 0, f"{clipboard_fallbacks} fallbacks")

        page.wait_for_selector("#finish", timeout=10000)
        page.click("#finish")

        # ----------------------------------------------------- the aha moment
        page.wait_for_selector("#see-analysis", timeout=15000)
        aha = page.inner_text("body")
        check("A distinct moment announces the finding",
              "found something worth looking at" in aha.lower())
        check("The aha moment already separates the three kinds of evidence",
              all(w in aha.lower() for w in ("observed", "reported", "inferred")))
        ms = milestones()
        check("Milestone recorded: analysis completed, finding not yet counted as read",
              bool(ms["analysis_completed"]) and not ms["finding_viewed"])
        page.wait_for_timeout(700)          # let the entrance animation settle
        shot(page, "07b-aha.png")
        page.click("#see-analysis")

        # ------------------------------------------------------------ finding
        page.wait_for_selector("#to-feedback", timeout=15000)
        body = page.inner_text("body")
        finding = api("/api/findings")["findings"][0]
        check("A finding was produced", bool(finding), finding["title"])
        check("Milestone recorded: finding viewed", reached("finding_viewed"))
        check("Finding combines both evidence sources",
              "observed" in body.lower() and "reported" in body.lower() and "inferred" in body.lower())
        check("Reported evidence quotes the participant",
              len(finding["reported"]["quotes"]) >= 1)
        check("Confidence is stated with a reason",
              finding["confidence"] in ("HIGH", "MEDIUM", "LOW") and bool(finding["confidence_reason"]),
              finding["confidence"])
        check("Interview context contributed to the score",
              next(c["points"] for c in api(f"/api/findings/{finding['id']}")["components"]
                   if c["key"] == "context") > 0)
        page.click("#why-score")
        page.wait_for_timeout(400)
        comps = page.locator("table.components tr")
        check("Score breakdown shows five stored components", comps.count() == 5)
        detail = api(f"/api/findings/{finding['id']}")
        check("Components sum to the score",
              abs(sum(c["points"] for c in detail["components"]) - finding["score"]) <= 1,
              f"{finding['score']}/100")
        check("Language is hedged, not asserted",
              any(w in finding["narrative"]["possible_issue"].lower()
                  for w in ("may ", "appears", "possible", "potential")))
        check("With no AI available the offline engine answers, and the page says which",
              api("/api/state")["ai_configured"] is False
              and finding["analysis_source"] != "ai"
              and "rules engine (offline fallback)" in body.lower(),
              finding["analysis_source"])
        shot(page, "08-finding.png")

        # determinism
        first = api(f"/api/findings/{finding['id']}")["score"]
        api("/api/monitoring", "POST", {"paused": False})
        check("Opportunity score is deterministic",
              api(f"/api/findings/{finding['id']}")["score"] == first, str(first))

        # ---------------------------------------------- the popup and console
        if ext_id:
            popup = ctx.new_page()
            popup.goto(f"chrome-extension://{ext_id}/popup.html")
            popup.wait_for_timeout(2200)
            ptext = popup.inner_text("body")
            check("Popup shows approved applications and status",
                  "FlowMail" in ptext and ("Analyzing" in ptext or "Not analyzing" in ptext))
            popup.screenshot(path=os.path.join(SHOTS, "09-popup.png"))
            popup.close()

        # ----------------------------------------------------------- feedback
        page.click("#to-feedback")
        page.wait_for_selector("#submit-feedback", timeout=10000)
        check("Milestone recorded: feedback started", reached("feedback_started"))

        fb_text = page.inner_text(".fb").lower()
        check("Feedback asks what the participant thinks the product does",
              "in your own words, what do you think flowmind does" in fb_text)
        check("Feedback asks whether the business should investigate the finding",
              "would you recommend your business investigate" in fb_text)
        questions = page.locator(".fbq .label").all_inner_texts()
        check("Feedback wording does not lead the participant",
              not any(w in " ".join(questions).lower()
                      for w in ("do you agree", "how helpful", "how useful was",
                                "don't you", "isn't it", "impressive")),
              f"{len(questions)} questions")
        check("Every rating question offers a negative answer",
              all(page.locator(f".choice[data-q='{q}'][data-v='{neg}']").count() == 1
                  for q, neg in [("understanding_rating", "No"), ("repetition_rating", "No"),
                                 ("usefulness_rating", "Not useful"), ("investigate_rating", "No"),
                                 ("continued_use_rating", "No"), ("permission_comfort", "No")]))

        for q, v in [("understanding_rating", "Yes"), ("repetition_rating", "Yes"),
                     ("usefulness_rating", "Very useful"), ("investigate_rating", "Yes"),
                     ("continued_use_rating", "Yes"), ("permission_comfort", "Yes")]:
            page.click(f".choice[data-q='{q}'][data-v='{v}']")
        page.fill("#fb-investigate-why", "It is the same three systems every single time.")
        page.fill("#fb-understanding",
                  "It watches which work apps I use and tells me which bits repeat.")
        page.fill("#fb-missed", "It did not notice that I also send a confirmation email afterwards.")
        page.fill("#fb-wished", "Building the weekly delivery report.")
        page.fill("#fb-reason", "Choosing the apps myself is what makes it acceptable.")
        shot(page, "10-feedback.png")

        # refreshing on the feedback screen must not lose the step
        page.reload(wait_until="load")
        page.wait_for_selector("#submit-feedback", timeout=15000)
        check("Refreshing the feedback screen returns to the feedback screen",
              "#/step/feedback" in page.url and api("/api/pilot-results")["completed_feedback"] == 0,
              page.url)
        for q, v in [("understanding_rating", "Yes"), ("repetition_rating", "Yes"),
                     ("usefulness_rating", "Very useful"), ("investigate_rating", "Yes"),
                     ("continued_use_rating", "Yes"), ("permission_comfort", "Yes")]:
            page.click(f".choice[data-q='{q}'][data-v='{v}']")
        page.fill("#fb-investigate-why", "It is the same three systems every single time.")
        page.fill("#fb-understanding",
                  "It watches which work apps I use and tells me which bits repeat.")
        page.fill("#fb-missed", "It did not notice that I also send a confirmation email afterwards.")
        page.fill("#fb-wished", "Building the weekly delivery report.")
        page.fill("#fb-reason", "Choosing the apps myself is what makes it acceptable.")
        page.click("#submit-feedback")
        page.wait_for_selector("#new-pilot-2", timeout=10000)
        check("Thank-you screen is reached", "Thank you" in page.inner_text("h1"))
        shot(page, "11-done.png")

        pilot = api("/api/pilot-results")
        check("Feedback persisted to the pilot results",
              pilot["completed_feedback"] == 1 and pilot["ratings"]["usefulness_rating"]["positive_pct"] == 100)
        check("The two new validation questions are stored",
              pilot["ratings"]["investigate_rating"]["answered"] == 1
              and len(pilot["understanding_texts"]) == 1)
        check("Qualitative answers are stored verbatim, not rewritten",
              pilot["understanding_texts"][0]["text"]
              == "It watches which work apps I use and tells me which bits repeat.")
        check("Pilot analytics report real industries and roles",
              "Professional Services" in pilot["industries"] and
              "Sales Operations Coordinator" in pilot["roles"],
              f"{list(pilot['industries'])} / {list(pilot['roles'])}")

        # ------------------------------------------------------------- funnel
        ms = milestones()
        check("All nine funnel milestones were recorded",
              all(ms[m] for m in MILESTONES),
              ", ".join(m for m in MILESTONES if not ms[m]) or "all")
        check("Milestones were recorded in the order the participant met them",
              [ms[m] for m in MILESTONES] == sorted(ms[m] for m in MILESTONES))
        funnel = {f["key"]: f for f in pilot["funnel"]}
        check("The funnel counts real milestones, not estimates",
              all(funnel[k]["count"] == 1 and funnel[k]["pct"] == 100 for k in funnel),
              ", ".join(f"{f['label']} {f['count']}" for f in pilot["funnel"]))
        check("Median time to complete is measured, not guessed",
              pilot["median_minutes"] is not None, f"{pilot['median_minutes']} min")

        # ---------------------------------------------------------- dashboard
        page.goto(BASE + "/#/overview", wait_until="load")
        page.wait_for_timeout(1600)
        ov = page.inner_text("body")
        check("Overview greets and summarises", "Here's what FlowMind learned" in ov)
        check("Overview shows where the workday goes", "where your workday goes" in ov.lower())
        check("Overview shows the work profile", "work profile" in ov.lower())
        shot(page, "12-overview.png")

        page.goto(BASE + "/#/consultant", wait_until="load")
        page.wait_for_selector("#chat-send", timeout=10000)
        page.fill("#chat-input", "Why did you flag this workflow?")
        page.click("#chat-send")
        page.wait_for_selector(".bubble.typing", state="detached", timeout=20000)
        page.wait_for_timeout(600)
        chat = page.inner_text("#chat")
        check("Consultant answers from stored evidence",
              "Customer Request Processing" in chat or "confidence" in chat.lower())
        page.fill("#chat-input", "Is there anything you need to ask me?")
        page.click("#chat-send")
        page.wait_for_selector(".bubble.typing", state="detached", timeout=20000)
        page.wait_for_timeout(600)
        shot(page, "13-consultant.png")
        thread = api("/api/consultant")["thread"]
        check("Consultant chat persists", len(thread) >= 4, f"{len(thread)} messages")

        page.goto(BASE + "/#/overview", wait_until="load")
        page.wait_for_timeout(1200)
        page.click("#nav a[data-route='privacy']")
        page.wait_for_timeout(1200)
        page.go_back()
        page.wait_for_timeout(1400)
        check("Browser Back works between dashboard tabs",
              "Here's what FlowMind learned" in page.inner_text("body"), page.url)

        page.goto(BASE + "/#/activity", wait_until="load")
        page.wait_for_timeout(1800)
        check("Activity timeline matches captured events",
              page.locator(".tl-item").count() >= len(visits))
        shot(page, "14-activity.png")

        page.goto(BASE + "/#/privacy", wait_until="load")
        page.wait_for_timeout(1200)
        pv = page.inner_text("body")
        check("Privacy page shows both sides and app permissions",
              "what flowmind can see" in pv.lower() and "what flowmind cannot see" in pv.lower()
              and "app permissions" in pv.lower())
        shot(page, "15-privacy.png")

        page.goto(BASE + "/#/report", wait_until="load")
        page.wait_for_timeout(1600)
        rp = page.inner_text("body")
        check("Business review renders with an executive summary",
              "executive summary" in rp.lower() and "recommended next steps" in rp.lower())
        shot(page, "16-report.png")

        # ------------------------------------- assistance, iteration log, faults
        before = api("/api/pilot-results")
        check("An unmarked session is never counted as unassisted",
              before["completed_count"] == 1 and before["assistance"]["unassisted"] == 0
              and before["assistance"]["marked"] == 0,
              f"completed={before['completed_count']} unassisted={before['assistance']['unassisted']}")

        api("/api/pilot/error", "POST", {"route": "#/step/observe", "kind": "extension_missing",
                                         "detail": "No FlowMind extension detected"})
        errs = api("/api/pilot-results")["errors"]
        check("Technical faults are logged against the session",
              any(e["kind"] == "extension_missing" for e in errs), f"{len(errs)} logged")
        check("Fault logs carry no work content",
              all(set(e) >= {"route", "kind"} and "text" not in e and "content" not in e
                  for e in errs))

        page.goto(BASE + "/pilot-results", wait_until="load")
        page.wait_for_selector(".assist button", timeout=15000)
        check("Pilot results page renders", "Pilot results" in page.inner_text("h1"))
        check("A small sample is flagged rather than presented as a percentage",
              "small sample" in page.inner_text("body").lower())
        page.click(".assist button[data-level='No assistance']")
        page.wait_for_timeout(1200)
        after = api("/api/pilot-results")
        check("Assistance is marked by the facilitator, on the results page only",
              after["assistance"]["marked"] == 1 and after["assistance"]["unassisted"] == 1)
        check("The participant is never asked about assistance",
              "assistance" not in fb_text)

        page.fill("#note-problem", "Participant paused at the app-access screen.")
        page.fill("#note-change", "Added a one-line explanation of why each app is listed.")
        page.fill("#note-reason", "They did not know the list was editable.")
        page.click("#note-add")
        page.wait_for_timeout(1200)
        notes = api("/api/pilot-results")["notes"]
        check("The iteration log records only what the facilitator entered",
              len(notes) == 1 and notes[0]["problem"].startswith("Participant paused"),
              f"{len(notes)} entries")
        shot(page, "17b-pilot-results-funnel.png")
        page.click("[data-delnote]")
        page.wait_for_timeout(1200)
        check("Iteration-log entries can be removed",
              len(api("/api/pilot-results")["notes"]) == 0)

        # ------------------------------------------- research integrity check
        api("/api/pilot/start", "POST", {"session_type": "DEMO"})
        real = api("/api/pilot-results")
        demo = api("/api/pilot-results?session_type=DEMO")
        check("Demo sessions are excluded from validation statistics",
              real["participants"] == 1 and demo["participants"] == 1,
              f"real={real['participants']} demo={demo['participants']}")

        csv_text = urllib.request.urlopen(BASE + "/api/pilot-results.csv").read().decode()
        check("CSV export contains the anonymised response",
              "pilot_session_id" in csv_text and "FM-PILOT-0001" in csv_text
              and len(csv_text.strip().splitlines()) == 2)
        check("CSV carries the new validation columns",
              all(c in csv_text.splitlines()[0] for c in
                  ("investigate_rating", "product_understanding_text",
                   "assistance_level", "minutes_to_complete")))

        # a scope with no answers must show no percentage at all
        demo_stats = api("/api/pilot-results?session_type=DEMO")
        check("No percentage is calculated when nobody has answered",
              all(b["positive_pct"] is None and b["answered"] == 0
                  for b in demo_stats["ratings"].values()))
        page.click("#scope button[data-type='DEMO']")
        page.wait_for_timeout(1400)
        snap = page.locator(".snapshot .snap .v").all_inner_texts()
        check("The results page prints '—' instead of an invented percentage",
              snap.count("—") >= 6, ", ".join(snap))
        page.click("#scope button[data-type='REAL_PILOT']")
        page.wait_for_timeout(1400)
        shot(page, "17-pilot-results.png")

        # ------------------------------------------ insufficient-evidence path
        api("/api/pilot/start", "POST", {"session_type": "DEMO"})
        api("/api/pilot/consent", "POST")
        api("/api/pilot/context", "POST", {"industry": "Retail", "role": "Owner",
                                           "company_size": "1-10"})
        api("/api/interview", "POST", {"text": "I do a bit of everything."})
        api("/api/interview/finish", "POST")
        api("/api/analysis/start", "POST")

        # finishing too early: the participant sees this, not a fabricated pattern
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector("#finish", timeout=15000)
        page.click("#finish")
        page.wait_for_selector("#continue-analysis", timeout=15000)
        early = page.inner_text("body").lower()
        check("Finishing too early gives an honest empty state, not a fabricated workflow",
              "i don't have enough activity yet" in early
              and "rather tell you that than invent a pattern" in early)
        check("The empty state offers a way forward instead of a dead end",
              page.locator("#continue-analysis").count() == 1
              and page.locator("#gen-demo").count() == 1)
        shot(page, "18-not-enough-evidence.png")
        finish = api("/api/analysis/finish", "POST")
        check("Honest 'not enough evidence' instead of a fabricated workflow",
              finish["sufficient"] is False and "don't have enough activity" in finish["message"])

        gen = api("/api/demo/generate?repetitions=8", "POST")
        check("Demo workday runs through the same pipeline",
              len(gen["findings"]) >= 1 and gen["findings"][0]["repetitions"] == 8,
              f"score {gen['findings'][0]['score']} {gen['findings'][0]['confidence']}")
        acts = api("/api/activity")["events"]
        check("Generated activity is labelled as simulated",
              all(e["source"] == "simulated" for e in acts))

        # ------------------------------- backing out of the very first step
        demo_before = api("/api/pilot-results?session_type=DEMO")["participants"]
        api("/api/pilot/start", "POST", {"session_type": "DEMO"})
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector("#allow", timeout=10000)      # resumes at consent
        page.wait_for_timeout(900)
        banner = page.inner_text("#build-banner")
        check("Page confirms it is talking to a matching server",
              "connected" in banner.lower() and "older code" not in banner.lower(), banner[:60])

        page.click("#flow-back")
        page.wait_for_selector("#start-pilot", timeout=10000)
        check("Back from the first step returns to the welcome screen",
              "your ai business consultant" in page.inner_text("body").lower()
              and page.locator("#start-pilot").count() == 1)
        check("Backing out before answering leaves no phantom participant",
              api("/api/pilot-results?session_type=DEMO")["participants"] == demo_before,
              f"{demo_before} -> {api('/api/pilot-results?session_type=DEMO')['participants']}")

        ctx.close()

        # ------------------------------------------- the extension is missing
        api("/api/pilot/start", "POST", {"session_type": "DEMO"})
        api("/api/pilot/consent", "POST")
        api("/api/pilot/context", "POST", {"industry": "Retail", "role": "Owner",
                                           "company_size": "1-10"})
        api("/api/interview", "POST", {"text": "Mostly orders and invoices."})
        api("/api/interview/finish", "POST")
        api("/api/analysis/start", "POST")

        plain = pw.chromium.launch(headless=False)          # no extension loaded
        bare = plain.new_page()
        bare.goto(BASE + "/", wait_until="load")
        bare.wait_for_selector("#finish", timeout=15000)
        bare.wait_for_timeout(3500)
        check("Without the extension the app says why nothing is happening",
              "can't see any activity" in bare.inner_text("#no-extension").lower()
              and bare.locator("#no-extension.hidden").count() == 0)
        check("A missing extension is logged as a fault, not read as a drop-off",
              any(e["kind"] == "extension_missing"
                  for e in api("/api/pilot-results?session_type=DEMO")["errors"]))
        bare.screenshot(path=os.path.join(SHOTS, "19-no-extension.png"), full_page=True)
        plain.close()

    return finish_report()


def finish_report():
    print("=" * 66)
    failed = [r for r in results if not r[1]]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("\nFailures:")
        for name, _, detail in failed:
            print(f"  - {name} [{detail}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
