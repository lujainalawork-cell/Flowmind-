"""SQLite storage for FlowMind — AI Business Consultant MVP.

Everything a participant produces (interview, approved apps, activity, findings,
feedback) is tied to one anonymous pilot session. No name, email, company name
or other identifying field exists anywhere in this schema.

The activity tables have no column that can hold page text, typed characters,
clipboard contents, form values or URLs. What the participant tells the
consultant IS stored — that is the point of an interview — and it can be deleted
from the Privacy page at any time.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "FLOWMIND_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "flowmind.db"),
)

_local = threading.local()
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS pilot_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT UNIQUE NOT NULL,
    session_type        TEXT NOT NULL,            -- REAL_PILOT | DEMO
    stage               TEXT NOT NULL,            -- welcome|consent|context|interview|permissions|observe|finding|feedback|done
    industry            TEXT,
    role                TEXT,
    company_size        TEXT,
    consent_at          TEXT,
    analysis_started_at TEXT,
    analysis_ended_at   TEXT,
    completed_at        TEXT,
    permissions_json    TEXT,
    active              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    -- funnel milestones: first write wins, never overwritten
    pilot_started          TEXT,
    context_completed      TEXT,
    interview_completed    TEXT,
    permissions_completed  TEXT,
    analysis_started       TEXT,
    analysis_completed     TEXT,
    finding_viewed         TEXT,
    feedback_started       TEXT,
    feedback_completed     TEXT,
    -- marked by the facilitator afterwards, never by the participant
    assistance_level       TEXT
);

CREATE TABLE IF NOT EXISTS app_permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL,
    path_prefix TEXT NOT NULL DEFAULT '',
    app_label   TEXT NOT NULL,
    product     TEXT NOT NULL,
    category    TEXT NOT NULL,
    allowed     INTEGER NOT NULL DEFAULT 1,
    builtin     INTEGER NOT NULL DEFAULT 1,
    UNIQUE(domain, path_prefix)
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER,
    run_id        TEXT NOT NULL,
    type          TEXT NOT NULL,       -- app_visit | copy | paste
    application   TEXT NOT NULL,       -- approved application label only
    category      TEXT NOT NULL,       -- Email | Spreadsheet | CRM | Support | Project | Messaging | Other
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'extension',   -- extension | simulated
    received_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, started_at);

CREATE TABLE IF NOT EXISTS interview_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    role        TEXT NOT NULL,          -- consultant | employee
    text        TEXT NOT NULL,
    slot        TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consultant_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    role        TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_profiles (
    session_id  INTEGER PRIMARY KEY,
    data_json   TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    pattern_key         TEXT NOT NULL,
    title               TEXT NOT NULL,
    sequence_json       TEXT NOT NULL,
    cyclic              INTEGER NOT NULL DEFAULT 0,
    repetitions         INTEGER NOT NULL,
    app_count           INTEGER NOT NULL,
    total_time_ms       INTEGER NOT NULL,
    avg_duration_ms     INTEGER NOT NULL,
    copy_events         INTEGER NOT NULL,
    paste_events        INTEGER NOT NULL,
    transitions         INTEGER NOT NULL,
    score               INTEGER NOT NULL,
    band                TEXT NOT NULL,
    confidence          TEXT NOT NULL,
    confidence_reason   TEXT NOT NULL,
    open_question       TEXT,
    components_json     TEXT NOT NULL,
    occurrences_json    TEXT NOT NULL,
    observed_json       TEXT NOT NULL,
    reported_json       TEXT NOT NULL,
    narrative_json      TEXT NOT NULL,
    analysis_source     TEXT NOT NULL,
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(session_id, pattern_key)
);

CREATE TABLE IF NOT EXISTS pilot_feedback (
    session_id           INTEGER PRIMARY KEY,
    finding_title        TEXT,
    finding_confidence   TEXT,
    understanding_rating TEXT,
    repetition_rating    TEXT,
    usefulness_rating    TEXT,
    continued_use_rating TEXT,
    permission_comfort   TEXT,
    missed_or_wrong      TEXT,
    wished_task          TEXT,
    permission_reason    TEXT,
    product_understanding_text TEXT,
    investigate_rating   TEXT,
    investigate_reason   TEXT,
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    problem     TEXT NOT NULL,
    change_made TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    route       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    detail      TEXT,
    source      TEXT NOT NULL DEFAULT 'browser',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS demo_orders (
    id             TEXT PRIMARY KEY,
    position       INTEGER NOT NULL,
    customer       TEXT NOT NULL,
    request        TEXT NOT NULL,
    request_detail TEXT NOT NULL,
    old_value      TEXT NOT NULL,
    new_value      TEXT NOT NULL,
    item           TEXT NOT NULL,
    sheet_done     INTEGER NOT NULL DEFAULT 0,
    crm_done       INTEGER NOT NULL DEFAULT 0,
    mail_done      INTEGER NOT NULL DEFAULT 0
);
"""

# domain, path_prefix, app_label, product, category, allowed by default
DEFAULT_PERMISSIONS = [
    ("localhost", "/demo/mail", "FlowMail", "FlowMind Demo Environment", "Email", 1),
    ("localhost", "/demo/sheet", "FlowSheet", "FlowMind Demo Environment", "Spreadsheet", 1),
    ("localhost", "/demo/crm", "FlowCRM", "FlowMind Demo Environment", "CRM", 1),
    ("mail.google.com", "", "Gmail", "Google Workspace", "Email", 1),
    ("docs.google.com", "/spreadsheets", "Google Sheets", "Google Workspace", "Spreadsheet", 1),
    ("outlook.office.com", "", "Outlook", "Microsoft 365", "Email", 1),
    ("app.hubspot.com", "", "HubSpot", "HubSpot", "CRM", 1),
    ("salesforce.com", "", "Salesforce", "Salesforce", "CRM", 1),
    # Customer service desks: for most small businesses this is where the
    # repetitive work actually lives, so they are approved by default.
    ("zendesk.com", "", "Zendesk", "Zendesk Support", "Support", 1),
    ("freshdesk.com", "", "Freshdesk", "Freshdesk", "Support", 1),
    ("app.intercom.com", "", "Intercom", "Intercom", "Support", 1),
    ("secure.helpscout.net", "", "Help Scout", "Help Scout", "Support", 1),
    # Messaging blurs work and personal, so it stays off until chosen.
    ("web.whatsapp.com", "", "WhatsApp Business", "WhatsApp", "Support", 0),
    ("trello.com", "", "Trello", "Trello", "Project", 0),
    ("app.asana.com", "", "Asana", "Asana", "Project", 0),
    ("app.slack.com", "", "Slack", "Slack", "Messaging", 0),
]

DEMO_ORDERS = [
    ("ORD-2841", 1, "Sarah Ahmed", "Update delivery address",
     "Please change my delivery address before the order ships.",
     "12 Palm Street, Jeddah", "44 Rawdah Avenue, Jeddah", "Ceramic Filter Set"),
    ("ORD-2842", 2, "Omar Nasser", "Update delivery address",
     "I have moved, can you update the address on my order?",
     "8 Harbour Road, Dammam", "21 Olaya Street, Riyadh", "Desk Lamp (Warm)"),
    ("ORD-2843", 3, "Layla Rahman", "Update delivery address",
     "Wrong address on the confirmation email, please correct it.",
     "5 Corniche Walk, Jeddah", "77 Al Andalus Road, Jeddah", "Travel Backpack 30L"),
    ("ORD-2844", 4, "Yousef Bakr", "Update delivery address",
     "Kindly send this to my office instead of my home.", "3 Garden Lane, Makkah",
     "19 King Fahd Branch Rd, Jeddah", "Wireless Keyboard"),
    ("ORD-2845", 5, "Hana Siddiqui", "Update delivery address",
     "Could you update the shipping address for this order?",
     "60 Rose Court, Taif", "12 Al Hamra Street, Jeddah", "Espresso Cups (x6)"),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=8000")
        _local.conn = conn
    return conn


MILESTONES = ["pilot_started", "context_completed", "interview_completed",
              "permissions_completed", "analysis_started", "analysis_completed",
              "finding_viewed", "feedback_started", "feedback_completed"]


def _ensure_columns(conn, table, columns):
    """Add columns an older database is missing, so upgrading never costs us
    pilot results already collected from real participants."""
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns:
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _ensure_columns(conn, "pilot_sessions",
                    [(m, "TEXT") for m in MILESTONES] + [("assistance_level", "TEXT")])
    _ensure_columns(conn, "pilot_feedback", [
        ("product_understanding_text", "TEXT"),
        ("investigate_rating", "TEXT"),
        ("investigate_reason", "TEXT"),
    ])
    conn.commit()
    seed_permissions()
    seed_demo_orders(reset=False)
    if get_setting("monitoring_paused") is None:
        set_setting("monitoring_paused", "0")


# ------------------------------------------------------------------- settings

def get_setting(key, default=None):
    row = get_conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()


# ---------------------------------------------------------------- permissions

def seed_permissions(reset=False):
    conn = get_conn()
    with _write_lock:
        if reset:
            conn.execute("DELETE FROM app_permissions")
        for domain, path, label, product, category, allowed in DEFAULT_PERMISSIONS:
            conn.execute(
                "INSERT INTO app_permissions (domain, path_prefix, app_label, product,"
                " category, allowed, builtin) VALUES (?,?,?,?,?,?,1)"
                " ON CONFLICT(domain, path_prefix) DO NOTHING",
                (domain, path, label, product, category, allowed),
            )
        conn.commit()


def list_permissions():
    rows = get_conn().execute(
        "SELECT * FROM app_permissions ORDER BY allowed DESC, product, app_label"
    ).fetchall()
    return [dict(r) for r in rows]


def allowed_permissions():
    return [p for p in list_permissions() if p["allowed"]]


def set_permission(perm_id, allowed):
    conn = get_conn()
    with _write_lock:
        conn.execute("UPDATE app_permissions SET allowed=? WHERE id=?", (1 if allowed else 0, perm_id))
        conn.commit()


def add_permission(domain, app_label, product, category):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO app_permissions (domain, path_prefix, app_label, product, category,"
            " allowed, builtin) VALUES (?,'',?,?,?,1,0)"
            " ON CONFLICT(domain, path_prefix) DO UPDATE SET allowed=1",
            (domain, app_label, product, category),
        )
        conn.commit()
    row = get_conn().execute(
        "SELECT * FROM app_permissions WHERE domain=? AND path_prefix=''", (domain,)
    ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------- sessions

def next_pilot_code():
    row = get_conn().execute("SELECT COUNT(*) c FROM pilot_sessions").fetchone()
    return f"FM-PILOT-{row['c'] + 1:04d}"


def create_session(session_type="REAL_PILOT"):
    conn = get_conn()
    with _write_lock:
        conn.execute("UPDATE pilot_sessions SET active=0")
        code = next_pilot_code()
        cur = conn.execute(
            "INSERT INTO pilot_sessions (code, session_type, stage, active, created_at)"
            " VALUES (?,?,?,1,?)",
            (code, session_type, "consent", now_iso()),
        )
        conn.commit()
    return get_session(cur.lastrowid)


def get_session(session_id):
    row = get_conn().execute("SELECT * FROM pilot_sessions WHERE id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def active_session():
    row = get_conn().execute(
        "SELECT * FROM pilot_sessions WHERE active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def update_session(session_id, **fields):
    if not fields:
        return get_session(session_id)
    cols = ", ".join(f"{k}=?" for k in fields)
    conn = get_conn()
    with _write_lock:
        conn.execute(f"UPDATE pilot_sessions SET {cols} WHERE id=?",
                     (*fields.values(), session_id))
        conn.commit()
    return get_session(session_id)


def delete_session(session_id):
    """Remove a session and everything attached to it.

    Used when a participant backs out before giving any answers, so an abandoned
    click on "Start my work analysis" never becomes a phantom participant in the
    validation statistics.
    """
    conn = get_conn()
    with _write_lock:
        for table in ("events", "interview_messages", "consultant_messages",
                      "work_profiles", "findings", "pilot_feedback"):
            conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM pilot_sessions WHERE id=?", (session_id,))
        conn.commit()


def mark_milestone(session_id, field):
    """Record a funnel milestone once. Re-running a step never rewrites history."""
    if field not in MILESTONES:
        return
    conn = get_conn()
    with _write_lock:
        conn.execute(
            f"UPDATE pilot_sessions SET {field}=? WHERE id=? AND {field} IS NULL",
            (now_iso(), session_id))
        conn.commit()


def set_assistance(session_id, level):
    conn = get_conn()
    with _write_lock:
        conn.execute("UPDATE pilot_sessions SET assistance_level=? WHERE id=?",
                     (level, session_id))
        conn.commit()


def add_note(problem, change_made, reason):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO pilot_notes (problem, change_made, reason, created_at)"
            " VALUES (?,?,?,?)", (problem, change_made, reason, now_iso()))
        conn.commit()


def list_notes():
    return [dict(r) for r in get_conn().execute(
        "SELECT * FROM pilot_notes ORDER BY id DESC").fetchall()]


def delete_note(note_id):
    conn = get_conn()
    with _write_lock:
        conn.execute("DELETE FROM pilot_notes WHERE id=?", (note_id,))
        conn.commit()


def log_error(session_id, route, kind, detail, source="browser"):
    """Technical faults only. Never page content — detail comes from FlowMind's
    own code and is truncated before it gets here."""
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO pilot_errors (session_id, route, kind, detail, source, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (session_id, route[:120], kind[:60], (detail or "")[:300], source, now_iso()))
        conn.commit()


def list_errors(limit=100):
    rows = get_conn().execute(
        """SELECT e.*, s.code, s.session_type FROM pilot_errors e
           LEFT JOIN pilot_sessions s ON s.id = e.session_id
           ORDER BY e.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_sessions(session_type=None):
    sql = "SELECT * FROM pilot_sessions"
    args = ()
    if session_type:
        sql += " WHERE session_type=?"
        args = (session_type,)
    sql += " ORDER BY id DESC"
    return [dict(r) for r in get_conn().execute(sql, args).fetchall()]


# --------------------------------------------------------------------- events

def insert_events(session_id, run_id, rows, source="extension"):
    conn = get_conn()
    received = now_iso()
    with _write_lock:
        for e in rows:
            conn.execute(
                "INSERT INTO events (session_id, run_id, type, application, category,"
                " started_at, ended_at, duration_ms, source, received_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (session_id, run_id, e["type"], e["application"], e["category"],
                 e["started_at"], e.get("ended_at"), e.get("duration_ms", 0), source, received),
            )
        conn.commit()
    return len(rows)


def session_events(session_id):
    rows = get_conn().execute(
        "SELECT * FROM events WHERE session_id=? ORDER BY started_at ASC, id ASC", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_session_events(session_id):
    conn = get_conn()
    with _write_lock:
        conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM findings WHERE session_id=?", (session_id,))
        conn.commit()


# ------------------------------------------------------------------ interview

def add_interview_message(session_id, role, text, slot=None):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO interview_messages (session_id, role, text, slot, created_at)"
            " VALUES (?,?,?,?,?)", (session_id, role, text, slot, now_iso()))
        conn.commit()


def interview_transcript(session_id):
    rows = get_conn().execute(
        "SELECT * FROM interview_messages WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_consultant_message(session_id, role, text):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO consultant_messages (session_id, role, text, created_at)"
            " VALUES (?,?,?,?)", (session_id, role, text, now_iso()))
        conn.commit()


def consultant_thread(session_id):
    rows = get_conn().execute(
        "SELECT * FROM consultant_messages WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_consultant_memory(session_id):
    conn = get_conn()
    with _write_lock:
        conn.execute("DELETE FROM interview_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM consultant_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM work_profiles WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM findings WHERE session_id=?", (session_id,))
        conn.commit()


# --------------------------------------------------------------- work profile

def save_work_profile(session_id, profile):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO work_profiles (session_id, data_json, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET data_json=excluded.data_json,"
            " updated_at=excluded.updated_at",
            (session_id, json.dumps(profile), now_iso()))
        conn.commit()


def load_work_profile(session_id):
    row = get_conn().execute(
        "SELECT * FROM work_profiles WHERE session_id=?", (session_id,)).fetchone()
    return json.loads(row["data_json"]) if row else None


# ------------------------------------------------------------------- findings

FINDING_JSON_FIELDS = ["sequence", "components", "occurrences", "observed", "reported", "narrative"]


def save_findings(session_id, findings):
    conn = get_conn()
    with _write_lock:
        conn.execute("DELETE FROM findings WHERE session_id=?", (session_id,))
        for f in findings:
            conn.execute(
                """INSERT INTO findings (session_id, pattern_key, title, sequence_json, cyclic,
                   repetitions, app_count, total_time_ms, avg_duration_ms, copy_events,
                   paste_events, transitions, score, band, confidence, confidence_reason,
                   open_question, components_json, occurrences_json, observed_json,
                   reported_json, narrative_json, analysis_source, first_seen, last_seen, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, f["pattern_key"], f["title"], json.dumps(f["sequence"]),
                 int(f["cyclic"]), f["repetitions"], f["app_count"], f["total_time_ms"],
                 f["avg_duration_ms"], f["copy_events"], f["paste_events"], f["transitions"],
                 f["score"], f["band"], f["confidence"], f["confidence_reason"],
                 f.get("open_question"), json.dumps(f["components"]), json.dumps(f["occurrences"]),
                 json.dumps(f["observed"]), json.dumps(f["reported"]), json.dumps(f["narrative"]),
                 f["analysis_source"], f["first_seen"], f["last_seen"], now_iso()))
        conn.commit()


def load_findings(session_id):
    rows = get_conn().execute(
        "SELECT * FROM findings WHERE session_id=? ORDER BY score DESC, repetitions DESC",
        (session_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for field in FINDING_JSON_FIELDS:
            d[field] = json.loads(d.pop(f"{field}_json"))
        d["cyclic"] = bool(d["cyclic"])
        out.append(d)
    return out


# ------------------------------------------------------------------- feedback

def save_feedback(session_id, data):
    conn = get_conn()
    with _write_lock:
        conn.execute(
            """INSERT INTO pilot_feedback (session_id, finding_title, finding_confidence,
               understanding_rating, repetition_rating, usefulness_rating, continued_use_rating,
               permission_comfort, missed_or_wrong, wished_task, permission_reason,
               product_understanding_text, investigate_rating, investigate_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                 finding_title=excluded.finding_title,
                 finding_confidence=excluded.finding_confidence,
                 understanding_rating=excluded.understanding_rating,
                 repetition_rating=excluded.repetition_rating,
                 usefulness_rating=excluded.usefulness_rating,
                 continued_use_rating=excluded.continued_use_rating,
                 permission_comfort=excluded.permission_comfort,
                 missed_or_wrong=excluded.missed_or_wrong,
                 wished_task=excluded.wished_task,
                 permission_reason=excluded.permission_reason,
                 product_understanding_text=excluded.product_understanding_text,
                 investigate_rating=excluded.investigate_rating,
                 investigate_reason=excluded.investigate_reason""",
            (session_id, data.get("finding_title"), data.get("finding_confidence"),
             data.get("understanding_rating"), data.get("repetition_rating"),
             data.get("usefulness_rating"), data.get("continued_use_rating"),
             data.get("permission_comfort"), data.get("missed_or_wrong"),
             data.get("wished_task"), data.get("permission_reason"),
             data.get("product_understanding_text"), data.get("investigate_rating"),
             data.get("investigate_reason"), now_iso()))
        conn.commit()


def all_feedback(session_type="REAL_PILOT"):
    rows = get_conn().execute(
        """SELECT f.*, s.code, s.session_type, s.industry, s.role, s.company_size,
                  s.assistance_level, s.pilot_started, s.feedback_completed
           FROM pilot_feedback f JOIN pilot_sessions s ON s.id = f.session_id
           WHERE (? IS NULL OR s.session_type = ?)
           ORDER BY f.created_at DESC""",
        (session_type, session_type)).fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------------- demo apps

def seed_demo_orders(reset=True):
    conn = get_conn()
    with _write_lock:
        if reset:
            conn.execute("DELETE FROM demo_orders")
        existing = conn.execute("SELECT COUNT(*) c FROM demo_orders").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT INTO demo_orders (id, position, customer, request, request_detail,"
                " old_value, new_value, item) VALUES (?,?,?,?,?,?,?,?)", DEMO_ORDERS)
        else:
            conn.execute("UPDATE demo_orders SET sheet_done=0, crm_done=0, mail_done=0")
        conn.commit()
