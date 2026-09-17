/* Shared helpers for the FlowMind dashboard and demo environment. */

const FM = {
  base: location.origin,

  async api(path, options) {
    const res = await fetch(FM.base + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) throw new Error(path + ' -> ' + res.status);
    return res.json();
  },

  async safeApi(path, options, fallback) {
    try { return await FM.api(path, options); }
    catch (err) {
      console.warn('[FlowMind]', err.message);
      // Record the failure, unless it was the error reporter itself failing.
      if (window.FM_REPORT_FAULT && !path.startsWith('/api/pilot/error')) {
        window.FM_REPORT_FAULT('api-failure', path + ' :: ' + err.message);
      }
      return fallback;
    }
  },

  /* ------------------------------------------------------------ formatting */

  duration(ms) {
    if (!ms || ms < 0) return '0m';
    const totalSeconds = Math.round(ms / 1000);
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s ? s + 's' : ''}`.trim();
    return `${s}s`;
  },

  minutes(ms) {
    const m = ms / 60000;
    if (m < 10) return (Math.round(m * 10) / 10).toFixed(1);
    return String(Math.round(m));
  },

  clock(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  },

  clockSeconds(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  },

  day(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
  },

  initials(app) {
    const map = {
      'FlowMail': 'FM', 'FlowSheet': 'FS', 'FlowCRM': 'FC',
      'Gmail': 'GM', 'Google Sheets': 'GS', 'HubSpot': 'HS', 'Outlook': 'OL',
      'Notion': 'N', 'Trello': 'T', 'Asana': 'A', 'Slack': 'SL', 'Other': '·',
      'Zendesk': 'ZD', 'Freshdesk': 'FD', 'Intercom': 'IC', 'Help Scout': 'HS',
      'WhatsApp Business': 'WA', 'Salesforce': 'SF',
    };
    return map[app] || app.slice(0, 2).toUpperCase();
  },

  categoryOf(app) {
    const map = {
      'FlowMail': 'Email', 'Gmail': 'Email', 'Outlook': 'Email',
      'FlowSheet': 'Spreadsheet', 'Google Sheets': 'Spreadsheet',
      'FlowCRM': 'CRM', 'HubSpot': 'CRM',
      'Notion': 'Project', 'Trello': 'Project', 'Asana': 'Project',
      'Slack': 'Messaging',
      'Zendesk': 'Support', 'Freshdesk': 'Support', 'Intercom': 'Support',
      'Help Scout': 'Support', 'WhatsApp Business': 'Support', 'Salesforce': 'CRM',
    };
    return map[app] || 'Other';
  },

  appChip(app) {
    const cat = FM.categoryOf(app);
    return `<span class="appchip"><span class="appicon ${cat}">${FM.initials(app)}</span>${app}</span>`;
  },

  escape(text) {
    return String(text ?? '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  },

  toast(message) {
    let el = document.getElementById('fm-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'fm-toast';
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(FM._toastTimer);
    FM._toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
  },
};

window.FM = FM;
