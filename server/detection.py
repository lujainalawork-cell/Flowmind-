"""Deterministic repeated-workflow detection for FlowMind Prototype 1.

There is no machine learning here and no randomness anywhere. Given the same
event stream the output is always identical. Every number shown in the FlowMind
dashboard is produced by the functions below and can be traced back to the raw
events on the Activity page.

Pipeline
--------
1. NORMALISE   drop transient visits, merge consecutive visits to the same app
2. SEGMENT     split the stream into runs wherever the user was idle > 15 min
3. FIND CYCLES look for repeating app sequences of length 3..5 in each run
4. MEASURE     repetitions, time, transitions, copy/paste counts per pattern
5. SCORE       five weighted components -> 0..100 opportunity score
"""

from datetime import datetime, timedelta

MIN_VISIT_MS = 1500          # ignore visits shorter than this (tab flicker)
MIN_OTHER_VISIT_MS = 8000    # a brief detour to an unrelated site is not a workflow step
RUN_GAP_MINUTES = 15         # a gap this long starts a new working run
MIN_SEQ_LEN = 3
MAX_SEQ_LEN = 5
MIN_REPETITIONS = 2          # a pattern is "detected" from 2 repetitions
BUBBLE_REPETITIONS = 3       # the in-page indicator only appears from 3

WORKFLOW_NAMES = {
    ("CRM", "Email", "Spreadsheet"): "Customer Data Transfer",
    ("CRM", "Email"): "Inbox to CRM Update",
    ("Email", "Spreadsheet"): "Inbox to Spreadsheet Entry",
    ("CRM", "Spreadsheet"): "Spreadsheet to CRM Update",
    ("CRM", "Project", "Email"): "Request to Task Handover",
    ("Email", "Project"): "Inbox to Task Handover",
    ("Project", "Spreadsheet"): "Spreadsheet to Task Handover",
}


def parse_ts(value):
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ms(a, b):
    return int((b - a).total_seconds() * 1000)


# ---------------------------------------------------------------- 1. normalise

def normalise(visits):
    """Drop transient visits, then merge consecutive visits to the same app."""
    kept = []
    for v in visits:
        limit = MIN_OTHER_VISIT_MS if v["category"] == "Other" else MIN_VISIT_MS
        if v["duration_ms"] >= limit:
            kept.append(dict(v))

    merged = []
    for v in kept:
        if merged and merged[-1]["application"] == v["application"]:
            prev = merged[-1]
            prev["ended_at"] = v["ended_at"]
            prev["duration_ms"] += v["duration_ms"]
            prev["merged_visits"] += 1
            prev["event_ids"].append(v["id"])
        else:
            v["merged_visits"] = 1
            v["event_ids"] = [v["id"]]
            merged.append(v)
    return merged


# ----------------------------------------------------------------- 2. segment

def segment(visits):
    """Split into runs of continuous work (gap > RUN_GAP_MINUTES starts a run)."""
    runs, current = [], []
    for v in visits:
        if current:
            gap = parse_ts(v["started_at"]) - parse_ts(current[-1]["ended_at"])
            if gap > timedelta(minutes=RUN_GAP_MINUTES):
                runs.append(current)
                current = []
        current.append(v)
    if current:
        runs.append(current)
    return runs


# -------------------------------------------------------------- 3. find cycles

def _occurrences(seq, candidate):
    """Non-overlapping left-to-right matches of candidate inside seq."""
    out, i, L = [], 0, len(candidate)
    while i <= len(seq) - L:
        if seq[i:i + L] == candidate:
            out.append(i)
            i += L
        else:
            i += 1
    return out


def _canonical(candidate):
    """Rotation-independent identity, so A>B>C and B>C>A are one workflow."""
    rotations = [tuple(candidate[i:] + candidate[:i]) for i in range(len(candidate))]
    return " > ".join(min(rotations))


def find_candidates(run):
    seq = [v["application"] for v in run]
    found = {}
    for L in range(MIN_SEQ_LEN, MAX_SEQ_LEN + 1):
        for i in range(0, len(seq) - L + 1):
            cand = seq[i:i + L]
            if len(set(cand)) < 2:
                continue
            if any(cand[j] == cand[j + 1] for j in range(L - 1)):
                continue
            occ = _occurrences(seq, cand)
            if len(occ) < MIN_REPETITIONS:
                continue
            key = _canonical(cand)
            coverage = len(occ) * L
            best = found.get(key)
            if best is None or (coverage, len(occ)) > (best["coverage"], len(best["occ"])):
                found[key] = {"key": key, "sequence": cand, "occ": occ,
                              "length": L, "coverage": coverage}
    return sorted(found.values(), key=lambda c: (-c["coverage"], -len(c["occ"])))


def select_patterns(run):
    """Greedy selection: best candidate first, then anything that does not
    substantially re-describe the visits an accepted pattern already covers."""
    accepted, claimed = [], set()
    for cand in find_candidates(run):
        idx = set()
        for start in cand["occ"]:
            idx.update(range(start, start + cand["length"]))
        overlap = len(idx & claimed) / len(idx)
        if overlap > 0.5:
            continue
        accepted.append(cand)
        claimed |= idx
        if len(accepted) >= 3:
            break
    return accepted


# ------------------------------------------------------------------ 4. measure

def measure(cand, run, marks):
    """Turn a candidate into a fully measured pattern occurrence set."""
    L = cand["length"]
    occurrences, total_ms, transitions = [], 0, 0
    copies = pastes = 0
    starts = sorted(cand["occ"])

    for n, start in enumerate(starts, 1):
        steps = run[start:start + L]
        occ_ms = sum(s["duration_ms"] for s in steps)
        total_ms += occ_ms
        transitions += L - 1
        if n > 1 and (starts[n - 2] + L) == start:
            transitions += 1  # the switch that led straight into this repetition

        t0 = parse_ts(steps[0]["started_at"])
        t1 = parse_ts(steps[-1]["ended_at"])
        occ_copies = sum(1 for m in marks if m["type"] == "copy" and t0 <= parse_ts(m["started_at"]) <= t1)
        occ_pastes = sum(1 for m in marks if m["type"] == "paste" and t0 <= parse_ts(m["started_at"]) <= t1)
        copies += occ_copies
        pastes += occ_pastes

        occurrences.append({
            "index": n,
            "started_at": steps[0]["started_at"],
            "ended_at": steps[-1]["ended_at"],
            "duration_ms": occ_ms,
            "copy_events": occ_copies,
            "paste_events": occ_pastes,
            "steps": [{
                "application": s["application"],
                "category": s["category"],
                "started_at": s["started_at"],
                "ended_at": s["ended_at"],
                "duration_ms": s["duration_ms"],
            } for s in steps],
        })

    reps = len(starts)
    cyclic = all(
        (starts[i] + L) < len(run) and run[starts[i] + L]["application"] == cand["sequence"][0]
        for i in range(reps - 1)
    ) if reps > 1 else False

    return {
        "pattern_key": cand["key"],
        "sequence": cand["sequence"],
        "categories": [run[starts[0] + i]["category"] for i in range(L)],
        "cyclic": cyclic,
        "repetitions": reps,
        "app_count": len(set(cand["sequence"])),
        "total_time_ms": total_ms,
        "avg_duration_ms": int(total_ms / reps) if reps else 0,
        "copy_events": copies,
        "paste_events": pastes,
        "transitions": transitions,
        "occurrences": occurrences,
        "first_seen": occurrences[0]["started_at"],
        "last_seen": occurrences[-1]["ended_at"],
    }


def merge_pattern(a, b):
    """Same workflow seen again in a later run -> add the evidence together."""
    occ = a["occurrences"] + b["occurrences"]
    for n, o in enumerate(occ, 1):
        o["index"] = n
    total = a["total_time_ms"] + b["total_time_ms"]
    reps = a["repetitions"] + b["repetitions"]
    return {
        **a,
        "cyclic": a["cyclic"] or b["cyclic"],
        "repetitions": reps,
        "total_time_ms": total,
        "avg_duration_ms": int(total / reps) if reps else 0,
        "copy_events": a["copy_events"] + b["copy_events"],
        "paste_events": a["paste_events"] + b["paste_events"],
        "transitions": a["transitions"] + b["transitions"],
        "occurrences": occ,
        "first_seen": min(a["first_seen"], b["first_seen"]),
        "last_seen": max(a["last_seen"], b["last_seen"]),
    }


# ------------------------------------------------------------------ entrypoint

def detect(events):
    """events: rows ordered by started_at. Returns MEASURED patterns.

    Scoring, employee context and narrative all happen in consultant.py — this
    module only answers "what repeated, how often, for how long"."""
    visits = [e for e in events if e["type"] == "app_visit"]
    marks = [e for e in events if e["type"] in ("copy", "paste")]

    merged = {}
    for run in segment(normalise(visits)):
        if len(run) < MIN_SEQ_LEN * MIN_REPETITIONS:
            continue
        for cand in select_patterns(run):
            p = measure(cand, run, marks)
            key = p["pattern_key"]
            merged[key] = merge_pattern(merged[key], p) if key in merged else p

    out = list(merged.values())
    out.sort(key=lambda p: (-p["repetitions"], -p["total_time_ms"]))
    return out


def stream_stats(events):
    """Headline counters computed from stored events only. No estimates."""
    visits = [e for e in events if e["type"] == "app_visit"]
    by_app, by_category, cat_of = {}, {}, {}
    for v in visits:
        by_app[v["application"]] = by_app.get(v["application"], 0) + v["duration_ms"]
        by_category[v["category"]] = by_category.get(v["category"], 0) + v["duration_ms"]
        cat_of[v["application"]] = v["category"]
    return {
        "total_events": len(events),
        "visit_events": len(visits),
        "copy_events": sum(1 for e in events if e["type"] == "copy"),
        "paste_events": sum(1 for e in events if e["type"] == "paste"),
        "time_analysed_ms": sum(v["duration_ms"] for v in visits),
        "applications": sorted(by_app),
        "by_application": sorted(
            [{"application": a, "category": cat_of[a], "duration_ms": ms} for a, ms in by_app.items()],
            key=lambda r: -r["duration_ms"]),
        "by_category": sorted(
            [{"category": c, "duration_ms": ms} for c, ms in by_category.items()],
            key=lambda r: -r["duration_ms"]),
        "transitions": max(0, len(normalise(visits)) - 1),
    }
