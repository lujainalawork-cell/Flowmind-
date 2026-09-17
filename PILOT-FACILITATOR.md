# FlowMind pilot — facilitator card

Print this. Everything a participant needs is on screen; this is for you.

## Before each participant
1. Backend running (`start-flowmind.bat`), extension loaded, Chrome open.
2. Open **http://localhost:8000/pilot** — a clean start screen that says *Help us test
   FlowMind*. That address always creates a **real pilot** session with a fresh anonymous
   code (`FM-PILOT-0007`, …). Never start a participant from `/` — that page also offers a
   demo session, and demo data must never mix with validation data.
3. Hand over the keyboard. **Say nothing else.**

## What you may say
* "Work at your normal pace."
* "There are no wrong answers — FlowMind is being tested, not you."
* If they ask what it will find: **"I'd rather not say — that's what we're testing."**

## What you must NOT do
* Do not explain what the finding will be.
* Do not help them answer the interview.
* Do not touch the keyboard during the analysis.
* Do not submit feedback on their behalf.
* Do not answer the interview questions for them — the hours figure especially must be theirs.
* Do not react to their feedback answers, even the negative ones.

## If they take a wrong turn
Every step has a **← Back** button, and the browser Back button works too. Refreshing,
closing the tab and reopening `http://localhost:8000` all return them to the same step with
their answers intact. Let them do it themselves.

## If something goes wrong
| Problem | Do this |
|---|---|
| "FlowMind service offline" | Check the `start-flowmind` window is still open. |
| "FlowMind can't see any activity" on the analysis screen | The extension isn't running: `chrome://extensions` → reload FlowMind → reload the page. Nothing they've told FlowMind is lost. |
| No pattern after the analysis | The screen already offers **Continue analysis** or the **3-minute guided test**. Let them choose. |
| Really stuck, judges waiting | On the insufficient-evidence screen, **Generate a demo workday**. It is labelled *simulated* everywhere and is excluded from validation stats. |

Anything that broke is logged automatically under **Pilot issues** on the results page, so a
participant who gave up because of a fault is never mistaken for one who lost interest.

## Immediately after each session — mark assistance
Open **http://localhost:8000/pilot-results** → **Sessions · assistance** → click one of
**No / Minor / Significant** for that session code.

* This is **your** judgement, not a question for the participant.
* **No assistance** means you said nothing beyond the lines above.
* Leave it unmarked if you are not sure — an unmarked session is never counted as
  unassisted, so honesty here costs nothing.

## Record what you changed
**What we changed after testing** on the same page takes one line per change: the problem
you observed, the change made, and why. Add only what you actually saw. This is the
build → test → learn → improve trail, and it is the part judges ask about.

## Reading the results honestly
* Under five participants, the page says **Small sample** — report counts, not percentages.
* A percentage is shown only when someone actually answered; otherwise it shows **—**.
* The **Pilot funnel** counts recorded milestones only. If four started and two reached the
  finding, that is the number — nothing is estimated.
* Verbatim answers are shown exactly as typed. Never tidy them up before quoting.
* **Export CSV** gives one anonymised row per participant. Demo sessions are on a separate
  tab and are never validation evidence.

## Timing (≈5–8 minutes)
| Step | Time |
|---|---|
| Pilot start + consent | 1 min |
| Role / industry / size | 30 s |
| Interview (5–8 questions incl. company + hours) | 2–3 min |
| Automation suggestions from the conversation | 30 s |
| App access | 30 s |
| Work analysis (2–4 repetitions) | 2–3 min |
| Finding + evidence | 1 min |
| Feedback (8 questions) | 1–2 min |
