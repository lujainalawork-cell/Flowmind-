"""FlowMind — AI Business Consultant MVP backend.

One FastAPI process serves the API, the FlowMind app, the demo environment and
the private pilot-results page.

    python -m uvicorn server.app:app --port 8000
"""

import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import ai, consultant, db, detection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

ALLOWED_CATEGORIES = {"Email", "Spreadsheet", "CRM", "Support", "Project", "Messaging",
                      "Finance", "ERP", "Other"}

# Bumped whenever the API changes. The browser compares this against its own
# copy and tells the user plainly when the running server is older than the
# page — the one failure mode you cannot see by looking at the screen.
BUILD = "3.1"

db.init_db()

app = FastAPI(title="FlowMind AI Business Consultant", version=BUILD)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def log_failures(request, call_next):
    """A 500 during a pilot session is evidence, not just a log line."""
    try:
        response = await call_next(request)
    except Exception as exc:                                    # noqa: BLE001
        try:
            session = db.active_session()
            db.log_error(session["id"] if session else None, str(request.url.path),
                         type(exc).__name__, str(exc), source="server")
        except Exception:                                       # noqa: BLE001
            pass
        raise
    if response.status_code >= 500:
        try:
            session = db.active_session()
            db.log_error(session["id"] if session else None, str(request.url.path),
                         f"HTTP {response.status_code}", None, source="server")
        except Exception:                                       # noqa: BLE001
            pass
    return response


@app.middleware("http")
async def no_store(request, call_next):
    """This is a prototype that gets edited between runs. Nothing may be cached,
    so a restart always serves the current code rather than yesterday's."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


# ------------------------------------------------------------------- schemas
# extra="forbid" everywhere: an event carrying clipboard text, a URL or a form
# value is rejected by the API rather than quietly stored.

class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["app_visit", "copy", "paste"]
    application: str = Field(max_length=60)
    category: str = Field(max_length=20)
    started_at: str = Field(max_length=40)
    ended_at: Optional[str] = Field(default=None, max_length=40)
    duration_ms: int = Field(default=0, ge=0, le=1000 * 60 * 60 * 12)


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(max_length=64)
    events: List[EventIn] = Field(max_length=500)


class StartPilot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_type: Literal["REAL_PILOT", "DEMO"] = "REAL_PILOT"


class ContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    industry: str = Field(max_length=80)
    role: str = Field(max_length=80)
    company_size: Literal["1-10", "11-50", "51-200", "200+"]


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4000)


class PermissionToggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool


class PermissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(max_length=120)
    app_label: str = Field(max_length=60)
    product: str = Field(default="Custom", max_length=60)
    category: Literal["Email", "Spreadsheet", "CRM", "Support", "Project", "Messaging",
                      "Finance", "ERP", "Other"] = "Other"


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(default="", max_length=120)
    industry: str = Field(default="", max_length=120)
    company_size: str = Field(default="", max_length=20)
    primary_tools: List[str] = Field(default_factory=list, max_length=12)
    recurring_tasks: List[str] = Field(default_factory=list, max_length=12)
    pain_points: List[str] = Field(default_factory=list, max_length=12)


class MonitoringIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paused: bool


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    understanding_rating: Optional[Literal["Yes", "Partially", "No"]] = None
    repetition_rating: Optional[Literal["Yes", "Sometimes", "No"]] = None
    usefulness_rating: Optional[Literal["Very useful", "Somewhat useful", "Not useful"]] = None
    continued_use_rating: Optional[Literal["Yes", "Maybe", "No"]] = None
    permission_comfort: Optional[Literal["Yes", "Maybe", "No"]] = None
    missed_or_wrong: Optional[str] = Field(default=None, max_length=2000)
    wished_task: Optional[str] = Field(default=None, max_length=2000)
    permission_reason: Optional[str] = Field(default=None, max_length=2000)
    product_understanding_text: Optional[str] = Field(default=None, max_length=2000)
    investigate_rating: Optional[Literal["Yes", "Maybe", "No"]] = None
    investigate_reason: Optional[str] = Field(default=None, max_length=2000)


class AssistanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: int
    level: Literal["No assistance", "Minor assistance", "Significant assistance"]


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    problem: str = Field(max_length=600)
    change_made: str = Field(max_length=600)
    reason: Optional[str] = Field(default=None, max_length=600)


class ErrorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str = Field(max_length=120)
    kind: str = Field(max_length=60)
    detail: Optional[str] = Field(default=None, max_length=300)


class GotoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["welcome", "consent", "context", "interview", "permissions", "ready",
                   "observe", "aha", "finding", "feedback", "done"]


class DemoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: Literal["sheet", "crm", "mail"]


# ------------------------------------------------------------------- helpers

def require_session():
    session = db.active_session()
    if not session:
        raise HTTPException(409, "No active FlowMind session. Start one first.")
    return session


def recording_state(session):
    """FlowMind only records while an analysis is explicitly running."""
    if db.get_setting("monitoring_paused") == "1":
        return False
    return bool(session and session.get("analysis_started_at") and not session.get("analysis_ended_at"))


def allowed_app_labels():
    return {p["app_label"] for p in db.allowed_permissions()}


def session_stats(session):
    return detection.stream_stats(db.session_events(session["id"]))


def public_finding(f, full=False):
    out = {
        "id": f["id"], "pattern_key": f["pattern_key"], "title": f["title"],
        "sequence": f["sequence"], "cyclic": f["cyclic"], "repetitions": f["repetitions"],
        "app_count": f["app_count"], "total_time_ms": f["total_time_ms"],
        "avg_duration_ms": f["avg_duration_ms"], "copy_events": f["copy_events"],
        "paste_events": f["paste_events"],
        "clipboard_events": f["copy_events"] + f["paste_events"],
        "transitions": f["transitions"], "score": f["score"], "band": f["band"],
        "confidence": f["confidence"], "confidence_reason": f["confidence_reason"],
        "open_question": f["open_question"], "observed": f["observed"],
        "reported": f["reported"], "narrative": f["narrative"],
        "analysis_source": f["analysis_source"],
        "first_seen": f["first_seen"], "last_seen": f["last_seen"],
    }
    if full:
        out["components"] = f["components"]
        out["occurrences"] = f["occurrences"]
    return out


# ---------------------------------------------------------------- app state

@app.get("/api/health")
def health():
    return {"ok": True, "build": BUILD, "ai_configured": ai.available(),
            "server_time": db.now_iso()}


@app.get("/api/state")
def state():
    session = db.active_session()
    if not session:
        return {"session": None, "monitoring_paused": db.get_setting("monitoring_paused") == "1",
                "ai_configured": ai.available()}
    stats = session_stats(session)
    findings = db.load_findings(session["id"])
    return {
        "session": session,
        "recording": recording_state(session),
        "monitoring_paused": db.get_setting("monitoring_paused") == "1",
        "ai_configured": ai.available(),
        "profile": db.load_work_profile(session["id"]),
        "stats": stats,
        "findings_count": len(findings),
        "top_finding": public_finding(findings[0]) if findings else None,
        "has_feedback": bool([r for r in db.all_feedback(None) if r["session_id"] == session["id"]]),
    }


# --------------------------------------------------------------- pilot flow

@app.post("/api/pilot/start")
def pilot_start(body: StartPilot):
    session = db.create_session(body.session_type)
    db.mark_milestone(session["id"], "pilot_started")
    db.seed_demo_orders(reset=True)
    db.set_setting("monitoring_paused", "0")
    return {"session": session}


@app.post("/api/pilot/consent")
def pilot_consent():
    session = require_session()
    return {"session": db.update_session(session["id"], consent_at=db.now_iso(), stage="context")}


@app.post("/api/pilot/context")
def pilot_context(body: ContextIn):
    session = require_session()
    session = db.update_session(
        session["id"], industry=body.industry.strip(), role=body.role.strip(),
        company_size=body.company_size, stage="interview")
    db.mark_milestone(session["id"], "context_completed")
    if not db.interview_transcript(session["id"]):
        db.add_interview_message(session["id"], "consultant", consultant.OPENING, "workday")
    return {"session": session, "question": consultant.OPENING, "slot": "workday"}


# One step back through the guided flow. Each transition undoes the side effect
# the forward step had, so going back is never a dead end or a half-state.
BACK_STAGES = {
    "consent": "welcome",
    "context": "consent",
    "interview": "context",
    "permissions": "interview",
    "ready": "permissions",
    "observe": "ready",
    "aha": "observe",
    "finding": "aha",
    "feedback": "finding",
    "done": "feedback",
}


FLOW_ORDER = ["welcome", "consent", "context", "interview", "permissions", "ready",
              "observe", "aha", "finding", "feedback", "done"]


def _step_back(session):
    """Move one step back, undoing that step's side effect. Returns (session, stage);
    session is None when the participant has backed out to the welcome screen."""
    current = session["stage"]
    target = BACK_STAGES.get(current)
    if not target:
        return session, current

    if target == "welcome":
        # Nothing has been recorded yet. Drop the session entirely rather than
        # leaving an abandoned row that would inflate the participant count.
        if not db.interview_transcript(session["id"]) and not db.session_events(session["id"]):
            db.delete_session(session["id"])
        else:
            db.update_session(session["id"], active=0)
        return None, "welcome"

    fields = {"stage": target}
    if current == "observe":
        fields.update(analysis_started_at=None, analysis_ended_at=None)  # stop recording
    elif current == "aha":
        fields.update(analysis_ended_at=None)                            # resume recording
    return db.update_session(session["id"], **fields), target


@app.post("/api/pilot/back")
def pilot_back():
    session, stage_name = _step_back(require_session())
    return {"session": session, "stage": stage_name}


@app.post("/api/pilot/goto")
def pilot_goto(body: GotoIn):
    """Rewind to an earlier step. Used when the browser's Back button lands on a
    step URL behind the one the server is on. Forward jumps are never allowed:
    the participant has to actually complete each step."""
    session = db.active_session()
    if not session:
        return {"session": None, "stage": "welcome"}
    if FLOW_ORDER.index(body.stage) >= FLOW_ORDER.index(session["stage"]):
        return {"session": session, "stage": session["stage"]}

    for _ in range(len(FLOW_ORDER)):
        session, stage_name = _step_back(session)
        if session is None:
            return {"session": None, "stage": "welcome"}
        if FLOW_ORDER.index(session["stage"]) <= FLOW_ORDER.index(body.stage):
            break
    return {"session": session, "stage": session["stage"]}


@app.post("/api/pilot/stage")
def pilot_stage(body: TextIn):
    """Advance one step. Only forward, only by one — a participant cannot skip a
    step they have not completed."""
    session = require_session()
    target = body.text.strip()[:40]
    if target not in FLOW_ORDER:
        raise HTTPException(400, "Unknown stage")
    here, there = FLOW_ORDER.index(session["stage"]), FLOW_ORDER.index(target)
    if there != here + 1:
        return {"session": session}
    session = db.update_session(session["id"], stage=target)
    db.mark_milestone(session["id"], {
        "ready": "permissions_completed",
        "finding": "finding_viewed",
        "feedback": "feedback_started",
    }.get(target, ""))
    return {"session": session}


# ---------------------------------------------------------------- interview

@app.get("/api/interview")
def interview_get():
    session = require_session()
    transcript = db.interview_transcript(session["id"])
    if not transcript:
        db.add_interview_message(session["id"], "consultant", consultant.OPENING, "workday")
        transcript = db.interview_transcript(session["id"])
    signals = consultant.transcript_signals(transcript)
    return {
        "transcript": transcript,
        "complete": consultant.interview_complete(signals),
        "asked": len([s for s in signals["asked"] if s]),
        "min_questions": consultant.MIN_QUESTIONS,
        "max_questions": consultant.MAX_QUESTIONS,
    }


@app.post("/api/interview")
def interview_answer(body: TextIn):
    session = require_session()
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty answer")

    transcript = db.interview_transcript(session["id"])
    last_slot = next((m["slot"] for m in reversed(transcript) if m["role"] == "consultant"), None)
    db.add_interview_message(session["id"], "employee", text, last_slot)

    done, ack, question, slot = consultant.compose_next_turn(session["id"])
    if ack:
        db.add_interview_message(session["id"], "consultant", ack, None)
    if question:
        db.add_interview_message(session["id"], "consultant", question, slot)

    profile = consultant.ensure_work_profile(db.get_session(session["id"]))
    if done:
        # The stage stays on "interview" until the participant presses Continue,
        # so a refresh at this moment shows the conclusion again rather than
        # skipping past it.
        db.mark_milestone(session["id"], "interview_completed")

    return {
        "transcript": db.interview_transcript(session["id"]),
        "complete": done, "acknowledgement": ack, "question": question,
        "profile": profile,
        "suggestions": consultant.interview_suggestions(session) if done else [],
    }


@app.get("/api/suggestions")
def suggestions_get():
    """Automation suggestions derived from the interview alone (REPORTED only)."""
    session = require_session()
    return {"suggestions": consultant.interview_suggestions(session)}


@app.post("/api/interview/finish")
def interview_finish():
    session = require_session()
    transcript = db.interview_transcript(session["id"])
    if not any(m["role"] == "employee" for m in transcript):
        raise HTTPException(400, "The interview needs at least one answer.")
    db.add_interview_message(
        session["id"], "consultant",
        "Thanks. I have enough context to start looking for opportunities.", None)
    profile = consultant.ensure_work_profile(session)
    db.mark_milestone(session["id"], "interview_completed")
    return {"complete": True, "profile": profile,
            "suggestions": consultant.interview_suggestions(session)}


# ------------------------------------------------------------- work profile

@app.get("/api/profile")
def profile_get():
    session = require_session()
    return {"profile": db.load_work_profile(session["id"]) or consultant.ensure_work_profile(session)}


@app.put("/api/profile")
def profile_put(body: ProfileIn):
    session = require_session()
    profile = db.load_work_profile(session["id"]) or consultant.ensure_work_profile(session)
    profile.update(body.model_dump())
    profile["edited"] = True
    profile["updated_at"] = db.now_iso()
    db.save_work_profile(session["id"], profile)
    return {"profile": profile}


# -------------------------------------------------------------- permissions

@app.get("/api/permissions")
def permissions_get():
    return {"permissions": db.list_permissions()}


@app.post("/api/permissions/{perm_id}")
def permissions_set(perm_id: int, body: PermissionToggle):
    db.set_permission(perm_id, body.allowed)
    return {"permissions": db.list_permissions()}


@app.post("/api/permissions")
def permissions_add(body: PermissionIn):
    domain = body.domain.strip().lower()
    domain = domain.replace("https://", "").replace("http://", "").split("/")[0].strip()
    if not domain or "." not in domain and domain != "localhost":
        raise HTTPException(400, "Enter a website domain, for example app.hubspot.com")
    created = db.add_permission(domain, body.app_label.strip() or domain,
                                body.product.strip() or "Custom", body.category)
    return {"permission": created, "permissions": db.list_permissions()}


@app.get("/api/extension/config")
def extension_config():
    """What the browser extension needs in order to classify a tab.

    It receives ONLY the approved domains. Anything not on this list is never
    looked at, never classified and never recorded."""
    session = db.active_session()
    return {
        "recording": recording_state(session),
        "paused": db.get_setting("monitoring_paused") == "1",
        "session_code": session["code"] if session else None,
        "permissions": [
            {"domain": p["domain"], "path_prefix": p["path_prefix"],
             "application": p["app_label"], "category": p["category"]}
            for p in db.allowed_permissions()
        ],
    }


# ------------------------------------------------------------------- ingest

@app.post("/api/events")
def ingest(batch: EventBatch):
    session = db.active_session()
    if not session:
        return {"accepted": 0, "recording": False, "reason": "no active session"}
    if not recording_state(session):
        return {"accepted": 0, "recording": False, "reason": "analysis not running"}

    allowed = allowed_app_labels()
    rows = []
    for e in batch.events:
        if e.application not in allowed:
            continue                       # never store an unapproved application
        rows.append({
            "type": e.type, "application": e.application,
            "category": e.category if e.category in ALLOWED_CATEGORIES else "Other",
            "started_at": e.started_at, "ended_at": e.ended_at, "duration_ms": e.duration_ms,
        })
    if rows:
        db.insert_events(session["id"], batch.run_id[:64], rows)

    live = live_patterns(session)
    return {
        "accepted": len(rows), "rejected": len(batch.events) - len(rows),
        "recording": True,
        "live": live,
        "bubble_ready": bool(live["patterns"]) and live["patterns"][0]["repetitions"] >= 3,
        "top": live["patterns"][0] if live["patterns"] else None,
    }


def live_patterns(session):
    """Cheap, no-AI view used during observation (live counters + in-page hint)."""
    events = db.session_events(session["id"])
    stats = detection.stream_stats(events)
    patterns = detection.detect(events)
    return {
        "events": stats["total_events"],
        "applications": stats["applications"],
        "time_analysed_ms": stats["time_analysed_ms"],
        "switches": stats["transitions"],
        "clipboard": stats["copy_events"] + stats["paste_events"],
        "patterns": [{
            "pattern_key": p["pattern_key"], "sequence": p["sequence"],
            "repetitions": p["repetitions"], "title": consultant.workflow_title(p),
        } for p in patterns],
    }


# ----------------------------------------------------------------- analysis

@app.post("/api/analysis/start")
def analysis_start():
    session = require_session()
    db.set_setting("monitoring_paused", "0")
    session = db.update_session(session["id"], analysis_started_at=db.now_iso(),
                                analysis_ended_at=None, stage="observe")
    db.mark_milestone(session["id"], "analysis_started")
    return {"session": session, "recording": True}


@app.get("/api/analysis/status")
def analysis_status():
    session = require_session()
    live = live_patterns(session)
    started = session.get("analysis_started_at")
    elapsed = 0
    if started:
        end = session.get("analysis_ended_at") or db.now_iso()
        elapsed = int((detection.parse_ts(end) - detection.parse_ts(started)).total_seconds())
    return {
        "recording": recording_state(session),
        "paused": db.get_setting("monitoring_paused") == "1",
        "elapsed_seconds": max(0, elapsed),
        "approved_apps": [p["app_label"] for p in db.allowed_permissions()],
        **live,
    }


@app.post("/api/analysis/finish")
def analysis_finish():
    session = require_session()
    session = db.update_session(session["id"], analysis_ended_at=db.now_iso())
    findings = consultant.build_findings(session)
    stats = session_stats(session)
    stage = "aha" if findings else "observe"
    db.update_session(session["id"], stage=stage)
    db.mark_milestone(session["id"], "analysis_completed")
    # "finding_viewed" is marked when the participant actually opens the finding
    # (stage -> finding), not here: producing a finding is not the same as reading one.
    return {
        "sufficient": bool(findings),
        "findings": [public_finding(f) for f in findings],
        "stats": stats,
        "message": None if findings else (
            "I don't have enough activity yet to confidently identify a repeated workflow."),
    }


@app.post("/api/analysis/continue")
def analysis_continue():
    session = require_session()
    session = db.update_session(session["id"], analysis_ended_at=None, stage="observe")
    return {"session": session, "recording": recording_state(session)}


# ----------------------------------------------------------------- findings

@app.get("/api/findings")
def findings_list():
    session = require_session()
    return {"findings": [public_finding(f) for f in db.load_findings(session["id"])]}


@app.get("/api/findings/{finding_id}")
def finding_detail(finding_id: str):
    session = require_session()
    for f in db.load_findings(session["id"]):
        if str(f["id"]) == finding_id or f["pattern_key"] == finding_id:
            data = public_finding(f, full=True)
            data["algorithm"] = {
                "min_visit_ms": detection.MIN_VISIT_MS,
                "run_gap_minutes": detection.RUN_GAP_MINUTES,
                "sequence_length_range": [detection.MIN_SEQ_LEN, detection.MAX_SEQ_LEN],
                "min_repetitions": detection.MIN_REPETITIONS,
                "high_threshold": consultant.HIGH_THRESHOLD,
                "medium_threshold": consultant.MEDIUM_THRESHOLD,
            }
            return data
    raise HTTPException(404, "Finding not found")


@app.get("/api/summary")
def summary():
    session = db.active_session()
    if not session:
        return {"session": None, "stats": None, "findings": []}
    stats = session_stats(session)
    findings = db.load_findings(session["id"])
    return {
        "session": session,
        "recording": recording_state(session),
        "monitoring_paused": db.get_setting("monitoring_paused") == "1",
        "stats": stats,
        "profile": db.load_work_profile(session["id"]),
        "findings": [public_finding(f) for f in findings],
        "open_questions": [
            {"finding_id": f["id"], "title": f["title"], "question": f["open_question"]}
            for f in findings if f["open_question"]
        ],
    }


# ---------------------------------------------------------------- consultant

@app.get("/api/consultant")
def consultant_get():
    session = require_session()
    findings = db.load_findings(session["id"])
    return {
        "thread": db.consultant_thread(session["id"]),
        "suggested": consultant.SUGGESTED_QUESTIONS,
        "open_questions": [f["open_question"] for f in findings if f["open_question"]],
    }


@app.post("/api/consultant")
def consultant_post(body: TextIn):
    session = require_session()
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty message")

    db.add_consultant_message(session["id"], "employee", text)
    # What the employee says here is evidence too: re-run the analysis so that
    # answering the consultant's question genuinely changes the finding.
    before = {f["pattern_key"]: (f["score"], f["confidence"]) for f in db.load_findings(session["id"])}
    if db.session_events(session["id"]):
        consultant.build_findings(session)
    after = db.load_findings(session["id"])

    reply, source = consultant.answer(session, text)
    db.add_consultant_message(session["id"], "consultant", reply)

    changed = [
        {"title": f["title"], "score": f["score"], "confidence": f["confidence"],
         "previous_score": before[f["pattern_key"]][0],
         "previous_confidence": before[f["pattern_key"]][1]}
        for f in after
        if f["pattern_key"] in before
        and before[f["pattern_key"]] != (f["score"], f["confidence"])
    ]
    return {
        "thread": db.consultant_thread(session["id"]),
        "reply": reply, "source": source, "updated_findings": changed,
        "findings": [public_finding(f) for f in after],
    }


# -------------------------------------------------------------------- report

@app.get("/api/report")
def report():
    session = require_session()
    return consultant.build_report(session)


# ------------------------------------------------------------------ feedback

@app.post("/api/feedback")
def feedback_post(body: FeedbackIn):
    session = require_session()
    findings = db.load_findings(session["id"])
    payload = body.model_dump()
    payload["finding_title"] = findings[0]["title"] if findings else None
    payload["finding_confidence"] = findings[0]["confidence"] if findings else None
    db.save_feedback(session["id"], payload)
    db.update_session(session["id"], stage="done", completed_at=db.now_iso())
    db.mark_milestone(session["id"], "feedback_completed")
    return {"saved": True}


@app.post("/api/pilot/assistance")
def pilot_assistance(body: AssistanceIn):
    """Marked by the facilitator on /pilot-results, never by the participant."""
    db.set_assistance(body.session_id, body.level)
    return {"saved": True}


@app.post("/api/pilot/notes")
def pilot_note_add(body: NoteIn):
    db.add_note(body.problem.strip(), body.change_made.strip(),
                (body.reason or "").strip() or None)
    return {"notes": db.list_notes()}


@app.delete("/api/pilot/notes/{note_id}")
def pilot_note_delete(note_id: int):
    db.delete_note(note_id)
    return {"notes": db.list_notes()}


@app.post("/api/pilot/error")
def pilot_error(body: ErrorIn):
    """Technical faults during a session, so we can see whether a participant hit
    a failure rather than simply losing interest. No work content is accepted."""
    session = db.active_session()
    db.log_error(session["id"] if session else None, body.route, body.kind, body.detail)
    return {"logged": True}


@app.get("/api/pilot-results")
def pilot_results(session_type: str = "REAL_PILOT"):
    if session_type not in ("REAL_PILOT", "DEMO"):
        raise HTTPException(400, "Unknown session type")
    return consultant.pilot_results(session_type)


@app.get("/api/pilot-results.csv")
def pilot_results_csv(session_type: str = "REAL_PILOT"):
    if session_type not in ("REAL_PILOT", "DEMO"):
        raise HTTPException(400, "Unknown session type")
    csv_text = consultant.pilot_csv(session_type)
    return PlainTextResponse(csv_text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="flowmind-pilot-{session_type.lower()}.csv"'})


# ------------------------------------------------------------------- privacy

@app.get("/api/monitoring")
def monitoring_get():
    return {"paused": db.get_setting("monitoring_paused") == "1"}


@app.post("/api/monitoring")
def monitoring_set(body: MonitoringIn):
    db.set_setting("monitoring_paused", "1" if body.paused else "0")
    return {"paused": body.paused}


@app.post("/api/privacy/delete-activity")
def delete_activity():
    session = require_session()
    db.clear_session_events(session["id"])
    return {"deleted": "activity"}


@app.post("/api/privacy/delete-memory")
def delete_memory():
    session = require_session()
    db.clear_consultant_memory(session["id"])
    db.update_session(session["id"], stage="context")
    return {"deleted": "consultant memory"}


@app.post("/api/reset")
def reset_demo():
    """Clears the current session's activity and restores the demo requests."""
    session = db.active_session()
    if session:
        db.clear_session_events(session["id"])
        db.update_session(session["id"], analysis_started_at=None, analysis_ended_at=None)
    db.seed_demo_orders(reset=True)
    db.set_setting("monitoring_paused", "0")
    return {"reset": True}


# ------------------------------------------------------- demo workday events

DEMO_SEQUENCE = [
    ("FlowMail", "Email", 70, 110),
    ("FlowSheet", "Spreadsheet", 95, 140),
    ("FlowCRM", "CRM", 80, 120),
]


@app.post("/api/demo/generate")
def generate_demo_workday(repetitions: int = 8):
    """Fallback for the live demo. Generates realistic raw ACTIVITY EVENTS and
    pushes them through the same aggregation, detection, scoring and analysis as
    the extension. It never injects a finding. Durations come from a fixed seed,
    so the result is reproducible rather than random."""
    session = require_session()
    repetitions = max(2, min(repetitions, 12))
    rng = random.Random(20260916)

    per_rep = sum((a + b) / 2 for _, _, a, b in DEMO_SEQUENCE) + 6
    earliest = db.get_conn().execute(
        "SELECT MIN(started_at) m FROM events WHERE session_id=?", (session["id"],)).fetchone()["m"]
    end_at = (detection.parse_ts(earliest) - timedelta(minutes=20)) if earliest else \
        (datetime.now(timezone.utc) - timedelta(seconds=60))
    cursor = end_at - timedelta(seconds=per_rep * repetitions + 30)

    rows = []
    for _ in range(repetitions):
        for app_name, category, lo, hi in DEMO_SEQUENCE:
            seconds = rng.randint(lo, hi)
            start, end = cursor, cursor + timedelta(seconds=seconds)
            rows.append({"type": "app_visit", "application": app_name, "category": category,
                         "started_at": _iso(start), "ended_at": _iso(end),
                         "duration_ms": seconds * 1000})
            marks = {"FlowMail": ["copy"], "FlowSheet": ["paste", "copy"],
                     "FlowCRM": ["paste"]}[app_name]
            for i, mark in enumerate(marks):
                at = start + timedelta(seconds=min(seconds - 2, 4 + i * 5))
                rows.append({"type": mark, "application": app_name, "category": category,
                             "started_at": _iso(at), "ended_at": None, "duration_ms": 0})
            cursor = end + timedelta(seconds=2)

    db.insert_events(session["id"], "demo-workday", rows, source="simulated")
    if not session.get("analysis_started_at"):
        db.update_session(session["id"], analysis_started_at=_iso(end_at - timedelta(
            seconds=per_rep * repetitions + 30)))
    session = db.get_session(session["id"])
    findings = consultant.build_findings(session)
    db.update_session(session["id"], analysis_ended_at=db.now_iso(),
                      stage="aha" if findings else "observe")
    return {"inserted": len(rows), "repetitions": repetitions,
            "findings": [public_finding(f) for f in findings]}


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------- activity API

@app.get("/api/activity")
def activity(limit: int = 400):
    session = db.active_session()
    if not session:
        return {"events": [], "count": 0, "by_application": [], "by_category": []}
    rows = db.get_conn().execute(
        "SELECT * FROM events WHERE session_id=? ORDER BY started_at DESC, id DESC LIMIT ?",
        (session["id"], limit)).fetchall()
    events = [{"id": r["id"], "type": r["type"], "application": r["application"],
               "category": r["category"], "started_at": r["started_at"],
               "ended_at": r["ended_at"], "duration_ms": r["duration_ms"],
               "source": r["source"]} for r in rows][::-1]
    stats = session_stats(session)
    return {"events": events, "count": len(events),
            "by_application": stats["by_application"], "by_category": stats["by_category"],
            "time_analysed_ms": stats["time_analysed_ms"], "switches": stats["transitions"]}


# ------------------------------------------------------------------ demo apps

@app.get("/api/demo/orders")
def demo_orders():
    rows = db.get_conn().execute("SELECT * FROM demo_orders ORDER BY position").fetchall()
    orders = [dict(r) for r in rows]
    return {"orders": orders, "completed": sum(1 for o in orders if o["mail_done"]),
            "total": len(orders)}


@app.post("/api/demo/orders/{order_id}")
def demo_update(order_id: str, body: DemoUpdate):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM demo_orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown order")
    with db._write_lock:
        conn.execute(f"UPDATE demo_orders SET {body.step}_done=1 WHERE id=?", (order_id,))
        conn.commit()
    return dict(conn.execute("SELECT * FROM demo_orders WHERE id=?", (order_id,)).fetchone())


# ---------------------------------------------------------------- static pages

def page(name):
    return FileResponse(os.path.join(WEB, name))


@app.get("/")
def app_root():
    return page("dashboard/index.html")


@app.get("/pilot")
def pilot_entry():
    return page("dashboard/index.html")


@app.get("/pilot-results")
def pilot_results_page():
    return page("dashboard/pilot-results.html")


@app.get("/demo")
def demo_home():
    return page("demo/index.html")


@app.get("/demo/mail")
def demo_mail():
    return page("demo/mail.html")


@app.get("/demo/sheet")
def demo_sheet():
    return page("demo/sheet.html")


@app.get("/demo/crm")
def demo_crm():
    return page("demo/crm.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.exception_handler(404)
def not_found(request, exc):
    return JSONResponse({"error": "Not found"}, status_code=404)
