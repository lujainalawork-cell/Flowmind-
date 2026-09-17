/* FlowMind service worker — Manifest V3.
 *
 * Records behavioural metadata about APPROVED applications only, and only while
 * a work analysis is explicitly running. It never reads page content, selected
 * text, clipboard contents, form values, keystrokes or document contents, and it
 * never looks at the address of a site the employee has not approved.
 */

importScripts('classify.js');

const API_BASE = 'http://localhost:8000';
const MAX_VISIT_MS = 10 * 60 * 1000;
const QUEUE_LIMIT = 400;
const CONFIG_TTL_MS = 5000;

/* ------------------------------------------------------------------ config */

async function getConfig(force) {
  const cached = await chrome.storage.session.get(['config', 'configAt']);
  const fresh = cached.configAt && (Date.now() - cached.configAt) < CONFIG_TTL_MS;
  if (!force && fresh && cached.config) return cached.config;
  try {
    const res = await fetch(API_BASE + '/api/extension/config');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const config = await res.json();
    await chrome.storage.session.set({ config, configAt: Date.now() });
    await chrome.storage.local.set({ online: true, config });
    return config;
  } catch (e) {
    await chrome.storage.local.set({ online: false });
    const stored = await chrome.storage.local.get('config');
    return cached.config || stored.config || { recording: false, paused: false, permissions: [] };
  }
}

async function runId() {
  const s = await chrome.storage.session.get('runId');
  if (s.runId) return s.runId;
  const id = 'run-' + Date.now().toString(36);
  await chrome.storage.session.set({ runId: id });
  return id;
}

async function queueEvent(event) {
  const { queue = [] } = await chrome.storage.local.get('queue');
  queue.push(event);
  if (queue.length > QUEUE_LIMIT) queue.splice(0, queue.length - QUEUE_LIMIT);
  await chrome.storage.local.set({ queue });
}

/* ------------------------------------------------------------- visit model */

async function closeCurrentVisit(endedAt) {
  const { current } = await chrome.storage.session.get('current');
  if (!current) return;
  await chrome.storage.session.remove('current');
  const started = new Date(current.startedAt).getTime();
  const duration = Math.max(0, Math.min(new Date(endedAt).getTime() - started, MAX_VISIT_MS));
  if (duration < 400) return;
  await queueEvent({
    type: 'app_visit',
    application: current.application,
    category: current.category,
    started_at: current.startedAt,
    ended_at: new Date(started + duration).toISOString(),
    duration_ms: duration,
  });
}

async function setActiveApp(app) {
  const now = new Date().toISOString();
  const { current } = await chrome.storage.session.get('current');
  if (current && app && current.application === app.application) return;
  await closeCurrentVisit(now);
  if (!app) return;                       // unapproved or non-work tab
  await chrome.storage.session.set({
    current: { application: app.application, category: app.category, startedAt: now },
  });
}

async function syncActiveTab() {
  let config = await getConfig();
  // If we believe we are idle, re-check before ignoring the tab: the participant
  // may have just pressed Continue in FlowMind and started the analysis. Without
  // this, the first seconds of their work would be silently dropped.
  if (!config.recording || config.paused) config = await getConfig(true);
  if (!config.recording || config.paused) {
    await closeCurrentVisit(new Date().toISOString());
    await flush();
    await refreshBadge();
    return;
  }
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    await setActiveApp(tab ? fmClassify(tab.url || '', config.permissions) : null);
  } catch (e) { /* no accessible tab */ }
  await flush();
  await refreshBadge();
}

/* ------------------------------------------------------------------ events */

chrome.tabs.onActivated.addListener(syncActiveTab);

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if ((info.status === 'complete' || info.url) && tab.active) syncActiveTab();
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    await closeCurrentVisit(new Date().toISOString());
    await flush();
  } else {
    await syncActiveTab();
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (msg.type === 'clipboard') {
      const config = await getConfig();
      if (!config.recording || config.paused) return sendResponse({ ok: false });
      const app = fmClassify(sender.tab ? sender.tab.url : '', config.permissions);
      if (!app) return sendResponse({ ok: false });
      await queueEvent({
        type: msg.action,                      // 'copy' or 'paste' — the event only
        application: app.application,
        category: app.category,
        started_at: new Date().toISOString(),
        duration_ms: 0,
      });
      await flush();
      return sendResponse({ ok: true });
    }
    if (msg.type === 'status') return sendResponse(await getStatus());
    if (msg.type === 'setPaused') {
      await setPaused(msg.paused);
      return sendResponse({ paused: msg.paused });
    }
    sendResponse({});
  })();
  return true;
});

chrome.alarms.create('flowmind-tick', { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== 'flowmind-tick') return;
  const { current } = await chrome.storage.session.get('current');
  if (current && (Date.now() - new Date(current.startedAt).getTime()) > MAX_VISIT_MS) {
    await closeCurrentVisit(new Date().toISOString());
  }
  await syncActiveTab();
});

chrome.runtime.onInstalled.addListener(() => { getConfig(true).then(syncActiveTab); });
chrome.runtime.onStartup.addListener(() => { getConfig(true).then(syncActiveTab); });

/* ------------------------------------------------------------------- flush */

let flushing = false;

async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    const { queue = [] } = await chrome.storage.local.get('queue');
    if (!queue.length) { await poll(); return; }

    const batch = queue.slice(0, 200);
    const res = await fetch(API_BASE + '/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: await runId(), events: batch }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    const { queue: latest = [] } = await chrome.storage.local.get('queue');
    await chrome.storage.local.set({
      queue: latest.slice(batch.length),
      online: true,
      lastSync: new Date().toISOString(),
      live: data.live || null,
      insight: data.top || null,
      bubbleReady: !!data.bubble_ready,
    });
    await notifyTabs();
  } catch (e) {
    await chrome.storage.local.set({ online: false });
  } finally {
    flushing = false;
  }
}

/** Keeps the popup and the in-page hint accurate when nothing is queued. */
async function poll() {
  try {
    const res = await fetch(API_BASE + '/api/analysis/status');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const status = await res.json();
    const top = (status.patterns && status.patterns[0]) || null;
    await chrome.storage.local.set({
      online: true,
      status,
      insight: top,
      bubbleReady: !!(top && top.repetitions >= 3),
    });
    await notifyTabs();
  } catch (e) {
    await chrome.storage.local.set({ online: false });
  }
}

async function notifyTabs() {
  const { bubbleReady, insight } = await chrome.storage.local.get(['bubbleReady', 'insight']);
  if (!bubbleReady || !insight) return;
  const config = await getConfig();
  try {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (!tab.url || !fmClassify(tab.url, config.permissions)) continue;
      chrome.tabs.sendMessage(tab.id, { type: 'flowmind-insight', insight },
        () => void chrome.runtime.lastError);
    }
  } catch (e) { /* nothing to notify */ }
}

/* ------------------------------------------------------------------ status */

async function getStatus() {
  const local = await chrome.storage.local.get(['queue', 'lastSync', 'online']);
  let status = null;
  try {
    const res = await fetch(API_BASE + '/api/analysis/status');
    if (res.ok) {
      status = await res.json();
      await chrome.storage.local.set({ online: true, status });
    }
  } catch (e) {
    const cached = await chrome.storage.local.get('status');
    status = cached.status || null;
    await chrome.storage.local.set({ online: false });
  }
  const config = await getConfig();
  return {
    online: status !== null,
    paused: !!(status ? status.paused : config.paused),
    recording: !!(status ? status.recording : config.recording),
    sessionCode: config.session_code || null,
    approved: config.permissions.map(p => p.application),
    pending: (local.queue || []).length,
    lastSync: local.lastSync || null,
    status,
  };
}

async function setPaused(paused) {
  if (paused) await closeCurrentVisit(new Date().toISOString());
  try {
    await fetch(API_BASE + '/api/monitoring', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paused }),
    });
  } catch (e) { /* offline: the server stays the source of truth when it returns */ }
  await getConfig(true);
  if (!paused) await syncActiveTab();
  await refreshBadge();
}

async function refreshBadge() {
  const config = await getConfig();
  const { online } = await chrome.storage.local.get('online');
  if (online === false) {
    await chrome.action.setBadgeText({ text: '!' });
    await chrome.action.setBadgeBackgroundColor({ color: '#E8A33D' });
  } else if (config.paused) {
    await chrome.action.setBadgeText({ text: '||' });
    await chrome.action.setBadgeBackgroundColor({ color: '#8C96B4' });
  } else if (config.recording) {
    await chrome.action.setBadgeText({ text: '●' });
    await chrome.action.setBadgeBackgroundColor({ color: '#6192FC' });
  } else {
    await chrome.action.setBadgeText({ text: '' });
  }
}

getConfig(true).then(syncActiveTab);
