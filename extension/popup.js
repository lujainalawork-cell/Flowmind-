/* FlowMind popup — a small honest status surface, not a second dashboard. */

const APP_URL = 'http://localhost:8000/';

const CATEGORY = {
  FlowMail: 'Email', Gmail: 'Email', Outlook: 'Email',
  FlowSheet: 'Spreadsheet', 'Google Sheets': 'Spreadsheet',
  FlowCRM: 'CRM', HubSpot: 'CRM',
  Slack: 'Messaging', Trello: 'Project', Asana: 'Project',
};
const INITIALS = {
  FlowMail: 'FM', FlowSheet: 'FS', FlowCRM: 'FC', Gmail: 'GM',
  'Google Sheets': 'GS', HubSpot: 'HS', Outlook: 'OL', Slack: 'SL',
  Trello: 'T', Asana: 'A',
};

const ARROW = `<svg class="arrow" width="14" height="13" viewBox="0 0 16 14" fill="none">
    <path d="M8 1c-4 3 4 7 0 10" stroke="#C9DAFF" stroke-width="2" stroke-linecap="round"/>
    <path d="M5.6 8.6 8 11.4l2.4-2.8" stroke="#C9DAFF" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;

const icon = (name) =>
  `<span class="ic ${CATEGORY[name] || 'Other'}">${INITIALS[name] || name.slice(0, 2).toUpperCase()}</span>`;

function duration(ms) {
  if (!ms) return '0s';
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${total}s`;
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) return resolve(null);
      resolve(response);
    });
  });
}

function renderStatus(state) {
  const el = document.getElementById('status');
  const text = document.getElementById('status-text');
  el.className = 'status';
  if (!state.online) {
    el.classList.add('offline');
    el.querySelector('.dot').className = 'dot';
    text.textContent = 'Service offline';
  } else if (state.paused) {
    el.classList.add('paused');
    el.querySelector('.dot').className = 'dot';
    text.textContent = 'Paused';
  } else if (state.recording) {
    el.querySelector('.dot').className = 'dot live';
    text.textContent = 'Analyzing';
  } else {
    el.classList.add('paused');
    el.querySelector('.dot').className = 'dot';
    text.textContent = 'Not analyzing';
  }
  document.getElementById('pause').textContent = state.paused ? 'Resume monitoring' : 'Pause monitoring';

  const note = document.getElementById('footnote');
  if (!state.online) {
    note.innerHTML = `FlowMind service is not running &middot; ${state.pending} event(s) held locally`;
  } else if (!state.recording && !state.paused) {
    note.textContent = 'Start a work analysis in FlowMind to begin';
  } else {
    note.textContent = 'Approved applications only · no content is collected';
  }
  document.getElementById('scope-label').textContent =
    state.sessionCode ? `This analysis · ${state.sessionCode}` : 'This analysis';
}

function renderStats(status) {
  const s = status || {};
  document.getElementById('s-apps').textContent = (s.applications || []).length;
  document.getElementById('s-events').textContent = s.events ?? 0;
  document.getElementById('s-time').textContent = duration(s.time_analysed_ms || 0);
  document.getElementById('s-switches').textContent = s.switches ?? 0;
}

function renderApproved(state) {
  const box = document.getElementById('approved');
  const apps = state.approved || [];
  if (!apps.length) {
    box.innerHTML = `<div class="empty"><div class="d">No applications approved yet.</div></div>`;
    return;
  }
  box.innerHTML = `<div class="chips">${apps.map(a =>
    `<span class="chip">${icon(a)}${a}</span>`).join('')}</div>`;
}

function renderInsight(status) {
  const box = document.getElementById('insight');
  const top = status && status.patterns && status.patterns[0];
  if (!top) {
    box.innerHTML = `
      <div class="empty">
        <div class="t">No repeated sequence yet</div>
        <div class="d">FlowMind needs to see the same sequence of applications happen more than once.</div>
      </div>`;
    return;
  }
  const steps = top.sequence.map((name, i) =>
    `<div class="step">${icon(name)}${name}</div>` +
    (i < top.sequence.length - 1 ? ARROW : '')).join('');
  box.innerHTML = `
    <div class="insight">
      <div class="title">Repeated sequence observed</div>
      <div class="flow">${steps}</div>
      <span class="reps">Repeated ${top.repetitions} times</span>
      <button class="btn btn-secondary" id="view">Open FlowMind</button>
    </div>`;
  document.getElementById('view').addEventListener('click', () => {
    chrome.tabs.create({ url: APP_URL });
    window.close();
  });
}

async function refresh() {
  const state = (await send({ type: 'status' })) ||
    { online: false, paused: false, recording: false, pending: 0, approved: [], status: null };
  renderStatus(state);
  renderStats(state.status);
  renderApproved(state);
  renderInsight(state.status);
}

document.getElementById('pause').addEventListener('click', async () => {
  const state = (await send({ type: 'status' })) || { paused: false };
  await send({ type: 'setPaused', paused: !state.paused });
  refresh();
});

document.getElementById('dashboard').addEventListener('click', () => {
  chrome.tabs.create({ url: APP_URL });
  window.close();
});

refresh();
setInterval(refresh, 3000);
