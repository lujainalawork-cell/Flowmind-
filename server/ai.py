"""Thin LLM adapter.

FlowMind is designed so that nothing breaks when there is no API key. Every
caller of this module must have a deterministic fallback. If a key is present
the consultant's *wording* improves; the evidence, the numbers and the score are
always produced by deterministic code.
"""

import json
import os
import urllib.error
import urllib.request

TIMEOUT_SECONDS = float(os.environ.get("FLOWMIND_AI_TIMEOUT", "12"))
MODEL = os.environ.get("FLOWMIND_AI_MODEL", "claude-sonnet-4-5")
ENDPOINT = "https://api.anthropic.com/v1/messages"


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("FLOWMIND_DISABLE_AI") != "1"


def call(system, user, max_tokens=700):
    """Returns the model's text, or None on any failure whatsoever."""
    if not available():
        return None
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode())
        text = "".join(b.get("text", "") for b in body.get("content", [])).strip()
        return text or None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError):
        return None


def call_json(system, user, required_keys=(), max_tokens=900):
    """Same, but insists on a JSON object containing required_keys."""
    text = call(system, user, max_tokens)
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not set(required_keys) <= set(parsed):
        return None
    return parsed


GUARDRAILS = """You are FlowMind, an AI business-process consultant.

Hard rules you must never break:
- You analyse PROCESSES, never a person's performance. Never comment on how fast,
  productive or good the employee is.
- You only ever see behavioural metadata (which approved application was active,
  for how long, how often a sequence repeated, counts of copy and paste events)
  plus what the employee has told you. You never see page content, text,
  clipboard contents, emails or documents.
- Never invent a number, an application, a system, a person or a fact that is not
  in the input you were given.
- Never present an inference as an observed fact. Observed means measured;
  reported means the employee said it; inferred means you concluded it.
- Hedge inferences: "may indicate", "appears consistent with", "worth investigating".
- Be concise and practical, like a good operations consultant. No filler."""
