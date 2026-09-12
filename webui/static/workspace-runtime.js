const runtimeUi = {
  timer: null,
  lastSession: null,
};

const r$ = (selector) => document.querySelector(selector);

function currentWorkerSessionId() {
  const kind = r$('#inspectKind')?.textContent?.trim();
  const id = r$('#inspectTitle')?.textContent?.trim();
  if (kind !== 'WORKER SESSION' || !id || id === '—') return null;
  return id;
}

async function runtimeApi(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let body = null;
  try { body = await response.json(); } catch { body = { detail: await response.text() }; }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function runtimeToast(message, error = false) {
  const element = r$('#toast');
  if (!element) return;
  element.textContent = message;
  element.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(element._runtimeTimer);
  element._runtimeTimer = setTimeout(() => { element.className = 'toast'; }, 2800);
}

function setRuntimeButtons(enabled) {
  for (const id of ['startPreviewBtn', 'stopPreviewBtn', 'openPreviewBtn', 'startTerminalBtn', 'stopTerminalBtn']) {
    const element = r$(`#${id}`);
    if (element) element.disabled = !enabled;
  }
}

function renderPreview(preview) {
  const state = r$('#previewState');
  const url = r$('#previewUrl');
  const frame = r$('#previewFrame');
  const log = r$('#previewLog');
  const start = r$('#startPreviewBtn');
  const stop = r$('#stopPreviewBtn');
  const open = r$('#openPreviewBtn');
  if (!state || !url || !frame || !log || !start || !stop || !open) return;

  const running = Boolean(preview?.running);
  const ready = Boolean(preview?.ready);
  state.textContent = running ? (ready ? 'READY' : 'STARTING') : 'STOPPED';
  state.classList.toggle('runtime-live', running);
  state.classList.toggle('runtime-ready', ready);
  url.textContent = preview?.url || '';
  url.href = preview?.url || '#';
  url.hidden = !preview?.url;
  log.textContent = preview?.log_tail || (running ? 'Preview started; waiting for output…' : 'No preview runtime.');
  start.disabled = running;
  stop.disabled = !running;
  open.disabled = !preview?.url || !running;

  if (ready && preview?.url) {
    if (frame.dataset.url !== preview.url) {
      frame.src = preview.url;
      frame.dataset.url = preview.url;
    }
    frame.hidden = false;
  } else {
    frame.hidden = true;
    if (!running) {
      frame.removeAttribute('src');
      delete frame.dataset.url;
    }
  }
}

function renderTerminal(terminal, sessionId) {
  const state = r$('#terminalState');
  const name = r$('#terminalRuntimeName');
  const command = r$('#terminalCommand');
  const log = r$('#terminalLog');
  const start = r$('#startTerminalBtn');
  const stop = r$('#stopTerminalBtn');
  if (!state || !name || !command || !log || !start || !stop) return;

  const running = Boolean(terminal?.running);
  state.textContent = running ? 'RUNNING' : 'STOPPED';
  state.classList.toggle('runtime-live', running);
  state.classList.toggle('runtime-ready', running);
  name.textContent = terminal?.runtime_name || 'tmux runtime not started';
  command.textContent = sessionId ? `arc terminal ${sessionId}` : 'arc terminal …';
  log.textContent = terminal?.log_tail || (running ? 'Terminal is running.' : 'No terminal runtime.');
  start.disabled = running;
  stop.disabled = !running;
}

function renderNoWorker() {
  setRuntimeButtons(false);
  renderPreview(null);
  renderTerminal(null, null);
  const previewState = r$('#previewState');
  const terminalState = r$('#terminalState');
  if (previewState) previewState.textContent = 'NO WORKER';
  if (terminalState) terminalState.textContent = 'NO WORKER';
}

async function refreshWorkerRuntime({ quiet = true } = {}) {
  const sessionId = currentWorkerSessionId();
  runtimeUi.lastSession = sessionId;
  if (!sessionId) {
    renderNoWorker();
    return;
  }
  try {
    const data = await runtimeApi(`/api/sessions/${encodeURIComponent(sessionId)}/runtime`);
    renderPreview(data.preview || null);
    renderTerminal(data.terminal || null, sessionId);
  } catch (error) {
    if (!quiet) runtimeToast(error.message, true);
  }
}

async function startPreview() {
  const sessionId = currentWorkerSessionId();
  if (!sessionId) return runtimeToast('Select a worker session first', true);
  const command = String(r$('#previewCommand')?.value || '').trim();
  const port = Number(r$('#previewPort')?.value || 0);
  if (!command.includes('{host}') || !command.includes('{port}')) {
    return runtimeToast('Preview command must contain {host} and {port}', true);
  }
  try {
    r$('#startPreviewBtn').disabled = true;
    await runtimeApi(`/api/sessions/${encodeURIComponent(sessionId)}/preview/start`, {
      method: 'POST',
      body: JSON.stringify({ command, port, host: '127.0.0.1' }),
    });
    runtimeToast(`Preview started on 127.0.0.1:${port}`);
    await refreshWorkerRuntime({ quiet: false });
  } catch (error) {
    runtimeToast(error.message, true);
    await refreshWorkerRuntime();
  }
}

async function stopPreview() {
  const sessionId = currentWorkerSessionId();
  if (!sessionId) return;
  try {
    r$('#stopPreviewBtn').disabled = true;
    await runtimeApi(`/api/sessions/${encodeURIComponent(sessionId)}/preview/stop`, {
      method: 'POST', body: '{}',
    });
    runtimeToast('Preview stopped');
    await refreshWorkerRuntime({ quiet: false });
  } catch (error) {
    runtimeToast(error.message, true);
  }
}

function openPreview() {
  const url = r$('#previewUrl')?.href;
  if (url && url !== '#' && url !== location.href) window.open(url, '_blank', 'noopener,noreferrer');
}

async function startTerminal() {
  const sessionId = currentWorkerSessionId();
  if (!sessionId) return runtimeToast('Select a worker session first', true);
  try {
    r$('#startTerminalBtn').disabled = true;
    await runtimeApi(`/api/sessions/${encodeURIComponent(sessionId)}/terminal/start`, {
      method: 'POST', body: '{}',
    });
    runtimeToast('Persistent provider terminal started');
    await refreshWorkerRuntime({ quiet: false });
  } catch (error) {
    runtimeToast(error.message, true);
    await refreshWorkerRuntime();
  }
}

async function stopTerminal() {
  const sessionId = currentWorkerSessionId();
  if (!sessionId) return;
  try {
    r$('#stopTerminalBtn').disabled = true;
    await runtimeApi(`/api/sessions/${encodeURIComponent(sessionId)}/terminal/stop`, {
      method: 'POST', body: '{}',
    });
    runtimeToast('Persistent terminal stopped');
    await refreshWorkerRuntime({ quiet: false });
  } catch (error) {
    runtimeToast(error.message, true);
  }
}

function repairPreviewTabBehavior() {
  document.querySelectorAll('.tab').forEach((button) => {
    button.addEventListener('click', () => {
      const preview = r$('#tabPreview');
      if (!preview) return;
      const selected = button.dataset.tab;
      preview.hidden = selected !== 'preview';
      if (selected === 'preview') {
        for (const tab of ['chat', 'files', 'diff', 'review', 'context', 'events', 'terminal']) {
          const node = r$(`#tab${tab[0].toUpperCase() + tab.slice(1)}`);
          if (node) node.hidden = true;
        }
        refreshWorkerRuntime({ quiet: false });
      }
    });
  });
}

function installRuntimeControls() {
  repairPreviewTabBehavior();
  r$('#startPreviewBtn')?.addEventListener('click', startPreview);
  r$('#stopPreviewBtn')?.addEventListener('click', stopPreview);
  r$('#openPreviewBtn')?.addEventListener('click', openPreview);
  r$('#startTerminalBtn')?.addEventListener('click', startTerminal);
  r$('#stopTerminalBtn')?.addEventListener('click', stopTerminal);

  r$('#copyTerminal')?.addEventListener('click', () => {
    const sessionId = currentWorkerSessionId();
    if (sessionId) r$('#terminalCommand').textContent = `arc terminal ${sessionId}`;
  });

  const observer = new MutationObserver(() => {
    const sessionId = currentWorkerSessionId();
    if (sessionId !== runtimeUi.lastSession) refreshWorkerRuntime();
  });
  const title = r$('#inspectTitle');
  const kind = r$('#inspectKind');
  if (title) observer.observe(title, { childList: true, characterData: true, subtree: true });
  if (kind) observer.observe(kind, { childList: true, characterData: true, subtree: true });

  refreshWorkerRuntime();
  runtimeUi.timer = setInterval(() => {
    if (currentWorkerSessionId()) refreshWorkerRuntime();
  }, 3000);
}

installRuntimeControls();
