/* Indicator overlay controller.
 * - Listens for helper:session-meta to populate the topic + operator label.
 * - STOP button invokes cmd_stop_session on the Rust core.
 */
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

await listen('helper:session-meta', (e) => {
  const meta = e.payload || {};
  if (meta.operator_label) {
    document.getElementById('who').textContent =
      `${meta.operator_label} is controlling your computer`;
  }
  if (meta.display_topic) {
    document.getElementById('topic').textContent = meta.display_topic;
  }
});

document.getElementById('indicator-stop').addEventListener('click', async () => {
  // Defensive: require a deliberate hover-and-click. We could add a
  // hold-to-confirm (press+hold 600ms) here if accidental clicks become a
  // problem in QA. For G34.2 v0.1 a single click is sufficient — the badge
  // is too small to hit by accident and the customer expects it to work
  // immediately when they need it.
  await invoke('cmd_stop_session');
});
