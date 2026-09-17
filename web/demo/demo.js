/* Shared logic for the three FlowMind demo applications. */

const DEMO = {
  orders: [],

  async load() {
    const data = await FM.safeApi('/api/demo/orders', {}, { orders: [], completed: 0, total: 0 });
    DEMO.orders = data.orders;
    return data;
  },

  /** The order the tester should currently be working on. */
  current() {
    return DEMO.orders.find(o => !o.mail_done) || null;
  },

  async mark(orderId, step) {
    await FM.safeApi(`/api/demo/orders/${orderId}`, {
      method: 'POST',
      body: JSON.stringify({ step }),
    }, null);
    await DEMO.load();
  },

  /**
   * Copy using a real selection + document.execCommand('copy').
   * This dispatches a genuine native 'copy' event on the document, which is
   * what the FlowMind extension counts. No text ever leaves the page.
   */
  copy(text, buttonEl) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none;';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    if (buttonEl) {
      const original = buttonEl.dataset.label || buttonEl.textContent;
      buttonEl.dataset.label = original;
      buttonEl.textContent = ok ? 'Copied' : 'Select and press Ctrl+C';
      buttonEl.classList.toggle('btn-lime', ok);
      setTimeout(() => {
        buttonEl.textContent = original;
        buttonEl.classList.remove('btn-lime');
      }, 1600);
    }
    return ok;
  },

  /** Renders the thin user-test strip at the top of every demo app. */
  strip({ step, total, instruction, data }) {
    const completed = data ? data.completed : 0;
    const count = data ? data.total : 0;
    const pips = Array.from({ length: count }, (_, i) =>
      `<span class="pipd ${i < completed ? 'done' : ''}"></span>`).join('');
    return `
      <div class="teststrip">
        <span class="badge">FlowMind user test</span>
        <span class="step">Step <b>${step}</b> of ${total} &nbsp;·&nbsp; ${instruction}</span>
        <span class="progress">
          <span class="tiny" style="color:#C9DAFF">${completed}/${count} requests handled</span>
          ${pips}
        </span>
      </div>`;
  },

  allDone(data) {
    return data.total > 0 && data.completed >= data.total;
  },
};

window.DEMO = DEMO;
