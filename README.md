<img src="extension/icons/icon128.png" width="76" alt="FlowMind">

# FlowMind

**Turn Work Into Progress.**

FlowMind is an AI-assisted workflow analysis prototype that helps businesses understand how everyday work moves across their tools and identify processes that may be worth improving or automating.

We built FlowMind around a simple question:

> Before a business decides how to automate, how does it know what is actually worth automating?

Employees often move between email, spreadsheets, CRMs, and internal tools to complete one process. The individual steps may look small, but repeated handoffs, copy/paste actions, and app switching can add friction that is difficult to see at a process level.

FlowMind combines employee context with approved workflow metadata to make those patterns easier to investigate.

## How it works

1. The employee tells FlowMind about their role, their tools, and the work that repeats. It is a short conversation, not a form, and the questions follow what they actually say.
2. They choose which supported applications FlowMind is allowed to observe. Nothing outside that list is visible to it.
3. While they work, a Chrome extension sends workflow metadata for those applications only, and only while an analysis is running.
4. The backend normalises the events, splits them into working runs, and looks for sequences of applications that repeat. This part is deterministic code, not a model.
5. The consultant explains what it found, separates the evidence by type, and points at the opportunity it thinks is worth investigating.

## Observed. Reported. Inferred.

Every statement FlowMind makes carries one of three labels.

**Observed** — what the approved workflow metadata actually showed. Sequences, counts, durations, app switches.

**Reported** — what the employee said in the interview, quoted back in their own words.

**Inferred** — what the two together suggest might be happening, phrased as something to check rather than something that is true.

We kept these apart deliberately. FlowMind sees that an employee moved between three applications eight times; it does not see why, and it should not pretend otherwise. An inference presented as a fact is how process tools lose the trust of the people they are meant to help.

## Opportunity Score

The score is 0–100 and is calculated in `server/consultant.py` from five stored components:

| Component | Weight | Measured against |
|---|---|---|
| Repetition frequency | 25 | how many times the sequence repeated |
| Time associated | 25 | share of analysed work time the sequence accounts for |
| Application switching | 15 | switches per repetition |
| Copy/paste activity | 15 | copy and paste events per repetition |
| Employee context | 20 | agreement between the interview and what was observed |

Every finding stores its five components, and the interface shows them behind a "Why 83?" button, so the number can always be taken apart. The language model never produces the score.

Score and confidence are separate. The score says how large the opportunity looks; confidence says how sure FlowMind is that it is real. Confidence is HIGH only when observed repetition and the employee's own description agree. When it is LOW, FlowMind asks a question instead of making a recommendation.

## Privacy

FlowMind is built around metadata, and the limits are enforced in code rather than promised in a policy.

What it records: which approved application was active, when, for how long, transitions between them, repeated sequences, and counts of copy and paste events.

What it does not record: keystrokes, passwords, copied text, email or message contents, form values, document contents, or payment information. The copy/paste listeners in `extension/content.js` never touch `clipboardData` — they count that an event happened. The ingest endpoint in `server/app.py` uses a strict schema that rejects any event carrying a field other than type, application, category, timestamps and duration, and drops any application that is not on the approved list.

Two further limits: the extension holds browser permission only for the applications in the approved catalogue, so Chrome does not expose any other address to it, and recording happens only while an analysis is explicitly running.

What the employee types in the interview is stored, because that is the point of it, and the Privacy page has a button that deletes it.

**FlowMind evaluates processes, not people.**

## Demo workflow

The repository includes three small local applications — FlowMail, FlowSheet and FlowCRM — at `/demo`. They stand in for the email, spreadsheet and CRM an employee would normally use, so the prototype can be demonstrated without touching anyone's real accounts.

The task is the one we heard described most often: take a customer request from the inbox, update a row in the spreadsheet, update the same customer in the CRM, mark the request handled. Doing it two to four times is enough for detection to have something to work with.

Demo activity runs through exactly the same pipeline as real activity, and is stored with its source recorded, so simulated sessions can be excluded from any result that is presented as validation.

## Tech

- Python 3.9+ with FastAPI and Uvicorn
- SQLite, created automatically on first run
- HTML, CSS and JavaScript with no build step and no framework
- Chrome extension, Manifest V3
- Anthropic API, optional (see below)

## Running locally

### 1. Clone

```
git clone https://github.com/<your-account>/FlowMind.git
cd FlowMind
```

### 2. Install dependencies

```
python -m pip install -r requirements.txt
```

### 3. Environment (optional)

FlowMind runs with no configuration at all. Detection, the opportunity score and the confidence level are deterministic in every case; an API key only changes who writes the consultant's sentences.

```
copy .env.example .env
```

With `ANTHROPIC_API_KEY` set, the consultant's wording comes from Claude. Without it, a built-in rules engine answers instead, instantly and offline, and each finding states which of the two produced its text. The prototype does not fail when the API is unavailable.

### 4. Start FlowMind

On Windows, double-click `start-flowmind.bat`. Otherwise:

```
python -m uvicorn server.app:app --port 8000 --host 127.0.0.1
```

One process serves the API, the app, the demo applications and the results page.

- Application: http://localhost:8000
- Pilot participant entry: http://localhost:8000/pilot
- Demo applications: http://localhost:8000/demo

The database is created empty on first launch. There is nothing to migrate or seed.

## Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Select **Load unpacked**
4. Choose the `extension` directory
5. Confirm FlowMind appears and is enabled

The extension declares host permissions for the approved application catalogue only — the local demo applications plus a set of common work tools such as Gmail, Outlook, Google Sheets, Salesforce, HubSpot and several help desks. Anything outside that list is invisible to it, which also means workflows in unsupported tools will not be detected.

## Prototype status

This is a prototype, built to test one hypothesis: that combining what an employee says with how their approved work actually happens produces a process insight a small business would act on.

What that means in practice:

- Observation is browser-based and covers approved domains only. Desktop applications are out of scope.
- Detection finds repeated sequences of applications. It is transparent and explainable, but it is not full process mining.
- There are no enterprise integrations or OAuth connections yet; permissions are chosen by the employee in the interface.
- The AI layer is optional by design, so the prototype can be demonstrated offline.
- It is built for pilot testing on one machine, not for production deployment.

## Team

Built by:

- **Lujain Alahmadi**
- **Atheer Alsulami**
- **Dina Alsulami**

Developed during the Start Smart University Challenge at King Abdulaziz University, bringing entrepreneurship and AI together to explore a practical problem: how businesses decide what work is actually worth automating.
