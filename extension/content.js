/* FlowMind content script.
 *
 * Two jobs, both deliberately minimal:
 *   1. count copy and paste events — the EVENT only, never the clipboard data
 *   2. show the FlowMind contextual indicator once a repeated pattern is real
 *
 * The listeners below never call event.clipboardData, never read the selection,
 * and never inspect the DOM of the host page.
 */

(function () {
  // Lets the FlowMind app confirm the extension is installed.
  document.documentElement.dataset.flowmindExtension = 'active';

  let approved = false;
  function refreshApproval() {
    try {
      chrome.storage.local.get('config', (data) => {
        if (chrome.runtime.lastError) return;
        const perms = (data && data.config && data.config.permissions) || [];
        approved = !!fmClassify(location.href, perms);
      });
    } catch (e) { /* extension context reloaded */ }
  }
  refreshApproval();
  setInterval(refreshApproval, 10000);

  /* ------------------------------------------------------ clipboard counts */

  function report(action) {
    if (!approved) return;            // never report from an unapproved page
    try {
      chrome.runtime.sendMessage({ type: 'clipboard', action }, () => void chrome.runtime.lastError);
    } catch (e) { /* extension context reloaded */ }
  }

  document.addEventListener('copy', () => report('copy'), true);
  document.addEventListener('cut', () => report('copy'), true);
  document.addEventListener('paste', () => report('paste'), true);

  /* ------------------------------------------------- contextual indicator */

  const DISMISS_KEY = 'flowmind-bubble-dismissed';
  let root = null;
  let shown = null;

  function dismissed(key) {
    try { return sessionStorage.getItem(DISMISS_KEY) === key; } catch (e) { return false; }
  }
  function dismiss(key) {
    try { sessionStorage.setItem(DISMISS_KEY, key); } catch (e) { /* ignore */ }
  }

  function initials(name) {
    const map = {
      FlowMail: 'FM', FlowSheet: 'FS', FlowCRM: 'FC',
      Gmail: 'GM', 'Google Sheets': 'GS', HubSpot: 'HS',
      Notion: 'N', Trello: 'T', Asana: 'A',
    };
    return map[name] || name.slice(0, 2).toUpperCase();
  }
  function categoryOf(name) {
    const map = {
      FlowMail: 'Email', Gmail: 'Email',
      FlowSheet: 'Spreadsheet', 'Google Sheets': 'Spreadsheet',
      FlowCRM: 'CRM', HubSpot: 'CRM',
      Notion: 'Project', Trello: 'Project', Asana: 'Project',
    };
    return map[name] || 'Other';
  }

  const ARROW = `<svg class="fm-arrow" width="16" height="14" viewBox="0 0 16 14" fill="none">
      <path d="M8 1c-4 3 4 7 0 10" stroke="#C9DAFF" stroke-width="2" stroke-linecap="round"/>
      <path d="M5.6 8.6 8 11.4l2.4-2.8" stroke="#C9DAFF" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;

  const MARK = `<svg width="15" height="15" viewBox="0 0 32 32" fill="none">
      <path d="M6 21c4-10 16-10 20 0" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
      <circle cx="16" cy="12" r="2.8" fill="#C7EF66"/>
    </svg>`;

  function ensureRoot() {
    if (root && document.body.contains(root)) return root;
    root = document.createElement('div');
    root.id = 'flowmind-bubble-root';
    document.body.appendChild(root);
    return root;
  }

  function renderOrb(insight) {
    ensureRoot().innerHTML =
      `<button class="fm-orb" title="FlowMind detected a pattern" aria-label="FlowMind detected a pattern">${MARK}</button>`;
    root.querySelector('.fm-orb').addEventListener('click', () => renderPanel(insight));
  }

  function renderPanel(insight) {
    const steps = insight.sequence.map((name, i) => `
      <div class="fm-step"><span class="fm-ic ${categoryOf(name)}">${initials(name)}</span>${name}</div>
      ${i < insight.sequence.length - 1 ? ARROW : ''}`).join('');

    ensureRoot().innerHTML = `
      <div class="fm-panel" role="dialog" aria-label="FlowMind pattern detected">
        <div class="fm-head">
          <span class="fm-mark">${MARK}</span>
          <span class="fm-title">FlowMind</span>
          <button class="fm-close" aria-label="Dismiss">×</button>
        </div>
        <h4>FlowMind detected a pattern</h4>
        <p>You've moved between these applications repeatedly during this analysis.</p>
        <div class="fm-flow">${steps}</div>
        <span class="fm-count">${insight.repetitions} times so far</span>
        <p>This may indicate repetitive information transfer.</p>
        <div class="fm-actions">
          <button class="fm-btn fm-btn-primary">Open FlowMind</button>
          <button class="fm-btn fm-btn-ghost">Later</button>
        </div>
        <div class="fm-note">Based on application metadata only — no page content was read.</div>
      </div>`;

    const close = () => { dismiss(insight.pattern_key); root.remove(); root = null; };
    root.querySelector('.fm-close').addEventListener('click', close);
    root.querySelector('.fm-btn-ghost').addEventListener('click', close);
    root.querySelector('.fm-btn-primary').addEventListener('click', () => {
      dismiss(insight.pattern_key);
      window.open('http://localhost:8000/#/consultant', '_blank');
      if (root) { root.remove(); root = null; }
    });
  }

  function maybeShow(insight) {
    if (!approved) return;
    if (!insight || !insight.sequence || insight.repetitions < 3) return;
    if (dismissed(insight.pattern_key)) return;
    if (shown === insight.pattern_key && root && document.body.contains(root)) return;
    shown = insight.pattern_key;
    renderOrb(insight);
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'flowmind-insight') maybeShow(msg.insight);
  });

  // Catch up on page load in case the pattern was detected before this page opened.
  setTimeout(() => {
    try {
      chrome.storage.local.get(['bubbleReady', 'insight', 'paused'], (data) => {
        if (chrome.runtime.lastError) return;
        if (data && data.bubbleReady) maybeShow(data.insight);
      });
    } catch (e) { /* extension context reloaded */ }
  }, 1200);
})();
