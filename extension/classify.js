/* Application classification, driven entirely by the APPROVED list.
 *
 * FlowMind never guesses. A tab is classified only if its domain appears in the
 * list of applications the employee approved on the FlowMind Privacy page.
 * Everything else returns null: not classified, not counted, not recorded, and
 * never sent anywhere.
 */

function fmNormaliseHost(hostname) {
  const host = (hostname || '').toLowerCase();
  if (host === '127.0.0.1' || host === '[::1]') return 'localhost';
  return host.replace(/^www\./, '');
}

function fmClassify(url, permissions) {
  if (!url || !Array.isArray(permissions) || !permissions.length) return null;

  let u;
  try { u = new URL(url); } catch (e) { return null; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;

  const host = fmNormaliseHost(u.hostname);
  const path = u.pathname || '/';

  let best = null;
  for (const p of permissions) {
    const domain = fmNormaliseHost(p.domain);
    const hostMatches = host === domain || host.endsWith('.' + domain);
    if (!hostMatches) continue;
    const prefix = p.path_prefix || '';
    if (prefix && !path.startsWith(prefix)) continue;
    // the most specific rule wins (longest path prefix)
    if (!best || prefix.length > (best.path_prefix || '').length) best = p;
  }
  if (!best) return null;
  return { application: best.application, category: best.category };
}

if (typeof self !== 'undefined') {
  self.fmClassify = fmClassify;
  self.fmNormaliseHost = fmNormaliseHost;
}
