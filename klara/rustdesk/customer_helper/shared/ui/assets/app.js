/* Klaravex helper — main UI controller.
 * Talks to the Tauri Rust core via window.__TAURI__.invoke.
 * The Rust side emits `helper:state` events ("awaiting-token" → "redeeming"
 * → "configuring" → "launching" → "active" → "error") and we mirror those
 * onto the <body data-state>.
 */
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const root = document.querySelector('.app-shell');
const setState = (s) => root.setAttribute('data-state', s);

await listen('helper:state', (e) => {
  if (typeof e.payload === 'string') setState(e.payload);
});

await listen('helper:error', (e) => {
  setState('error');
  const msg = document.getElementById('error-msg');
  if (msg) msg.textContent = String(e.payload ?? 'Unknown error');
});

const form = document.getElementById('token-form');
form?.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const tok = document.getElementById('token-input').value.trim();
  if (!tok) return;
  setState('redeeming');
  try {
    await invoke('cmd_request_token', { token: tok });
  } catch (e) {
    setState('error');
    document.getElementById('error-msg').textContent = String(e);
  }
});

document.getElementById('stop-btn')?.addEventListener('click', async () => {
  await invoke('cmd_stop_session');
});
