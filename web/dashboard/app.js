/* FlowMind — AI Business Consultant.
 *
 * Every number on these screens comes from the backend's deterministic analysis
 * of stored evidence. Nothing here is hard-coded, estimated or invented.
 */

const S = { state: null, summary: null, timer: null, poll: null, draft: {} };

// Must match BUILD in server/app.py. If the running server is older, the page
// says so instead of failing quietly.
const CLIENT_BUILD = '3.1';

async function checkBuild() {
  const health = await FM.safeApi('/api/health', {}, null);
  const banner = document.getElementById('build-banner');
  if (!banner) return;
  const fit = () => {
    document.body.style.paddingTop =
      banner.classList.contains('ok') || banner.classList.contains('bad')
        ? banner.offsetHeight + 'px' : '0px';
  };
  if (!health) {
    banner.className = 'buildbanner bad';
    banner.innerHTML = `<b>FlowMind service is not running.</b>
      Start it again, then reload this page.`;
    setTimeout(fit, 30);
    return;
  }
  if (health.build !== CLIENT_BUILD) {
    banner.className = 'buildbanner bad';
    banner.innerHTML = `<b>The FlowMind server is running older code
      (${FM.escape(health.build || 'pre-2.2')}, this page is ${CLIENT_BUILD}).</b>
      Go to the window running FlowMind, press <kbd>Ctrl</kbd>+<kbd>C</kbd>, start it again,
      then reload this page. Until you do, Back and some other buttons will not work.`;
    setTimeout(fit, 30);
    return;
  }
  banner.className = 'buildbanner ok';
  banner.textContent = `FlowMind ${CLIENT_BUILD} · connected`;
  setTimeout(fit, 30);
  setTimeout(() => {
    banner.className = 'buildbanner ok faded';
    document.body.style.paddingTop = '0px';
  }, 3500);
}

const DASHBOARD_STAGES = ['finding', 'feedback', 'done'];
const FLOW_ORDER = ['welcome', 'consent', 'context', 'interview', 'permissions', 'ready',
                    'observe', 'aha', 'finding', 'feedback', 'done'];

// Four named phases instead of an anonymous progress bar, so the participant
// always knows where they are and how much is left.
const PHASES = [
  { n: '01', label: 'About you', stages: ['consent', 'context', 'interview'] },
  { n: '02', label: 'Work access', stages: ['permissions', 'ready'] },
  { n: '03', label: 'Analysis', stages: ['observe'] },
  { n: '04', label: 'Insights', stages: ['aha', 'finding', 'feedback', 'done'] },
];

/* Each step of the guided flow gets its OWN url (#/step/interview and so on).
   That is what makes the browser's Back button work: there is a real history
   entry per step to go back to. route() then reconciles the server with
   whatever step the url says. */
function stepIndex(name) { return FLOW_ORDER.indexOf(name); }

function hashStep() {
  const m = location.hash.match(/^#\/step\/([a-z]+)/);
  return m && stepIndex(m[1]) >= 0 ? m[1] : null;
}

/** Forward moves push a history entry; rewinds replace, because the entry they
 *  came from has already been popped. */
function syncStepHash(st) {
  const target = '#/step/' + st;
  if (location.hash === target) return;
  const from = hashStep();
  if (!from || stepIndex(st) > stepIndex(from)) {
    history.pushState({ step: st }, '', target);
    stepDepth += 1;
  } else {
    history.replaceState({ step: st }, '', target);
  }
}

let stepDepth = 0;

// Where "Back" goes from each step, and what the participant returns to.
const FLOW_BACK = {
  consent: 'the start',
  context: 'the permission summary',
  interview: 'your work details',
  permissions: 'the interview',
  ready: 'app access',
  observe: 'the briefing',
  aha: 'the work analysis',
  finding: 'the summary',
  feedback: 'the finding',
  done: 'the feedback form',
};
let lastFlowStage = null;

const CAT_COLOR = {
  Email: '#6192FC', Spreadsheet: '#2FA36B', CRM: '#11358B', Support: '#D4634F',
  Project: '#8A6BE0', Messaging: '#E8A33D', Finance: '#3FA9B8', ERP: '#B85C9E',
  Other: '#9AA3BE',
};

const MARK = `<svg width="20" height="20" viewBox="0 0 32 32" fill="none">
  <path d="M6 21c4-10 16-10 20 0" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
  <circle cx="16" cy="11.5" r="2.8" fill="#C7EF66"/></svg>`;

const el = (id) => document.getElementById(id);
const view = () => el('view');

function clearTimers() {
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
  if (S.poll) { clearInterval(S.poll); S.poll = null; }
}

/* ===================================================================== data */

async function loadState() {
  S.state = await FM.safeApi('/api/state', {}, null);
  return S.state;
}

async function loadSummary() {
  S.summary = await FM.safeApi('/api/summary', {}, null);
  return S.summary;
}

function session() { return S.state && S.state.session; }
function stage() { return session() ? session().stage : 'welcome'; }

/* ================================================================== chrome */

function renderChrome(showDashboard) {
  const bar = el('sidebar');
  bar.hidden = !showDashboard;
  document.body.classList.toggle('flow', !showDashboard);
  if (!showDashboard) return;

  const s = S.summary || {};
  el('nav-count').textContent = (s.findings || []).length;
  el('session-code').textContent = session() ? session().code : '';

  const status = el('statusbar');
  const text = el('statustext');
  status.className = 'statusbar';
  if (!S.state) {
    status.classList.add('offline');
    status.querySelector('.dot').className = 'dot dot-paused';
    text.textContent = 'Service offline';
  } else if (S.state.monitoring_paused) {
    status.classList.add('paused');
    status.querySelector('.dot').className = 'dot dot-paused';
    text.textContent = 'Monitoring paused';
  } else if (S.state.recording) {
    status.querySelector('.dot').className = 'dot dot-live';
    text.textContent = 'Analyzing work';
  } else {
    status.classList.add('paused');
    status.querySelector('.dot').className = 'dot dot-paused';
    text.textContent = 'Analysis complete';
  }

  const route = (location.hash.split('/')[1] || 'overview');
  document.querySelectorAll('#nav a').forEach(a =>
    a.classList.toggle('active', a.dataset.route === route));
}

function flowHeader(current) {
  const idx = FLOW_ORDER.indexOf(current);
  const activePhase = PHASES.findIndex(p => p.stages.includes(current));
  const rail = PHASES.map((p, i) => `
    <div class="phase ${i < activePhase ? 'done' : i === activePhase ? 'now' : ''}">
      <span class="pn">${i < activePhase ? '✓' : p.n}</span>
      <span class="pl">${p.label}</span>
    </div>`).join('');
  return `
    <div class="flowbrand">
      <span class="mark">${MARK}</span>
      <span>
        <div class="n">FlowMind</div>
        <div class="t">AI Business Consultant</div>
      </span>
      ${session() ? `<span class="code">${session().code}</span>` : ''}
    </div>
    ${activePhase >= 0 ? `<div class="phases">${rail}</div>` : ''}
    ${FLOW_BACK[current] ? `<button class="btn btn-ghost btn-sm flowback" id="flow-back"
        title="Go back to ${FLOW_BACK[current]}">\u2190 Back</button>` : ''}`;
}

/** One step back through the guided flow. The server undoes the side effect of
 *  the forward step (stops recording, reopens the analysis) so nothing is left
 *  in a half-finished state. */
async function goBack() {
  // Prefer the real history entry, so our button and the browser's do exactly
  // the same thing. Only step back directly if there is nothing to pop.
  if (stepDepth > 0) {
    stepDepth -= 1;
    history.back();
    return;
  }
  const r = await FM.safeApi('/api/pilot/back', { method: 'POST' }, null);
  if (!r) return FM.toast('Could not go back');
  const target = r.stage || 'welcome';
  history.replaceState({ step: target }, '', '#/step/' + target);
  await route();
}

/* ================================================================ screens */

const IS_PILOT_ENTRY = location.pathname.replace(/\/$/, '') === '/pilot';

function screenPilotEntry() {
  return `
    ${flowHeader('welcome')}
    <div style="max-width:620px;margin:0 auto;text-align:center">
      <div class="eyebrow" style="margin-bottom:10px">Pilot</div>
      <h1 style="font-size:36px;line-height:1.15;margin-bottom:16px">Help us test FlowMind</h1>
      <p class="lead" style="margin:0 auto 10px">
        This short pilot takes about 5 minutes. You'll experience FlowMind as an employee
        and tell us whether its analysis was actually useful.
      </p>
      <p class="small muted" style="margin-bottom:28px">
        No name, no email, no company name. Your session is identified only by a code.
      </p>
      <button class="btn btn-primary" id="start-pilot-run" style="font-size:16px;padding:15px 34px">
        Start pilot →</button>
      <p class="tiny muted" style="margin-top:16px">
        There are no right answers, and nothing here is a test of you.
      </p>
    </div>`;
}

function screenWelcome() {
  return `
    ${flowHeader('welcome')}
    <div class="hero" style="text-align:center;max-width:680px;margin:0 auto">
      <h1 style="font-size:40px;line-height:1.1;margin-bottom:16px">
        Your AI Business Consultant<br>for how work gets done.</h1>
      <p class="lead" style="margin:0 auto;font-size:17px">
        FlowMind learns how your work actually happens, identifies repetitive processes,
        and helps uncover opportunities for improvement and automation.
      </p>
    </div>

    <div class="journey">
      <div class="jstep">
        <div class="ji">1</div>
        <div class="jt">Tell me about your work</div>
        <div class="jd">A short conversation, in your own words.</div>
      </div>
      <div class="jstep">
        <div class="ji">2</div>
        <div class="jt">Work normally</div>
        <div class="jd">Only in the applications you approve.</div>
      </div>
      <div class="jstep">
        <div class="ji">3</div>
        <div class="jt">I find the patterns</div>
        <div class="jd">Repeated steps, switching, manual transfer.</div>
      </div>
      <div class="jstep last">
        <div class="ji">★</div>
        <div class="jt">You get the opportunity</div>
        <div class="jd">With the evidence behind it.</div>
      </div>
    </div>

    <div class="row" style="justify-content:center;gap:14px;margin-top:8px">
      <button class="btn btn-primary" id="start-pilot" style="font-size:16px;padding:15px 32px">
        Start my work analysis →</button>
    </div>
    <p style="text-align:center;margin-top:14px">
      <a class="small muted" id="how-it-works" href="#">How does FlowMind work?</a>
    </p>

    <div class="hidden" id="how-panel">
      <div class="card" style="margin-top:20px">
        <div class="eyebrow" style="margin-bottom:12px">How FlowMind works</div>
        <p class="small" style="margin-bottom:12px">
          I combine two things most tools keep apart. <b>What you tell me</b> about your work,
          and <b>what actually happens</b> in the applications you approve — which app was
          active, for how long, what order you moved through them, and how often you copied
          and pasted. Never what was in them.
        </p>
        <p class="small">
          On their own, neither is enough. Activity alone shows switching but not why.
          A conversation alone is memory, not measurement. Together they are evidence.
          Every statement I make is labelled <b>observed</b>, <b>reported</b> or
          <b>inferred</b>, so you always know which is which.
        </p>
      </div>
    </div>

    <div class="privacyline">
      <span class="shield">
        <svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="#11358B" stroke-width="1.8">
          <path d="M10 2.6 16 5v5c0 4-2.6 6.6-6 7.6C6.6 16.6 4 14 4 10V5z" stroke-linejoin="round"/>
        </svg>
      </span>
      <div>
        <b>Private by design</b>
        <div class="small muted" style="margin-top:3px">
          FlowMind analyzes approved workflow metadata — not the contents of your work.
          No passwords, no keystrokes, no message or document contents. You choose every
          application it may look at, and you can stop it at any time.
        </div>
      </div>
    </div>

    <div class="row wrap" style="justify-content:center;gap:16px;margin-top:22px">
      <button class="btn btn-ghost btn-sm" id="start-demo">Run a demo session</button>
      <a class="tiny muted" href="/pilot-results">Team: pilot results</a>
    </div>`;
}
function screenConsent() {
  return `
    ${flowHeader('consent')}
    <div class="eyebrow" style="margin-bottom:8px">Connect your work environment</div>
    <h1 style="margin-bottom:12px">Before we begin, FlowMind needs your permission.</h1>
    <p class="lead">
      FlowMind analyzes approved work activity metadata and combines it with your input to
      identify repetitive work, workflow friction and potential automation opportunities.
    </p>

    <div class="permgrid">
      <div class="privacy-col">
        <h3><span class="tick">✓</span> FlowMind may analyze</h3>
        <ul class="plist">
          <li><span class="tick">✓</span> Which approved application is active</li>
          <li><span class="tick">✓</span> Time spent in approved applications</li>
          <li><span class="tick">✓</span> Switching between approved applications</li>
          <li><span class="tick">✓</span> Repeated workflow sequences</li>
          <li><span class="tick">✓</span> Counts of copy and paste events</li>
          <li><span class="tick">✓</span> What you tell it about your tasks</li>
        </ul>
      </div>
      <div class="privacy-col">
        <h3><span class="cross">✕</span> FlowMind does not collect</h3>
        <ul class="plist">
          <li><span class="cross">✕</span> Passwords</li>
          <li><span class="cross">✕</span> Keystrokes</li>
          <li><span class="cross">✕</span> Email or message contents</li>
          <li><span class="cross">✕</span> Copied or pasted text</li>
          <li><span class="cross">✕</span> Private document contents</li>
          <li><span class="cross">✕</span> Payment information</li>
        </ul>
      </div>
    </div>

    <div class="banner info" style="margin-bottom:24px">
      <div>
        <b>What this prototype actually does.</b>
        <div class="small" style="margin-top:4px">
          Allowing access here lets a Chrome extension record metadata about the websites you
          approve on the next screens — nothing more. It does not give FlowMind access to your
          computer, your accounts or any application outside the browser. A production deployment
          would use organization-approved integrations and SSO; that is not built here, and
          FlowMind will not pretend otherwise.
        </div>
      </div>
    </div>

    <div class="row wrap" style="gap:12px">
      <button class="btn btn-primary" id="allow" style="font-size:15px;padding:13px 26px">Allow access</button>
      <button class="btn btn-secondary" id="choose">Choose what FlowMind can access</button>
    </div>`;
}

const INDUSTRIES = ['Retail', 'Professional Services', 'Food & Beverage', 'E-commerce',
                    'Technology', 'Healthcare', 'Education', 'Other'];

function screenContext() {
  const sizes = ['1-10', '11-50', '51-200', '200+'];
  // Whatever was already saved wins, so coming back here shows the real answers
  // rather than an empty form.
  const saved = session() || {};
  const d = {
    industry: S.draft.industry || saved.industry || '',
    role: S.draft.role || saved.role || '',
    company_size: S.draft.company_size || saved.company_size || '',
  };
  S.draft = { ...S.draft, ...d };

  return `
    ${flowHeader('context')}
    <h1 style="margin-bottom:10px">First, help me understand your work.</h1>
    <p class="lead" style="margin-bottom:28px">
      Just like a consultant, I need a little context before I can make any recommendation.
      This takes about thirty seconds.
    </p>

    <div class="card">
      <div class="field-row">
        <label for="role">What's your role?</label>
        <input class="input" id="role" placeholder="e.g. Operations coordinator, office manager"
               value="${FM.escape(d.role)}" autocomplete="off">
      </div>

      <div class="field-row">
        <label>What kind of business is it?</label>
        <div class="pickgrid" id="industries">
          ${INDUSTRIES.map(i => `<button class="pick ${d.industry === i ? 'selected' : ''}"
            data-industry="${FM.escape(i)}">${FM.escape(i)}</button>`).join('')}
        </div>
      </div>

      <div class="field-row" style="margin-bottom:6px">
        <label>How many people work there?</label>
        <div class="optionrow" id="sizes">
          ${sizes.map(x => `<button class="option ${d.company_size === x ? 'selected' : ''}"
            data-size="${x}">${x}</button>`).join('')}
        </div>
      </div>
    </div>

    <div class="row" style="margin-top:22px">
      <button class="btn btn-primary" id="context-next" style="font-size:15px;padding:13px 26px">
        Continue with FlowMind →</button>
    </div>
    <p class="tiny muted" style="margin-top:12px">
      No company name, no email, no personal details — this stays anonymous.
    </p>`;
}
function bubble(role, text) {
  const avatar = role === 'consultant'
    ? `<span class="av">${MARK}</span>`
    : `<span class="av">You</span>`;
  // escape first, then allow only **bold** through — nothing else is interpreted
  const body = FM.escape(text).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  return `<div class="bubble ${role === 'consultant' ? '' : 'me'}">
      ${avatar}<div class="body">${body}</div></div>`;
}

function learnedChips(profile) {
  if (!profile) return '';
  const chips = [];
  if (profile.role) chips.push(['Role', profile.role]);
  if (profile.industry) chips.push(['Industry', profile.industry]);
  (profile.primary_tools || []).slice(0, 4).forEach(t => chips.push(['Uses', t]));
  if (profile.hours_per_week) chips.push(['Reported', `${profile.hours_per_week}h a week`]);
  (profile.recurring_tasks || []).slice(0, 1).forEach(t =>
    chips.push(['Repeats', t.length > 46 ? t.slice(0, 46) + '…' : t]));
  if (!chips.length) return '';
  return `<div class="learned">${chips.map(([k, v]) =>
    `<span class="chip"><span class="k">${k}</span><b>${FM.escape(String(v))}</b></span>`).join('')}</div>`;
}

function screenInterview(data) {
  const asked = data.asked || 0;
  return `
    ${flowHeader('interview')}
    <div class="row between wrap" style="margin-bottom:10px">
      <div class="eyebrow">FlowMind Consultant</div>
      <span class="thinking"><span class="pulse"></span> Learning about your work</span>
    </div>
    <h1 style="margin-bottom:10px">Let's talk about your work.</h1>
    <p class="lead" style="margin-bottom:8px">
      Answer in your own words — a sentence or two is plenty. I'll ask four to six questions
      and follow up on whatever you tell me.
    </p>
    <p class="tiny muted" style="margin-bottom:8px" id="q-counter">Question ${Math.max(1, asked)} of about 6</p>
    <div id="learned">${learnedChips(S.state && S.state.profile)}</div>
    <div style="height:18px"></div>

    <div class="chat" id="chat">
      ${data.transcript.map(m => bubble(m.role, m.text)).join('')}
    </div>

    <div id="composer-wrap">
      <div class="composer">
        <textarea id="answer" placeholder="Type your answer… (Enter to send, Shift+Enter for a new line)"></textarea>
        <button class="btn btn-primary" id="send" style="padding:14px 22px">Send</button>
      </div>
      <div class="row" style="margin-top:12px">
        <span class="tiny muted">Nothing you type here leaves this computer.</span>
        <span class="spacer"></span>
        ${asked >= 2 ? `<button class="btn btn-ghost btn-sm" id="skip">I've said enough →</button>` : ''}
      </div>
    </div>
    <div id="interview-close" style="margin-top:26px"></div>`;
}

function suggestionCard(sug) {
  return `
    <div class="card" style="margin-bottom:12px">
      <div class="row between wrap" style="margin-bottom:8px">
        <h3 style="font-size:16px">${FM.escape(sug.title)}</h3>
        <span class="row" style="gap:6px">
          <span class="evidence-tag reported">Reported</span>
          <span class="pill pill-low">${FM.escape(sug.effort)} effort</span>
        </span>
      </div>
      <p class="small" style="margin-bottom:12px">${FM.escape(sug.what)}</p>
      <div class="qa" style="margin:0">
        <div class="q">How to approach it</div>
        <div class="a" style="font-size:14px">${FM.escape(sug.how)}</div>
      </div>
      ${sug.reported_time ? `<p class="tiny muted" style="margin-top:10px">${FM.escape(sug.reported_time)}</p>` : ''}
      ${(sug.based_on || []).length ? `
        <details style="margin-top:10px">
          <summary class="tiny muted" style="cursor:pointer">What you told me</summary>
          ${sug.based_on.map(q => `<blockquote style="margin:9px 0 0;padding-left:13px;
            border-left:3px solid var(--lime);font-size:13.5px">\u201c${FM.escape(q)}\u201d</blockquote>`).join('')}
        </details>` : ''}
    </div>`;
}

function suggestionsBlock(suggestions, intro) {
  if (!suggestions || !suggestions.length) return '';
  return `
    <div class="eyebrow" style="margin:0 0 6px">Automation suggestions from our conversation</div>
    <p class="small muted" style="margin-bottom:14px">${intro}</p>
    ${suggestions.map(suggestionCard).join('')}`;
}

function screenPermissions(permissions, profile) {
  const rows = permissions.map(p => `
    <div class="approw">
      <span class="appicon ${p.category}">${FM.initials(p.app_label)}</span>
      <div class="meta">
        <div class="nm">${FM.escape(p.app_label)}</div>
        <div class="dm">${FM.escape(p.product)} · ${FM.escape(p.domain)}${p.path_prefix || ''} · ${p.category}</div>
      </div>
      <span class="toggle-label ${p.allowed ? 'on' : 'off'}">${p.allowed ? 'Allowed' : 'Not allowed'}</span>
      <button class="toggle ${p.allowed ? 'on' : ''}" data-perm="${p.id}"
        aria-label="${p.allowed ? 'Disallow' : 'Allow'} ${FM.escape(p.app_label)}"></button>
    </div>`).join('');

  return `
    ${flowHeader('permissions')}
    <div class="eyebrow" style="margin-bottom:8px">App access</div>
    <h1 style="margin-bottom:10px">Choose what FlowMind may observe.</h1>
    <p class="lead" style="margin-bottom:26px">
      FlowMind records metadata only for the applications you allow here. Everything else is
      invisible to it — the browser extension is not even permitted to read the address.
    </p>

    ${profile && profile.primary_tools && profile.primary_tools.length ? `
      <div class="banner info" style="margin-bottom:20px">
        <div><b>You mentioned ${profile.primary_tools.slice(0, 3).map(FM.escape).join(', ')}.</b>
        <div class="small" style="margin-top:3px">Allow the matching applications below so FlowMind
        can look for the work you described.</div></div>
      </div>` : ''}

    <div class="card">
      <div class="applist">${rows}</div>
      <hr class="divider">
      <div class="eyebrow" style="margin-bottom:10px">Add an approved website</div>
      <div class="row wrap" style="gap:10px">
        <input class="input" id="new-domain" placeholder="app.example.com" style="flex:2;min-width:180px">
        <input class="input" id="new-label" placeholder="Name, e.g. Our CRM" style="flex:1;min-width:140px">
        <select class="input" id="new-category" style="flex:0 0 150px">
          <option value="Email">Email</option>
          <option value="Spreadsheet">Spreadsheet</option>
          <option value="CRM">CRM</option>
          <option value="Support">Customer service / help desk</option>
          <option value="Project">Project</option>
          <option value="Messaging">Messaging</option>
          <option value="Finance">Finance</option>
          <option value="ERP">ERP</option>
          <option value="Other" selected>Other</option>
        </select>
        <button class="btn btn-secondary" id="add-domain">Add</button>
      </div>
      <p class="tiny muted" style="margin-top:10px">
        Added sites are approved immediately in FlowMind. The extension ships with browser
        permission for the applications listed above; for any other site Chrome will ask you to
        grant permission the first time it is used, and until you do it simply isn't recorded.
      </p>
    </div>

    <div class="row wrap" style="gap:12px;margin-top:22px">
      <button class="btn btn-primary" id="perms-next" style="font-size:15px;padding:13px 26px">
        Continue →</button>
      <span class="small muted">You can change this at any time on the Privacy page.</span>
    </div>`;
}

function screenReady(profile) {
  const tools = (profile && profile.primary_tools) || [];
  return `
    ${flowHeader('ready')}
    <div class="eyebrow" style="margin-bottom:8px">Ready</div>
    <h1 style="margin-bottom:12px">I'm ready.</h1>
    <p class="lead" style="margin-bottom:28px">
      I'll now compare what you told me about your work with the activity in the
      applications you approved${tools.length ? ` — you mentioned ${tools.slice(0, 3).map(FM.escape).join(', ')}` : ''}.
    </p>

    <div class="card">
      <div class="eyebrow" style="margin-bottom:14px">What I'll look for</div>
      <ul class="plist">
        <li><span class="tick">✓</span><div><b>Repeated processes</b>
          <div class="small muted">The same sequence of applications, happening again and again.</div></div></li>
        <li><span class="tick">✓</span><div><b>Frequent application switching</b>
          <div class="small muted">Work that cannot be finished in one place.</div></div></li>
        <li><span class="tick">✓</span><div><b>Signals of manual information transfer</b>
          <div class="small muted">Copy and paste counts inside a repeating sequence.</div></div></li>
        <li><span class="tick">✓</span><div><b>Time-heavy workflows</b>
          <div class="small muted">Where the analysed time actually goes.</div></div></li>
      </ul>
      <p class="tiny muted" style="margin-top:16px">
        I record only while the analysis is running, only in the applications you approved,
        and you can pause me at any time.
      </p>
    </div>

    <div class="row wrap" style="gap:12px;margin-top:24px">
      <button class="btn btn-primary" id="begin-analysis" style="font-size:15px;padding:14px 28px">
        Start work analysis →</button>
      <a class="btn btn-secondary" href="/demo" target="_blank">Try the 3-minute guided demo</a>
    </div>`;
}

function screenAha(finding) {
  const seq = finding.sequence.map((n, i) =>
    `<span class="fnode">${FM.escape(n)}</span>` +
    (i < finding.sequence.length - 1 ? '<span style="color:#9FBFFF">→</span>' : '')).join('');
  return `
    ${flowHeader('aha')}
    <div class="aha">
      <div class="kicker">
        <span class="dot" style="background:#C7EF66"></span> Analysis complete
      </div>
      <h1>I found something worth looking at.</h1>
      <p class="sub">${FM.escape(finding.title)} — a sequence you repeated
        ${finding.repetitions} times while I was watching.</p>
      <div class="flowline">${seq}
        ${finding.cyclic ? '<span style="color:#9FBFFF">↺</span><span class="fnode loop">back to '
          + FM.escape(finding.sequence[0]) + '</span>' : ''}</div>
      <div class="ahascore">
        <span class="v">${finding.score}</span>
        <span class="d">/ 100 opportunity score · confidence ${finding.confidence}</span>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top:24px;align-items:start">
      <div class="evidence observed" style="margin:0">
        <span class="tag">Observed</span>
        <p style="font-size:14.5px">${FM.escape(finding.observed[0])}</p>
      </div>
      <div class="evidence reported" style="margin:0">
        <span class="tag">Reported</span>
        <p style="font-size:14.5px">${finding.reported.quotes.length
          ? '\u201c' + FM.escape(finding.reported.quotes[0].text) + '\u201d'
          : 'You have not described this part of your work to me yet.'}</p>
      </div>
    </div>
    <div class="evidence inferred" style="margin-top:12px">
      <span class="tag">Inferred</span>
      <p style="font-size:14.5px">${FM.escape(finding.narrative.possible_issue)}</p>
    </div>

    <div class="row wrap" style="gap:12px;margin-top:24px">
      <button class="btn btn-primary" id="see-analysis" style="font-size:15px;padding:14px 28px">
        See consultant analysis →</button>
      <button class="btn btn-secondary" id="not-accurate">That's not accurate</button>
    </div>`;
}

function screenObserve(status) {
  return `
    ${flowHeader('observe')}
    <div class="eyebrow" style="margin-bottom:8px">Work analysis</div>
    <h1 style="margin-bottom:10px">Now just work the way you normally would.</h1>
    <p class="lead" style="margin-bottom:26px">
      FlowMind is analyzing approved workflow metadata. Do a task you repeat often — two to four
      times is enough. When you're finished, come back and press <b>Finish analysis</b>.
    </p>

    <div class="observer" id="observer">
      <div class="live"><span class="pulse"></span> <span id="obs-state">Analyzing approved workflow metadata</span></div>
      <div class="timer" id="obs-timer">00:00</div>
      <div class="sub" id="obs-current">Waiting for activity in an approved application…</div>
      <div class="obsgrid">
        <div class="cell"><div class="v" id="obs-events">0</div><div class="l">Events captured</div></div>
        <div class="cell"><div class="v" id="obs-apps">0</div><div class="l">Applications observed</div></div>
        <div class="cell"><div class="v" id="obs-switches">0</div><div class="l">App switches</div></div>
        <div class="cell"><div class="v" id="obs-reps">0</div><div class="l">Repeated sequences</div></div>
      </div>
    </div>

    <div class="card hidden" id="no-extension"
         style="margin-top:18px;border-color:#E8A33D;background:#FDF3E4">
      <b>FlowMind can't see any activity.</b>
      <p class="small" style="margin-top:6px">
        The browser extension isn't running, so nothing is being recorded. Load it from
        <code>chrome://extensions</code> (Developer mode → Load unpacked → the
        <b>extension</b> folder) and reload this page. Nothing you have told FlowMind is lost.
      </p>
    </div>

    <div class="row wrap" style="gap:12px;margin-top:22px">
      <button class="btn btn-primary" id="finish" style="font-size:15px;padding:13px 26px">Finish analysis</button>
      <button class="btn btn-secondary" id="pause">${S.state.monitoring_paused ? 'Resume' : 'Pause'}</button>
      <span class="spacer"></span>
      <a class="btn btn-secondary" href="/demo/mail" target="_blank">Open the guided test →</a>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="eyebrow" style="margin-bottom:10px">Approved right now</div>
      <div class="row wrap" style="gap:7px" id="obs-approved"></div>
      <p class="tiny muted" style="margin-top:12px">
        Don't have a repetitive task handy? The <b>guided test</b> gives you a small customer-request
        workflow across three demo applications. Do it two to four times, at your own pace.
      </p>
    </div>`;
}

function evidenceBlock(finding) {
  const reported = finding.reported.quotes || [];
  return `
    <div class="evidence observed">
      <span class="tag">Observed</span>
      <ul>${finding.observed.map(o => `<li>${FM.escape(o)}</li>`).join('')}</ul>
    </div>
    <div class="evidence reported">
      <span class="tag">Reported</span>
      ${reported.length
        ? reported.map(q => `<blockquote>“${FM.escape(q.text)}”<cite>you, in the ${FM.escape(q.source)}</cite></blockquote>`).join('')
        : `<p class="small muted">You haven't described this part of your work yet, so this
             finding currently rests on observed activity alone.</p>`}
    </div>
    <div class="evidence inferred">
      <span class="tag">Inferred</span>
      <ul><li>${FM.escape(finding.narrative.possible_issue)}</li></ul>
      <p class="tiny muted" style="margin-top:8px">
        An inference, not a fact. FlowMind sees metadata, never content.
      </p>
    </div>`;
}

function scoreTable(finding) {
  return `<table class="components">${finding.components.map(c => `
    <tr>
      <td><div class="lbl">${FM.escape(c.label)}</div>
          <div class="det">${FM.escape(String(c.value))} ${FM.escape(c.unit)} · counts up to ${c.cap}</div></td>
      <td style="width:110px;padding-left:16px">
        <div class="bar ${c.points / c.weight > .8 ? 'lime' : ''}">
          <span style="width:${Math.round(c.points / c.weight * 100)}%"></span></div></td>
      <td class="pts" style="width:72px">${c.points} / ${c.weight}</td>
    </tr>`).join('')}</table>`;
}

function screenFinding(finding, inFlow = true) {
  return `
    ${inFlow ? flowHeader('finding') : ''}
    <div class="eyebrow" style="margin-bottom:8px">Consultant finding</div>
    <div class="row between wrap" style="margin-bottom:6px">
      <h1>${FM.escape(finding.title)}</h1>
      <span class="confidence ${finding.confidence}">Confidence: ${finding.confidence}</span>
    </div>
    <p class="lead" style="margin-bottom:26px">${FM.escape(finding.narrative.why_flagged)}</p>

    <div class="grid" style="grid-template-columns:minmax(0,1fr) 260px;gap:24px;align-items:start">
      <div>${evidenceBlock(finding)}</div>
      <div class="card" style="text-align:center">
        <div class="eyebrow" style="margin-bottom:12px">Opportunity score</div>
        ${scoreRing(finding.score, finding.band)}
        <div style="margin-top:12px">${bandPill(finding.band)}</div>
        <p class="tiny muted" style="margin-top:12px">${FM.escape(finding.confidence_reason)}</p>
        <button class="btn btn-secondary btn-sm" id="why-score" style="margin-top:14px">Why ${finding.score}?</button>
      </div>
    </div>

    <div class="card hidden" id="score-detail" style="margin-top:18px">
      <div class="eyebrow" style="margin-bottom:14px">How the score was calculated</div>
      ${scoreTable(finding)}
      <div class="row between" style="margin-top:12px;padding-top:12px;border-top:2px solid var(--line)">
        <b>Opportunity score</b><b>${finding.score} / 100</b>
      </div>
      <p class="tiny muted" style="margin-top:10px">
        Deterministic. The same evidence always produces the same score — no model invents it.
      </p>
    </div>

    <div class="card" style="margin-top:18px">
      <div class="qa"><div class="q">Possible issue</div><div class="a">${FM.escape(finding.narrative.possible_issue)}</div></div>
      <div class="qa"><div class="q">Business impact</div><div class="a">${FM.escape(finding.narrative.business_impact)}</div></div>
      <div class="qa"><div class="q">Recommended next step</div><div class="a">${FM.escape(finding.narrative.recommended_next_step)}</div></div>
      <div class="qa"><div class="q">Automation potential</div><div class="a">${FM.escape(finding.narrative.automation_potential)}</div></div>
      <p class="tiny muted" style="margin-top:14px">
        Wording produced by the ${finding.analysis_source === 'ai' ? 'AI interpretation layer'
          : 'built-in rules engine (offline fallback)'}. The evidence and the score above are
        computed deterministically either way.
      </p>
    </div>

    ${finding.open_question ? `
      <div class="askbox" id="askbox">
        <div class="row" style="gap:12px;align-items:flex-start">
          <span class="av" style="width:30px;height:30px;border-radius:10px;background:var(--blue);display:grid;place-items:center;flex:none">${MARK}</span>
          <div style="flex:1">
            <b>FlowMind would like to ask you something</b>
            <p style="margin-top:6px">${FM.escape(finding.open_question)}</p>
            <div class="composer" style="margin-top:12px">
              <textarea id="answer-open" placeholder="Answer in your own words…"></textarea>
              <button class="btn btn-primary" id="send-open" style="padding:13px 20px">Answer</button>
            </div>
          </div>
        </div>
      </div>` : ''}

    <div class="row wrap" style="gap:12px;margin-top:24px">
      ${inFlow ? `<button class="btn btn-primary" id="to-feedback" style="font-size:15px;padding:13px 26px">
        Continue →</button>` : ''}
      <a class="btn btn-secondary" href="#/consultant">Ask FlowMind about this</a>
      ${inFlow ? `<button class="btn btn-ghost btn-sm" id="more-analysis">Keep analyzing instead</button>` : ''}
    </div>`;
}

function screenInsufficient(message) {
  return `
    ${flowHeader('observe')}
    <div class="empty" style="text-align:left;padding:34px">
      <h3 style="margin-bottom:8px">I don't have enough activity yet.</h3>
      <p style="margin:0 0 18px">${FM.escape(message ||
        "I don't have enough activity yet to confidently identify a repeated workflow.")}
        I'd rather tell you that than invent a pattern.</p>
      <div class="row wrap" style="gap:12px">
        <button class="btn btn-primary" id="continue-analysis">Continue analysis</button>
        <a class="btn btn-secondary" href="/demo/mail" target="_blank">Complete a 3-minute guided test</a>
        <button class="btn btn-ghost btn-sm" id="gen-demo">Generate a demo workday</button>
      </div>
      <p class="tiny muted" style="margin-top:16px">
        A repeated workflow needs the same sequence of approved applications to happen at least
        twice. Two to four repetitions of a normal task is usually enough.
      </p>
    </div>`;
}

/* Each question offers a negative answer, and none of them hints at the answer we
   would like. The follow-up box sits directly under the question it belongs to. */
const FEEDBACK_QUESTIONS = [
  ['understanding_rating', 'Did FlowMind understand this part of your work?',
    ['Yes', 'Partially', 'No']],
  ['repetition_rating', 'Is this a repetitive or frustrating part of your job?',
    ['Yes', 'Sometimes', 'No']],
  ['usefulness_rating', 'Would identifying workflows like this be useful to your business?',
    ['Very useful', 'Somewhat useful', 'Not useful']],
  ['investigate_rating', 'Would you recommend your business investigate the workflow FlowMind identified?',
    ['Yes', 'Maybe', 'No'], ['fb-investigate-why', 'Why?']],
  ['continued_use_rating', 'If FlowMind were available at your company today, would you want it to continue analyzing your workflows?',
    ['Yes', 'Maybe', 'No']],
  ['permission_comfort', 'Would you be comfortable with FlowMind analyzing work-activity metadata from the applications you choose?',
    ['Yes', 'Maybe', 'No'], ['fb-reason', 'Why did you answer that way?']],
];

function screenFeedback(finding) {
  return `
    ${flowHeader('feedback')}
    <div class="eyebrow" style="margin-bottom:8px">Your verdict</div>
    <h1 style="margin-bottom:10px">What did you make of that?</h1>
    <p class="lead" style="margin-bottom:26px">
      This is the part we actually need. Critical answers are more useful to us than kind
      ones, and nobody at your company sees them.
      ${finding ? `You're rating the finding <b>${FM.escape(finding.title)}</b>.` : ''}
    </p>

    <div class="fb">
      ${FEEDBACK_QUESTIONS.map(([key, label, options, followup]) => `
        <div class="fbq">
          <div class="label">${label}</div>
          <div class="row wrap" style="gap:8px">
            ${options.map(o => `<button class="choice" data-q="${key}" data-v="${o}">${o}</button>`).join('')}
          </div>
          ${followup ? `<textarea class="fbtext" style="margin-top:10px" id="${followup[0]}"
            placeholder="${followup[1]} (optional)"></textarea>` : ''}
        </div>`).join('')}

      <div class="fbq">
        <div class="label">In your own words, what do you think FlowMind does?</div>
        <textarea class="fbtext" id="fb-understanding"
          placeholder="However you'd describe it to a colleague."></textarea>
      </div>
      <div class="fbq">
        <div class="label">What did FlowMind misunderstand or miss?</div>
        <textarea class="fbtext" id="fb-missed" placeholder="Optional."></textarea>
      </div>
      <div class="fbq">
        <div class="label">What is one task you wish FlowMind had identified?</div>
        <textarea class="fbtext" id="fb-wished" placeholder="Optional."></textarea>
      </div>

      <div class="row wrap" style="gap:12px">
        <button class="btn btn-primary" id="submit-feedback" style="font-size:15px;padding:13px 26px">
          Submit feedback</button>
        <span class="small muted">Stored anonymously against ${session() ? session().code : 'this session'}.</span>
      </div>
    </div>`;
}

function screenDone() {
  return `
    ${flowHeader('done')}
    <div class="card" style="text-align:center;padding:48px 32px">
      <span class="tick" style="width:46px;height:46px;font-size:20px;margin:0 auto 18px">✓</span>
      <h1 style="margin-bottom:10px">Thank you.</h1>
      <p class="lead" style="margin:0 auto 26px;max-width:520px">
        That's the whole test. Your answers are stored anonymously against
        ${session() ? session().code : 'this session'} and will help us work out whether FlowMind
        is worth building properly.
      </p>
      <div class="row wrap" style="gap:12px;justify-content:center">
        <a class="btn btn-primary" href="#/overview">Explore what FlowMind found</a>
        <a class="btn btn-secondary" href="#/report">See the business review</a>
        <button class="btn btn-ghost" id="new-pilot-2">Start a new pilot session</button>
      </div>
    </div>`;
}

/* ============================================================== dashboard */

function scoreRing(score, band) {
  const r = 63, c = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(score, 100)) / 100 * c;
  const colour = band === 'HIGH' ? '#C7EF66' : band === 'MEDIUM' ? '#E8A33D' : '#C9DAFF';
  return `
    <div class="scorering">
      <svg width="150" height="150" viewBox="0 0 150 150">
        <circle cx="75" cy="75" r="${r}" fill="none" stroke="#EFF0F4" stroke-width="13"/>
        <circle cx="75" cy="75" r="${r}" fill="none" stroke="${colour}" stroke-width="13"
          stroke-linecap="round" stroke-dasharray="${filled} ${c - filled}" transform="rotate(-90 75 75)"/>
      </svg>
      <div class="val"><div><div class="num">${score}</div><div class="den">of 100</div></div></div>
    </div>`;
}

function bandPill(band) {
  const cls = band === 'HIGH' ? 'pill-high' : band === 'MEDIUM' ? 'pill-medium' : 'pill-low';
  return `<span class="pill ${cls}">${band} POTENTIAL</span>`;
}

const MINI_ARROW = `<svg width="20" height="14" viewBox="0 0 20 14" fill="none" style="flex:none">
  <path d="M2 7c5-6 11 6 16 0" stroke="#9FBFFF" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M14.6 4.4 18 7l-3 2.8" stroke="#9FBFFF" stroke-width="1.8"
        stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function flowInline(sequence, cyclic) {
  return `<div class="row wrap" style="gap:7px">
    ${sequence.map(FM.appChip).join(MINI_ARROW)}
    ${cyclic ? MINI_ARROW + `<span class="pill pill-live">back to ${FM.escape(sequence[0])}</span>` : ''}
  </div>`;
}

function timeBreakdown(byCategory, total) {
  if (!byCategory.length) {
    return `<p class="muted small">No work activity has been analyzed yet.</p>`;
  }
  const bar = byCategory.map(r =>
    `<span style="width:${(r.duration_ms / total * 100).toFixed(2)}%;background:${CAT_COLOR[r.category] || CAT_COLOR.Other}"></span>`).join('');
  const rows = byCategory.map(r => `
    <div class="row">
      <span class="swatch" style="background:${CAT_COLOR[r.category] || CAT_COLOR.Other}"></span>
      <span class="nm">${FM.escape(r.category)}</span>
      <span class="val">${FM.duration(r.duration_ms)}</span>
      <span class="pct">${Math.round(r.duration_ms / total * 100)}%</span>
    </div>`).join('');
  return `<div class="timebar">${bar}</div><div class="timelegend">${rows}</div>`;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

function renderOverview() {
  const s = S.summary;
  if (!s || !s.session) return offline();
  const stats = s.stats;
  const findings = s.findings;
  const top = findings[0];
  const profile = s.profile || {};

  return `
    <div class="pagehead">
      <h1>${greeting()}. Here's what FlowMind learned about your work.</h1>
      <p>Two sources of evidence: what you told me, and what I observed in the applications
         you approved.</p>
    </div>

    <div class="grid grid-4" style="margin-bottom:24px">
      <div class="stat"><div class="value">${FM.duration(stats.time_analysed_ms)}</div><div class="label">Analyzed work time</div></div>
      <div class="stat"><div class="value">${stats.applications.length}</div><div class="label">Applications observed</div></div>
      <div class="stat"><div class="value">${findings.length}</div><div class="label">Repeated workflows</div></div>
      <div class="stat"><div class="value">${findings.filter(f => f.band !== 'LOW').length}</div><div class="label">Opportunities identified</div></div>
    </div>

    <div class="grid" style="grid-template-columns:minmax(0,1fr) 320px;gap:24px;align-items:start">
      <div class="card">
        <div class="eyebrow" style="margin-bottom:14px">Where your workday goes</div>
        ${timeBreakdown(stats.by_category, stats.time_analysed_ms || 1)}
        <hr class="divider">
        <div class="row wrap" style="gap:24px">
          <div class="metric"><div class="m">${stats.transitions}</div><div class="t">application switches</div></div>
          <div class="metric"><div class="m">${stats.copy_events + stats.paste_events}</div><div class="t">copy/paste events</div></div>
          <div class="metric"><div class="m">${stats.total_events}</div><div class="t">activity events stored</div></div>
        </div>
      </div>

      <div class="card">
        <div class="row between" style="margin-bottom:12px">
          <div class="eyebrow">Work profile</div>
          <button class="btn btn-ghost btn-sm" id="edit-profile">Edit</button>
        </div>
        <div class="stack" style="gap:12px" id="profile-view">
          ${profileRow('Role', profile.role)}
          ${profileRow('Industry', profile.industry)}
          ${profileRow('Company size', profile.company_size)}
          ${profileList('Primary tools', profile.primary_tools)}
          ${profileList('Recurring tasks', profile.recurring_tasks)}
          ${profileList('Reported pain points', profile.pain_points)}
        </div>
        <p class="tiny muted" style="margin-top:12px">Built from your interview. Correct anything that's wrong.</p>
      </div>
    </div>

    ${top ? `
      <div class="eyebrow" style="margin:30px 0 12px">Top opportunity</div>
      <div class="opportunity">
        <div>
          <div class="row between wrap" style="margin-bottom:6px">
            <h2 style="font-size:23px">${FM.escape(top.title)}</h2>
            <span class="confidence ${top.confidence}">Confidence: ${top.confidence}</span>
          </div>
          <div style="margin:16px 0">${flowInline(top.sequence, top.cyclic)}</div>
          <div class="metricrow" style="margin:20px 0 22px">
            <div class="metric"><div class="m">${top.repetitions}</div><div class="t">repetitions</div></div>
            <div class="metric"><div class="m">${FM.duration(top.avg_duration_ms)}</div><div class="t">average duration</div></div>
            <div class="metric"><div class="m">${FM.duration(top.total_time_ms)}</div><div class="t">time associated</div></div>
            <div class="metric"><div class="m">${top.clipboard_events}</div><div class="t">copy/paste events</div></div>
          </div>
          <p class="muted" style="max-width:520px">${FM.escape(top.narrative.possible_issue)}</p>
          <div class="row wrap" style="gap:10px;margin-top:20px">
            <a class="btn btn-primary" href="#/consultant">Ask FlowMind about this</a>
            <a class="btn btn-secondary" href="#/report">Business review</a>
          </div>
        </div>
        <div class="scoreblock">
          ${scoreRing(top.score, top.band)}
          <div class="eyebrow">Opportunity score</div>
        </div>
      </div>` : `
      <div class="empty" style="margin-top:30px">
        <h3>I haven't seen enough repeated activity yet</h3>
        <p>I won't invent a pattern. Keep working normally, or repeat a typical task a few
           more times, and I'll tell you as soon as I have something worth investigating.</p>
        <a class="btn btn-primary" href="#/step/observe">Continue the analysis</a>
      </div>`}`;
}

function profileRow(label, value) {
  return `<div><div class="eyebrow" style="margin-bottom:2px">${label}</div>
    <div style="font-size:14.5px">${value ? FM.escape(value) : '<span class="muted">Not captured</span>'}</div></div>`;
}

function profileList(label, items) {
  const list = items && items.length
    ? `<ul style="margin:4px 0 0;padding-left:18px;font-size:14px">${items.map(i => `<li>${FM.escape(i)}</li>`).join('')}</ul>`
    : '<div class="muted small">Not captured</div>';
  return `<div><div class="eyebrow" style="margin-bottom:2px">${label}</div>${list}</div>`;
}

function renderConsultantPage(data, suggestions) {
  const s = S.summary;
  const findings = (s && s.findings) || [];
  return `
    <div class="pagehead">
      <h1>Consultant</h1>
      <p>Ask me anything about what I found. If I don't have the evidence to answer, I'll say so
         and ask you instead.</p>
    </div>

    <div class="grid" style="grid-template-columns:minmax(0,1fr) 340px;gap:24px;align-items:start">
      <div class="card">
        <div class="chat" id="chat">
          ${data.thread.length
            ? data.thread.map(m => bubble(m.role, m.text)).join('')
            : bubble('consultant', findings.length
                ? `I've analyzed your approved work activity and your interview. The strongest opportunity is ${findings[0].title} — ${findings[0].score}/100, confidence ${findings[0].confidence}. Ask me why, or what to do about it.`
                : "I haven't analyzed any work activity yet. Start a work analysis and I'll have something to tell you.")}
        </div>
        <div class="composer">
          <textarea id="chat-input" placeholder="Ask FlowMind…"></textarea>
          <button class="btn btn-primary" id="chat-send" style="padding:14px 22px">Ask</button>
        </div>
        <div class="suggestions">
          ${data.suggested.map(q => `<button data-q="${FM.escape(q)}">${FM.escape(q)}</button>`).join('')}
        </div>
      </div>

      <div class="stack" style="gap:16px">
        ${findings.map(f => `
          <div class="card">
            <div class="row between wrap" style="margin-bottom:10px">
              <h3 style="font-size:16px">${FM.escape(f.title)}</h3>
              ${bandPill(f.band)}
            </div>
            ${flowInline(f.sequence, f.cyclic)}
            <div class="metricrow" style="margin:14px 0">
              <div class="metric"><div class="m">${f.score}</div><div class="t">score</div></div>
              <div class="metric"><div class="m">${f.repetitions}</div><div class="t">repetitions</div></div>
              <div class="metric"><div class="m">${FM.duration(f.total_time_ms)}</div><div class="t">time</div></div>
            </div>
            <span class="confidence ${f.confidence}">Confidence: ${f.confidence}</span>
            <p class="small muted" style="margin-top:10px">${FM.escape(f.confidence_reason)}</p>
            ${f.open_question ? `<p class="small" style="margin-top:10px"><b>FlowMind asks:</b>
              ${FM.escape(f.open_question)}</p>` : ''}
            <a class="btn btn-secondary btn-sm" style="margin-top:12px" href="#/finding/${f.id}">See the evidence</a>
          </div>`).join('') || (suggestions && suggestions.length ? '' : `<div class="empty"><h3>No findings yet</h3>
            <p>Run a work analysis and they'll appear here.</p>
            <a class="btn btn-primary" href="#/step/observe">Go to the analysis</a></div>`)}
        ${suggestionsBlock(suggestions,
          findings.length
            ? 'From your interview, independently of what I measured.'
            : 'From your interview. I have not observed your work yet.')}
      </div>
    </div>`;
}

async function renderFindingPage(id) {
  const f = await FM.safeApi('/api/findings/' + encodeURIComponent(id), {}, null);
  if (!f) return `<div class="empty"><h3>That finding is no longer available</h3>
    <p>It may have been removed when the activity data was reset.</p>
    <a class="btn btn-primary" href="#/consultant">Back to the consultant</a></div>`;
  return `<a class="backlink" href="#/consultant">← Consultant</a>` + screenFinding(f, false);
}

function renderActivity(data) {
  const s = S.summary;
  if (!s || !s.session) return offline();
  const stats = s.stats;
  return `
    <div class="pagehead">
      <h1>Work activity</h1>
      <p>Everything FlowMind recorded, in order. Every conclusion on the other pages is derived
         from exactly this list — nothing else.</p>
    </div>

    <div class="grid grid-2" style="margin-bottom:24px;align-items:start">
      <div class="card">
        <div class="eyebrow" style="margin-bottom:14px">Time by application</div>
        ${stats.by_application.length ? `<div class="timelegend">${stats.by_application.map(r => `
          <div class="row">
            <span class="swatch" style="background:${CAT_COLOR[r.category] || CAT_COLOR.Other}"></span>
            <span class="nm">${FM.escape(r.application)}</span>
            <span class="val">${FM.duration(r.duration_ms)}</span>
            <span class="pct">${Math.round(r.duration_ms / (stats.time_analysed_ms || 1) * 100)}%</span>
          </div>`).join('')}</div>` : '<p class="muted small">Nothing recorded yet.</p>'}
      </div>
      <div class="card">
        <div class="eyebrow" style="margin-bottom:14px">Totals</div>
        <div class="row wrap" style="gap:24px">
          <div class="metric"><div class="m">${FM.duration(stats.time_analysed_ms)}</div><div class="t">analyzed</div></div>
          <div class="metric"><div class="m">${stats.transitions}</div><div class="t">switches</div></div>
          <div class="metric"><div class="m">${stats.copy_events}</div><div class="t">copy events</div></div>
          <div class="metric"><div class="m">${stats.paste_events}</div><div class="t">paste events</div></div>
        </div>
        <p class="tiny muted" style="margin-top:16px">
          Copy and paste rows record only that the event happened and in which application.
          Clipboard contents are never read or stored.
        </p>
      </div>
    </div>

    <div class="card"><div id="activity-body"><div class="loading">Loading activity…</div></div></div>`;
}

async function fillActivity() {
  const data = await FM.safeApi('/api/activity', {}, { events: [] });
  const box = el('activity-body');
  if (!box) return;
  if (!data.events.length) {
    box.innerHTML = `<p class="muted">No activity recorded yet.
      <a href="#/step/observe">Run a work analysis</a> and it will appear here.</p>`;
    return;
  }
  const groups = {};
  data.events.forEach(e => { (groups[e.started_at.slice(0, 10)] ||= []).push(e); });

  box.innerHTML = Object.entries(groups).sort().reverse().map(([day, events]) => `
    <div class="tl-group">
      <h4>${FM.day(day + 'T00:00:00Z')}
        ${events.some(e => e.source === 'simulated')
          ? '<span class="pill pill-sim" style="margin-left:8px">includes simulated demo activity</span>' : ''}</h4>
      <div class="timeline">
        ${events.map(e => e.type === 'app_visit' ? `
          <div class="tl-item">
            <span class="node"></span>
            <span class="time">${FM.clockSeconds(e.started_at)}</span>
            ${FM.appChip(e.application)}
            ${e.source === 'simulated' ? '<span class="pill pill-sim tiny">simulated</span>' : ''}
            <span class="dur">${FM.duration(e.duration_ms)}</span>
          </div>` : `
          <div class="tl-item mark">
            <span class="node"></span>
            <span class="time">${FM.clockSeconds(e.started_at)}</span>
            <span class="small muted">${e.type === 'copy' ? 'Copy' : 'Paste'} event in ${FM.escape(e.application)}</span>
          </div>`).join('')}
      </div>
    </div>`).join('') + `<p class="tiny muted">Showing the ${data.count} most recent events.</p>`;
}

function renderPrivacy(permissions) {
  const paused = S.state && S.state.monitoring_paused;
  return `
    <div class="pagehead">
      <h1>Your work data stays under your control.</h1>
      <p>FlowMind analyzes processes, not people. Nothing here is a measure of your performance.</p>
    </div>

    <div class="grid grid-2">
      <div class="privacy-col">
        <h3><span class="tick">✓</span> What FlowMind can see</h3>
        <ul class="plist">
          <li><span class="tick">✓</span> Which approved application is active</li>
          <li><span class="tick">✓</span> Transitions between approved applications</li>
          <li><span class="tick">✓</span> Timestamps and approximate duration</li>
          <li><span class="tick">✓</span> Counts of copy and paste events</li>
          <li><span class="tick">✓</span> What you told it in the interview and chat</li>
        </ul>
      </div>
      <div class="privacy-col">
        <h3><span class="cross">✕</span> What FlowMind cannot see</h3>
        <ul class="plist">
          <li><span class="cross">✕</span> What you type</li>
          <li><span class="cross">✕</span> What you copy or paste</li>
          <li><span class="cross">✕</span> Email or message contents</li>
          <li><span class="cross">✕</span> Passwords or payment information</li>
          <li><span class="cross">✕</span> Document or form contents</li>
          <li><span class="cross">✕</span> Any site you have not approved</li>
        </ul>
      </div>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="eyebrow" style="margin-bottom:12px">App permissions</div>
      <div class="applist">
        ${permissions.map(p => `
          <div class="approw">
            <span class="appicon ${p.category}">${FM.initials(p.app_label)}</span>
            <div class="meta">
              <div class="nm">${FM.escape(p.app_label)}</div>
              <div class="dm">${FM.escape(p.product)} · ${FM.escape(p.domain)}${p.path_prefix || ''}</div>
            </div>
            <span class="toggle-label ${p.allowed ? 'on' : 'off'}">${p.allowed ? 'Allowed' : 'Not allowed'}</span>
            <button class="toggle ${p.allowed ? 'on' : ''}" data-perm="${p.id}"></button>
          </div>`).join('')}
      </div>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="eyebrow" style="margin-bottom:12px">How this is enforced</div>
      <ul class="plist">
        <li><span class="tick">1</span><div>The extension classifies a tab only if its domain is on
          your approved list. For every other site it does not look at the address at all.</div></li>
        <li><span class="tick">2</span><div>Recording happens only while a work analysis is running.
          Outside that window the extension records nothing.</div></li>
        <li><span class="tick">3</span><div>The copy and paste listeners record that an event
          happened and in which application. They never read clipboard data.</div></li>
        <li><span class="tick">4</span><div>The activity tables have no column that could hold page
          text, typed characters, form values or URLs, and the ingest endpoint rejects any event
          carrying a field other than the ones listed above.</div></li>
      </ul>
    </div>

    <div class="card" style="margin-top:24px">
      <div class="eyebrow" style="margin-bottom:12px">Your controls</div>
      <div class="row wrap" style="gap:12px">
        <button class="btn btn-secondary" id="toggle-monitoring">${paused ? 'Resume monitoring' : 'Pause monitoring'}</button>
        <button class="btn btn-secondary" id="delete-activity">Delete my activity</button>
        <button class="btn btn-secondary" id="delete-memory">Delete consultant memory</button>
      </div>
      <p class="small muted" style="margin-top:12px">
        Deleting activity removes every recorded event and finding for this session. Deleting
        consultant memory also erases the interview, the chat and your work profile. Neither can
        be undone.
      </p>
    </div>`;
}

function renderReport(report) {
  const total = report.analysed_time_ms || 1;
  return `
    <div class="row between wrap no-print" style="margin-bottom:18px">
      <a class="backlink" href="#/overview">← Overview</a>
      <button class="btn btn-secondary btn-sm" onclick="window.print()">Print / save as PDF</button>
    </div>
    <div class="reportsheet">
      <div class="row between wrap" style="margin-bottom:26px">
        <div>
          <div class="eyebrow">FlowMind business review</div>
          <h1 style="margin-top:6px">${FM.escape(report.session.role || 'Work analysis')}</h1>
          <p class="small muted">${FM.escape(report.session.industry || '')}
            ${report.session.company_size ? '· ' + FM.escape(report.session.company_size) + ' people' : ''}
            · ${FM.escape(report.session.code)}</p>
        </div>
        <span class="mark" style="width:44px;height:44px;border-radius:14px;background:var(--blue);display:grid;place-items:center">${MARK}</span>
      </div>

      <h2>Executive summary</h2>
      <p style="font-size:16px">${FM.escape(report.executive_summary)}</p>

      <h2>How work time is distributed</h2>
      ${timeBreakdown(report.time_distribution, total)}

      <h2>Top workflow friction</h2>
      ${report.top_opportunities.length ? report.top_opportunities.map((f, i) => `
        <div class="card flat" style="border-radius:16px;margin-bottom:12px">
          <div class="row between wrap" style="margin-bottom:8px">
            <b style="font-size:16px">${i + 1}. ${FM.escape(f.title)}</b>
            <span class="row" style="gap:8px">${bandPill(f.band)}
              <span class="confidence ${f.confidence}">${f.confidence}</span></span>
          </div>
          ${flowInline(f.sequence, f.cyclic)}
          <div class="metricrow" style="margin:14px 0 10px">
            <div class="metric"><div class="m">${f.score}</div><div class="t">score</div></div>
            <div class="metric"><div class="m">${f.repetitions}</div><div class="t">repetitions</div></div>
            <div class="metric"><div class="m">${FM.duration(f.total_time_ms)}</div><div class="t">time associated</div></div>
            <div class="metric"><div class="m">${f.copy_events + f.paste_events}</div><div class="t">copy/paste</div></div>
          </div>
          <p class="small">${FM.escape(f.narrative.possible_issue)}</p>
        </div>`).join('') : '<p class="muted">No repeated workflow was identified with enough evidence.</p>'}

      <h2>Evidence</h2>
      ${report.top_opportunities.length ? evidenceBlock(report.top_opportunities[0])
        : '<p class="muted small">Nothing to evidence yet.</p>'}

      ${(report.interview_suggestions || []).length ? `
        <h2>What you told us could be automated</h2>
        <p class="small muted" style="margin-bottom:14px">Reported by the participant during the
          interview, independent of what FlowMind measured.</p>
        ${report.interview_suggestions.map(suggestionCard).join('')}` : ''}

      <h2>Recommended next steps</h2>
      ${report.next_steps.length
        ? `<ol style="padding-left:20px">${report.next_steps.map(s => `<li style="margin-bottom:8px">${FM.escape(s)}</li>`).join('')}</ol>`
        : '<p class="muted small">FlowMind is not recommending action yet — the evidence is too thin.</p>'}

      <hr class="divider">
      <p class="tiny muted">
        Generated ${FM.day(report.generated_at)} ${FM.clock(report.generated_at)} from
        ${FM.duration(report.analysed_time_ms)} of approved work-activity metadata and this
        participant's interview. Findings describe possibilities to investigate, not confirmed
        facts: FlowMind observes metadata, never content.
      </p>
      <div class="row no-print" style="margin-top:18px">
        <a class="btn btn-primary" href="#/consultant">Ask FlowMind about this report</a>
      </div>
    </div>`;
}

function offline() {
  return `<div class="empty"><h3>FlowMind service is not reachable</h3>
    <p>Start the backend and this page will recover on its own.</p>
    <code class="small muted">python -m uvicorn server.app:app --port 8000</code></div>`;
}

/* ================================================================== router */

// hashchange and popstate can both fire for one navigation. Without this guard
// two route() calls interleave and the older one repaints the screen you just
// left — which looks exactly like "Back doesn't work".
let routing = false;
let routeQueued = false;
// True only when the url changed because the participant navigated (Back /
// Forward). A route() that follows an action must NOT read the stale url as a
// request to rewind — that would undo the step just completed.
let fromNavigation = false;

async function route() {
  if (routing) { routeQueued = true; return; }
  routing = true;
  try {
    await doRoute();
  } finally {
    routing = false;
    if (routeQueued) { routeQueued = false; route(); }
  }
}

async function doRoute() {
  const navigated = fromNavigation;
  fromNavigation = false;
  clearTimers();
  await loadState();

  if (!S.state) { renderChrome(false); view().innerHTML = offline(); return; }

  const hash = location.hash.replace(/^#\/?/, '');
  const [page, arg] = hash.split('/');
  const reached = session() && DASHBOARD_STAGES.includes(stage());
  const wantsDashboard = reached && page && page !== 'flow' && page !== 'step';

  if (wantsDashboard) {
    lastFlowStage = null;
    await loadSummary();
    renderChrome(true);
    if (page === 'consultant') {
      const data = await FM.safeApi('/api/consultant', {}, { thread: [], suggested: [] });
      const sug = await FM.safeApi('/api/suggestions', {}, { suggestions: [] });
      view().innerHTML = renderConsultantPage(data, sug.suggestions);
      wireConsultant();
    } else if (page === 'finding') {
      view().innerHTML = await renderFindingPage(arg);
      wireFinding(true);
    } else if (page === 'activity') {
      view().innerHTML = renderActivity();
      fillActivity();
    } else if (page === 'privacy') {
      const p = await FM.safeApi('/api/permissions', {}, { permissions: [] });
      view().innerHTML = renderPrivacy(p.permissions);
      wirePrivacy();
    } else if (page === 'report') {
      const r = await FM.safeApi('/api/report', {}, null);
      view().innerHTML = r ? renderReport(r) : offline();
    } else {
      view().innerHTML = renderOverview();
      wireOverview();
    }
    renderChrome(true);
    window.scrollTo({ top: 0 });
    return;
  }

  // ---- guided flow
  renderChrome(false);
  let st = session() ? stage() : 'welcome';

  // The url names an earlier step than the server is on AND the participant got
  // here by navigating: they pressed Back. Actually rewind, then render it.
  // No step in the url after a navigation means they went back past the first
  // step, which is the welcome screen.
  const wanted = hashStep() || (navigated ? 'welcome' : null);
  if (navigated && wanted && wanted !== st && stepIndex(wanted) < stepIndex(st)) {
    const moved = await FM.safeApi('/api/pilot/goto', {
      method: 'POST', body: JSON.stringify({ stage: wanted }),
    }, null);
    if (moved) {
      await loadState();
      st = session() ? stage() : 'welcome';
    } else {
      // Older server without /api/pilot/goto — step back one at a time instead.
      for (let i = 0; i < FLOW_ORDER.length && stepIndex(st) > stepIndex(wanted); i++) {
        const back = await FM.safeApi('/api/pilot/back', { method: 'POST' }, null);
        if (!back) break;
        await loadState();
        st = session() ? stage() : 'welcome';
      }
    }
  }
  if (st === 'welcome') {
    history.replaceState({ step: 'welcome' }, '', location.pathname);
    stepDepth = 0;
  } else {
    syncStepHash(st);
  }

  if ((!session() || st === 'welcome') && IS_PILOT_ENTRY) {
    view().innerHTML = screenPilotEntry();
    el('start-pilot-run').onclick = async () => {
      const r = await FM.safeApi('/api/pilot/start', {
        method: 'POST', body: JSON.stringify({ session_type: 'REAL_PILOT' }),
      }, null);
      if (!r) return FM.toast('Could not reach the FlowMind service');
      location.replace('/#/step/consent');       // continue on the normal app path
    };
  } else if (!session() || st === 'welcome') {
    view().innerHTML = screenWelcome();
    el('start-pilot').onclick = () => startPilot('REAL_PILOT');
    el('start-demo').onclick = () => startPilot('DEMO');
    el('how-it-works').onclick = (e) => {
      e.preventDefault();
      el('how-panel').classList.toggle('hidden');
    };
  } else if (st === 'consent') {
    view().innerHTML = screenConsent();
    el('allow').onclick = async () => { await FM.safeApi('/api/pilot/consent', { method: 'POST' }, null); route(); };
    el('choose').onclick = async () => {
      await FM.safeApi('/api/pilot/consent', { method: 'POST' }, null);
      S.draft.jumpPermissions = true;
      route();
    };
  } else if (st === 'context') {
    view().innerHTML = screenContext();
    wireContext();
  } else if (st === 'interview') {
    const data = await FM.safeApi('/api/interview', {}, { transcript: [], asked: 0 });
    view().innerHTML = screenInterview(data);
    wireInterview();
    // Resuming after a refresh or a step back: if the interview was already
    // closed, show its conclusion again instead of asking for more answers.
    if (session() && session().interview_completed) {
      const s = await FM.safeApi('/api/suggestions', {}, { suggestions: [] });
      closeInterview({ suggestions: s.suggestions || [] }, true);
    }
  } else if (st === 'permissions') {
    const p = await FM.safeApi('/api/permissions', {}, { permissions: [] });
    const prof = await FM.safeApi('/api/profile', {}, { profile: null });
    view().innerHTML = screenPermissions(p.permissions, prof.profile);
    wirePermissions();
  } else if (st === 'ready') {
    const prof = await FM.safeApi('/api/profile', {}, { profile: null });
    view().innerHTML = screenReady(prof.profile);
    el('begin-analysis').onclick = async () => {
      const r = await FM.safeApi('/api/analysis/start', { method: 'POST' }, null);
      if (!r) return FM.toast('Could not start the analysis');
      route();
    };
  } else if (st === 'observe') {
    view().innerHTML = screenObserve();
    wireObserve();
  } else if (st === 'aha') {
    await loadSummary();
    const top = (S.summary.findings || [])[0];
    if (!top) { view().innerHTML = screenInsufficient(); wireInsufficient(); }
    else {
      view().innerHTML = screenAha(top);
      el('see-analysis').onclick = async () => {
        await FM.safeApi('/api/pilot/stage', {
          method: 'POST', body: JSON.stringify({ text: 'finding' }) }, null);
        route();
      };
      el('not-accurate').onclick = async () => {
        await FM.safeApi('/api/pilot/stage', {
          method: 'POST', body: JSON.stringify({ text: 'finding' }) }, null);
        await FM.safeApi('/api/pilot/stage', {
          method: 'POST', body: JSON.stringify({ text: 'feedback' }) }, null);
        route();
      };
    }
  } else if (st === 'finding' || st === 'feedback' || st === 'done') {
    await loadSummary();
    if (st === 'done') {
      view().innerHTML = screenDone();
      el('new-pilot-2').onclick = () => startPilot('REAL_PILOT');
    } else if (st === 'feedback') {
      view().innerHTML = screenFeedback((S.summary.findings || [])[0]);
      wireFeedback();
    } else {
      const top = (S.summary.findings || [])[0];
      if (!top) { view().innerHTML = screenInsufficient(); wireInsufficient(); }
      else {
        const full = await FM.safeApi('/api/findings/' + top.id, {}, top);
        view().innerHTML = screenFinding(full);
        wireFinding(false);
      }
    }
  }
  const backBtn = el('flow-back');
  if (backBtn) backBtn.onclick = goBack;
  window.scrollTo({ top: 0 });
}

/* ================================================================== wiring */

async function startPilot(type) {
  const r = await FM.safeApi('/api/pilot/start', {
    method: 'POST', body: JSON.stringify({ session_type: type }),
  }, null);
  if (!r) return FM.toast('Could not reach the FlowMind service');
  S.draft = {};
  stepDepth = 1;
  history.pushState({ step: 'consent' }, '', '#/step/consent');
  route();
}

function wireContext() {
  document.querySelectorAll('#sizes .option').forEach(b => b.onclick = () => {
    S.draft.company_size = b.dataset.size;
    document.querySelectorAll('#sizes .option').forEach(x => x.classList.remove('selected'));
    b.classList.add('selected');
  });
  document.querySelectorAll('#industries .pick').forEach(b => b.onclick = () => {
    S.draft.industry = b.dataset.industry;
    document.querySelectorAll('#industries .pick').forEach(x => x.classList.remove('selected'));
    b.classList.add('selected');
  });
  el('role').focus();
  el('context-next').onclick = async () => {
    const role = el('role').value.trim();
    const industry = S.draft.industry || '';
    S.draft.role = role;
    if (!role) { FM.toast('Your role helps me interpret what I observe'); return el('role').focus(); }
    if (!industry) return FM.toast('Pick the kind of business you work in');
    if (!S.draft.company_size) return FM.toast('Pick a company size');
    const r = await FM.safeApi('/api/pilot/context', {
      method: 'POST',
      body: JSON.stringify({ industry, role, company_size: S.draft.company_size }),
    }, null);
    if (!r) return FM.toast('Could not save that');
    route();
  };
}

function wireInterview() {
  const input = el('answer');
  const send = el('send');
  input.focus();

  async function submit() {
    const text = input.value.trim();
    if (!text) return;
    send.disabled = true;
    el('chat').insertAdjacentHTML('beforeend', bubble('employee', text));
    el('chat').insertAdjacentHTML('beforeend',
      `<div class="bubble typing" id="typing"><span class="av">${MARK}</span>
       <div class="body">FlowMind is thinking…</div></div>`);
    input.value = '';
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });

    const r = await FM.safeApi('/api/interview', { method: 'POST', body: JSON.stringify({ text }) }, null);
    const typing = el('typing'); if (typing) typing.remove();
    send.disabled = false;
    if (!r) { FM.toast('Could not reach FlowMind'); return; }
    if (r.complete) { closeInterview(r); return; }
    const answered = r.transcript.filter(m => m.role === 'employee').length;
    if (el('q-counter')) el('q-counter').textContent = `Question ${answered + 1} of about 6`;
    if (el('learned')) el('learned').innerHTML = learnedChips(r.profile);
    if (r.acknowledgement) el('chat').insertAdjacentHTML('beforeend', bubble('consultant', r.acknowledgement));
    if (r.question) el('chat').insertAdjacentHTML('beforeend', bubble('consultant', r.question));
    input.focus();
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  }

  send.onclick = submit;
  input.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };
  if (el('skip')) el('skip').onclick = async () => {
    const r = await FM.safeApi('/api/interview/finish', { method: 'POST' }, null);
    if (!r) return FM.toast('Could not reach FlowMind');
    closeInterview(r);
  };
}

/** The consultant signs off the interview with what it would look at, before
 *  anything has been observed. Everything here is labelled REPORTED. */
function closeInterview(result, resuming) {
  const suggestions = result.suggestions || [];
  const composer = el('composer-wrap');
  // When resuming a finished interview we leave the composer in place, so a
  // participant who remembers one more thing can still say it.
  if (composer && !resuming) composer.remove();

  el('chat').insertAdjacentHTML('beforeend', bubble('consultant',
    resuming
      ? "We already covered this — here's where we got to. Add anything else, or continue."
      : suggestions.length
        ? "Thanks — that's enough context. Based on what you've told me, here's what I'd look at first."
        : "Thanks. I have enough context to start looking for opportunities."));

  el('interview-close').innerHTML = `
    ${suggestionsBlock(suggestions,
      'These come from our conversation only — I have not observed your work yet. '
      + 'Next I will watch the approved applications and check whether what you described '
      + 'actually shows up in practice.')}
    <div class="row wrap" style="gap:12px;margin-top:18px">
      <button class="btn btn-primary" id="after-interview" style="font-size:15px;padding:13px 26px">
        Continue →</button>
      <span class="small muted">Next: choose what FlowMind may observe.</span>
    </div>`;
  el('after-interview').onclick = async () => {
    await FM.safeApi('/api/pilot/stage',
      { method: 'POST', body: JSON.stringify({ text: 'permissions' }) }, null);
    route();
  };
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

function wireToggles() {
  document.querySelectorAll('.toggle[data-perm]').forEach(btn => btn.onclick = async () => {
    const on = btn.classList.contains('on');
    const r = await FM.safeApi(`/api/permissions/${btn.dataset.perm}`, {
      method: 'POST', body: JSON.stringify({ allowed: !on }),
    }, null);
    if (!r) return FM.toast('Could not update that permission');
    btn.classList.toggle('on', !on);
    const label = btn.previousElementSibling;
    label.textContent = !on ? 'Allowed' : 'Not allowed';
    label.className = `toggle-label ${!on ? 'on' : 'off'}`;
  });
}

function wirePermissions() {
  wireToggles();
  el('add-domain').onclick = async () => {
    const domain = el('new-domain').value.trim();
    const label = el('new-label').value.trim();
    if (!domain) return FM.toast('Enter a website domain');
    const r = await FM.safeApi('/api/permissions', {
      method: 'POST',
      body: JSON.stringify({ domain, app_label: label || domain, product: 'Custom',
                             category: el('new-category').value }),
    }, null);
    if (!r) return FM.toast('Could not add that site');
    FM.toast('Added and approved');
    route();
  };
  el('perms-next').onclick = async () => {
    const r = await FM.safeApi('/api/pilot/stage', {
      method: 'POST', body: JSON.stringify({ text: 'ready' }),
    }, null);
    if (!r) return FM.toast('Could not continue');
    route();
  };
}

function wireObserve() {
  // If the extension is not running, say so instead of leaving the participant
  // watching a counter that will never move.
  let warned = false;
  function checkExtension(events) {
    const live = document.documentElement.dataset.flowmindExtension === 'active';
    const box = el('no-extension');
    if (!box) return;
    box.classList.toggle('hidden', live || events > 0);
    if (!live && !events && !warned) {
      warned = true;
      reportFault('extension_missing', 'No FlowMind extension detected during analysis');
    }
  }

  async function tick() {
    const s = await FM.safeApi('/api/analysis/status', {}, null);
    if (!s || !el('obs-timer')) return;
    const mm = String(Math.floor(s.elapsed_seconds / 60)).padStart(2, '0');
    const ss = String(s.elapsed_seconds % 60).padStart(2, '0');
    el('obs-timer').textContent = `${mm}:${ss}`;
    el('obs-events').textContent = s.events;
    el('obs-apps').textContent = s.applications.length;
    el('obs-switches').textContent = s.switches;
    el('obs-reps').textContent = s.patterns.length;
    el('obs-state').textContent = s.paused
      ? 'Monitoring paused' : 'Analyzing approved workflow metadata';
    el('obs-current').textContent = s.applications.length
      ? `Observed so far: ${s.applications.join(', ')}`
      : 'Waiting for activity in an approved application…';
    el('obs-approved').innerHTML = (s.approved_apps || []).map(FM.appChip).join('');
    checkExtension(s.events);
  }
  tick();
  S.poll = setInterval(tick, 2000);

  el('finish').onclick = async () => {
    const r = await FM.safeApi('/api/analysis/finish', { method: 'POST' }, null);
    if (!r) return FM.toast('Could not finish the analysis');
    if (!r.sufficient) {
      clearTimers();
      view().innerHTML = screenInsufficient(r.message);
      wireInsufficient();
      return;
    }
    stepDepth += 1;
    history.pushState({ step: 'aha' }, '', '#/step/aha');
    route();
  };
  el('pause').onclick = async () => {
    const paused = !(S.state && S.state.monitoring_paused);
    await FM.safeApi('/api/monitoring', { method: 'POST', body: JSON.stringify({ paused }) }, null);
    await loadState();
    el('pause').textContent = paused ? 'Resume' : 'Pause';
    FM.toast(paused ? 'Monitoring paused' : 'Monitoring resumed');
  };
}

function wireInsufficient() {
  el('continue-analysis').onclick = async () => {
    await FM.safeApi('/api/analysis/continue', { method: 'POST' }, null);
    route();
  };
  el('gen-demo').onclick = async () => {
    const r = await FM.safeApi('/api/demo/generate', { method: 'POST' }, null);
    if (!r) return FM.toast('Could not generate demo activity');
    FM.toast(`Generated ${r.inserted} activity events`);
    route();
  };
}

function wireFinding(inDashboard) {
  if (el('why-score')) el('why-score').onclick = () =>
    el('score-detail').classList.toggle('hidden');

  if (el('send-open')) el('send-open').onclick = async () => {
    const text = el('answer-open').value.trim();
    if (!text) return FM.toast('Type an answer first');
    el('send-open').disabled = true;
    const r = await FM.safeApi('/api/consultant', { method: 'POST', body: JSON.stringify({ text }) }, null);
    el('send-open').disabled = false;
    if (!r) return FM.toast('Could not reach FlowMind');
    const changed = (r.updated_findings || [])[0];
    FM.toast(changed
      ? `Updated: ${changed.previous_score} → ${changed.score}, confidence ${changed.confidence}`
      : 'Thanks — noted');
    route();
  };

  if (el('to-feedback')) el('to-feedback').onclick = async () => {
    await FM.safeApi('/api/pilot/stage', { method: 'POST', body: JSON.stringify({ text: 'feedback' }) }, null);
    route();
  };
  if (el('more-analysis')) el('more-analysis').onclick = async () => {
    await FM.safeApi('/api/analysis/continue', { method: 'POST' }, null);
    route();
  };
}

function wireFeedback() {
  const answers = {};
  document.querySelectorAll('.choice').forEach(btn => btn.onclick = () => {
    const q = btn.dataset.q;
    answers[q] = btn.dataset.v;
    document.querySelectorAll(`.choice[data-q="${q}"]`).forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
  });

  el('submit-feedback').onclick = async () => {
    const payload = {
      ...answers,
      missed_or_wrong: el('fb-missed').value.trim() || null,
      wished_task: el('fb-wished').value.trim() || null,
      permission_reason: el('fb-reason').value.trim() || null,
      product_understanding_text: el('fb-understanding').value.trim() || null,
      investigate_reason: el('fb-investigate-why').value.trim() || null,
    };
    if (!Object.keys(answers).length && !payload.missed_or_wrong
        && !payload.product_understanding_text) {
      return FM.toast('Answer at least one question');
    }
    el('submit-feedback').disabled = true;
    const r = await FM.safeApi('/api/feedback', { method: 'POST', body: JSON.stringify(payload) }, null);
    el('submit-feedback').disabled = false;
    if (!r) return FM.toast('Could not save your feedback');
    route();
  };
}

function wireConsultant() {
  const input = el('chat-input');
  const send = el('chat-send');

  async function ask(text) {
    if (!text.trim()) return;
    send.disabled = true;
    el('chat').insertAdjacentHTML('beforeend', bubble('employee', text));
    el('chat').insertAdjacentHTML('beforeend',
      `<div class="bubble typing" id="typing"><span class="av">${MARK}</span>
       <div class="body">FlowMind is thinking…</div></div>`);
    input.value = '';
    const r = await FM.safeApi('/api/consultant', { method: 'POST', body: JSON.stringify({ text }) }, null);
    const typing = el('typing'); if (typing) typing.remove();
    send.disabled = false;
    if (!r) { FM.toast('Could not reach FlowMind'); return; }
    el('chat').insertAdjacentHTML('beforeend', bubble('consultant', r.reply));
    const changed = (r.updated_findings || [])[0];
    if (changed) FM.toast(`${changed.title}: ${changed.previous_score} → ${changed.score}, confidence ${changed.confidence}`);
    el('chat').lastElementChild.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }

  send.onclick = () => ask(input.value);
  input.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(input.value); } };
  document.querySelectorAll('.suggestions button').forEach(b => b.onclick = () => ask(b.dataset.q));
}

function wireOverview() {
  if (!el('edit-profile')) return;
  el('edit-profile').onclick = () => {
    const p = (S.summary && S.summary.profile) || {};
    const box = el('profile-view');
    box.innerHTML = `
      <div class="field-row"><label>Role</label><input class="input" id="p-role" value="${FM.escape(p.role || '')}"></div>
      <div class="field-row"><label>Industry</label><input class="input" id="p-industry" value="${FM.escape(p.industry || '')}"></div>
      <div class="field-row"><label>Primary tools (comma separated)</label>
        <input class="input" id="p-tools" value="${FM.escape((p.primary_tools || []).join(', '))}"></div>
      <div class="field-row"><label>Recurring tasks (one per line)</label>
        <textarea class="fbtext" id="p-tasks">${FM.escape((p.recurring_tasks || []).join('\n'))}</textarea></div>
      <div class="field-row"><label>Pain points (one per line)</label>
        <textarea class="fbtext" id="p-pains">${FM.escape((p.pain_points || []).join('\n'))}</textarea></div>
      <button class="btn btn-primary btn-sm" id="save-profile">Save profile</button>`;
    el('save-profile').onclick = async () => {
      const split = (v, sep) => v.split(sep).map(s => s.trim()).filter(Boolean);
      const r = await FM.safeApi('/api/profile', {
        method: 'PUT',
        body: JSON.stringify({
          role: el('p-role').value.trim(),
          industry: el('p-industry').value.trim(),
          company_size: p.company_size || '',
          primary_tools: split(el('p-tools').value, ','),
          recurring_tasks: split(el('p-tasks').value, '\n'),
          pain_points: split(el('p-pains').value, '\n'),
        }),
      }, null);
      if (!r) return FM.toast('Could not save the profile');
      FM.toast('Work profile updated');
      route();
    };
  };
}

function wirePrivacy() {
  wireToggles();
  el('toggle-monitoring').onclick = async () => {
    const paused = !(S.state && S.state.monitoring_paused);
    await FM.safeApi('/api/monitoring', { method: 'POST', body: JSON.stringify({ paused }) }, null);
    FM.toast(paused ? 'Monitoring paused' : 'Monitoring resumed');
    route();
  };
  el('delete-activity').onclick = async () => {
    await FM.safeApi('/api/privacy/delete-activity', { method: 'POST' }, null);
    FM.toast('Activity data deleted');
    route();
  };
  el('delete-memory').onclick = async () => {
    await FM.safeApi('/api/privacy/delete-memory', { method: 'POST' }, null);
    FM.toast('Consultant memory deleted');
    history.pushState({ step: 'context' }, '', '#/step/context');
    route();
  };
}

el('new-pilot').onclick = () => startPilot('REAL_PILOT');

/* ---------------------------------------------------------------- help ---
   A pilot participant who gets stuck should never have to guess. */
const HELP = `
  <div class="card" style="max-width:520px">
    <div class="row between" style="margin-bottom:12px">
      <h3>Need help?</h3>
      <button class="btn btn-ghost btn-sm" id="help-close">Close</button>
    </div>
    <div class="qa"><div class="q">Nothing is being recorded</div><div class="a" style="font-size:14px">
      Recording only runs during a work analysis. Check the status in the sidebar — it should
      say "Analyzing work". If it says the service is offline, the FlowMind window was closed.</div></div>
    <div class="qa"><div class="q">I want to stop or delete everything</div><div class="a" style="font-size:14px">
      Privacy → Pause monitoring, Delete my activity, or Delete consultant memory. All three
      take effect immediately.</div></div>
    <div class="qa"><div class="q">I want to start over</div><div class="a" style="font-size:14px">
      New analysis, in the sidebar. Earlier sessions and feedback are kept.</div></div>
    <div class="qa" style="margin-bottom:0"><div class="q">Something is wrong</div><div class="a" style="font-size:14px">
      Tell whoever set this up for you — this is a prototype under test, and a fault you hit
      is more useful to us than a session that went smoothly.</div></div>
  </div>`;

function openHelp() {
  let overlay = el('help-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'help-overlay';
    overlay.className = 'overlay';
    document.body.appendChild(overlay);
  }
  overlay.innerHTML = HELP;
  overlay.classList.add('show');
  el('help-close').onclick = () => overlay.classList.remove('show');
  overlay.onclick = (e) => { if (e.target === overlay) overlay.classList.remove('show'); };
}

if (el('help-link')) el('help-link').onclick = (e) => { e.preventDefault(); openHelp(); };
// Both events mean the same thing now: the url changed, so re-render from it.
// route() is serialised, so firing twice is harmless.
/* A participant who hits a fault usually just stops. Log it so a drop-off can be
   told apart from a technical failure. Never any page or work content. */
function reportFault(kind, detail) {
  try {
    fetch(FM.base + '/api/pilot/error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        route: (location.pathname + location.hash).slice(0, 120),
        kind: String(kind).slice(0, 60),
        detail: detail ? String(detail).slice(0, 300) : null,
      }),
      keepalive: true,
    }).catch(() => {});
  } catch (e) { /* never let logging break the page */ }
}

window.addEventListener('error', (e) => reportFault('js-error', e.message));
window.addEventListener('unhandledrejection', (e) =>
  reportFault('promise-rejection', e.reason && e.reason.message));
window.FM_REPORT_FAULT = reportFault;

checkBuild();

window.addEventListener('hashchange', () => { fromNavigation = true; route(); });
window.addEventListener('popstate', () => {
  fromNavigation = true;
  stepDepth = Math.max(0, stepDepth - 1);
  route();
});

route();
