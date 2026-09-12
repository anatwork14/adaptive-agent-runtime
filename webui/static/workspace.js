const state = {
  snapshot: null,
  selectedTask: null,
  selectedSession: null,
  selectedDetail: null,
  liveTurn: null,
  cursor: 0,
  ws: null,
  reconnect: null,
  activeTab: 'chat',
};

const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const split = (value) => String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
const sessionByTask = (id) => (state.snapshot?.sessions || []).find((session) => session.task_id === id) || null;
const taskById = (id) => (state.snapshot?.tasks || []).find((task) => task.task_id === id) || null;

function toast(message, error = false) {
  const element = $('#toast');
  element.textContent = message;
  element.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(element._t);
  element._t = setTimeout(() => { element.className = 'toast'; }, 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let body = null;
  try { body = await response.json(); } catch { body = { detail: await response.text() }; }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function renderProviders() {
  const root = $('#providerList');
  const agents = state.snapshot?.agents || [];
  const order = ['codex', 'claude', 'antigravity', 'opencode'];
  root.innerHTML = order.map((provider) => {
    const matches = agents.filter((agent) => agent.provider === provider);
    if (!matches.length) return `<div class="provider-row"><i></i><span>${provider}</span><small>—</small></div>`;
    const ready = matches.some((agent) => agent.doctor?.status === 'READY');
    const warn = matches.some((agent) => agent.doctor?.status === 'AUTH_REQUIRED');
    return `<div class="provider-row ${ready ? 'ready' : warn ? 'warn' : ''}"><i></i><span>${esc(provider)}</span><small>${ready ? 'READY' : warn ? 'LOGIN' : 'SETUP'}</small></div>`;
  }).join('');
}

function renderMetrics() {
  const snapshot = state.snapshot || {};
  const sessions = snapshot.sessions || [];
  const tasks = snapshot.tasks || [];
  const active = sessions.filter((item) => ['open', 'running', 'needs_input', 'failed'].includes(item.status)).length;
  const ready = tasks.filter((item) => item.status === 'ready').length;
  const done = tasks.filter((item) => item.status === 'completed').length;
  const cards = [
    ['Workers', active],
    ['Ready tasks', ready],
    ['Resolved', done],
    ['Memory', snapshot.memory_count || 0],
    ['Tokens', Number(snapshot.budget?.consumed_tokens || 0).toLocaleString()],
    ['Cost', `$${Number(snapshot.budget?.consumed_usd || 0).toFixed(2)}`],
  ];
  $('#metrics').innerHTML = cards.map(([key, value]) => `<div class="metric"><span>${esc(key)}</span><b>${esc(value)}</b></div>`).join('');
}

function boardBucket(task, session) {
  if (task.status === 'completed' || session?.status === 'accepted') return 'done';
  if (session?.status === 'submitted') return 'review';
  if (['failed', 'blocked'].includes(task.status) || ['failed', 'rejected', 'needs_input'].includes(session?.status)) return 'needs';
  return 'working';
}

function renderBoard() {
  const groups = { working: [], needs: [], review: [], done: [] };
  for (const task of state.snapshot?.tasks || []) {
    const session = sessionByTask(task.task_id);
    groups[boardBucket(task, session)].push({ task, session });
  }
  for (const key of Object.keys(groups)) {
    const root = $(`#${key}Cards`);
    const items = groups[key];
    $(`#${key}Count`).textContent = items.length;
    root.innerHTML = items.length ? items.slice().reverse().map(({ task, session }) => {
      const active = (state.selectedSession?.session_id === session?.session_id)
        || (state.selectedTask?.task_id === task.task_id);
      const label = session ? session.status : task.status;
      const agent = session?.agent_name || task.assigned_agent || 'unassigned';
      const files = session?.changed_files?.length || 0;
      return `<button class="worker-card ${key} ${active ? 'selected' : ''}" data-task="${esc(task.task_id)}" data-session="${esc(session?.session_id || '')}"><div class="card-top"><span class="card-id">${esc(session?.session_id || task.task_id)}</span><span class="card-state">${esc(label)}</span></div><div class="card-goal">${esc(task.goal)}</div><div class="card-meta"><span>${esc(task.task_id)}</span><span>${esc(agent)}</span>${session ? `<span>${files} changed</span>` : '<span>READY TO OPEN</span>'}</div></button>`;
    }).join('') : '<div class="empty-column">Nothing here.</div>';
    root.querySelectorAll('.worker-card').forEach((card) => card.addEventListener('click', () => selectItem(card.dataset.task, card.dataset.session || null)));
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  $('#projectName').textContent = snapshot.project_id;
  $('#stateVersion').textContent = `state v${snapshot.version}`;
  renderProviders();
  renderMetrics();
  renderBoard();
  if (state.selectedSession) {
    const fresh = (snapshot.sessions || []).find((item) => item.session_id === state.selectedSession.session_id);
    if (!fresh) closeInspector();
    else {
      state.selectedSession = fresh;
      state.liveTurn = snapshot.live_turns?.[fresh.session_id] || state.liveTurn;
    }
  } else if (state.selectedTask) {
    const fresh = (snapshot.tasks || []).find((item) => item.task_id === state.selectedTask.task_id);
    if (!fresh) closeInspector(); else state.selectedTask = fresh;
  }
}

async function refresh() {
  try {
    renderSnapshot(await api('/api/snapshot'));
    $('#connection').textContent = 'LIVE';
    $('#connectionDot').classList.add('live');
  } catch (error) {
    $('#connection').textContent = 'ERROR';
    $('#connectionDot').classList.remove('live');
    toast(error.message, true);
  }
}

function selectItem(taskId, sessionId) {
  state.selectedTask = taskById(taskId);
  state.selectedSession = sessionId
    ? (state.snapshot?.sessions || []).find((session) => session.session_id === sessionId)
    : null;
  state.liveTurn = sessionId ? state.snapshot?.live_turns?.[sessionId] || null : null;
  renderBoard();
  openInspector();
}

function closeInspector() {
  state.selectedTask = null;
  state.selectedSession = null;
  state.selectedDetail = null;
  state.liveTurn = null;
  $('#inspectorBody').hidden = true;
  $('#inspectorEmpty').hidden = false;
  $('#inspector').classList.remove('open');
  $('#liveTurn').hidden = true;
  renderBoard();
}

async function openInspector() {
  const task = state.selectedTask;
  if (!task) return;
  $('#inspectorEmpty').hidden = true;
  $('#inspectorBody').hidden = false;
  $('#inspector').classList.add('open');
  $('#inspectTitle').textContent = state.selectedSession?.session_id || task.task_id;
  $('#inspectSubtitle').textContent = task.goal;
  $('#inspectKind').textContent = state.selectedSession ? 'WORKER SESSION' : 'READY TASK';
  $('#inspectStatus').textContent = (state.selectedSession?.status || task.status).toUpperCase();
  $('#inspectAgent').textContent = state.selectedSession?.agent_name || task.assigned_agent || 'unassigned';
  $('#inspectBranch').textContent = state.selectedSession?.branch || 'no worktree yet';
  $('#openWorkerBtn').hidden = Boolean(state.selectedSession) || task.status !== 'ready';
  $('#submitWorkerBtn').hidden = !state.selectedSession || !['open', 'failed', 'needs_input'].includes(state.selectedSession.status);
  $('#stopWorkerBtn').hidden = !state.selectedSession || !['open', 'running', 'failed', 'needs_input'].includes(state.selectedSession.status);
  await loadInspectorDetail();
  showTab(state.activeTab);
}

async function loadInspectorDetail() {
  const session = state.selectedSession;
  const task = state.selectedTask;
  if (!task) return;
  try {
    state.selectedDetail = session
      ? await api(`/api/sessions/${encodeURIComponent(session.session_id)}`)
      : await api(`/api/tasks/${encodeURIComponent(task.task_id)}`);
    if (state.selectedDetail?.turn) state.liveTurn = state.selectedDetail.turn;
    renderInspectorContent();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderReview(review, session) {
  if (!session) {
    $('#reviewSummary').textContent = 'Open a worker to publish and supervise a pull request.';
    $('#reviewLink').innerHTML = '';
    $('#reviewChecks').innerHTML = '<div class="empty-column">No checks.</div>';
    $('#reviewFeedback').textContent = 'No review feedback.';
    $('#publishReviewBtn').disabled = true;
    $('#syncReviewBtn').disabled = true;
    $('#applyReviewBtn').disabled = true;
    return;
  }
  const linked = Boolean(review?.linked);
  const failed = review?.checks?.filter((check) => {
    const conclusion = String(check.conclusion || '').toUpperCase();
    return conclusion && !['SUCCESS', 'NEUTRAL', 'SKIPPED'].includes(conclusion);
  }).length || 0;
  const pending = review?.checks?.filter((check) => !check.conclusion && !['COMPLETED', 'SUCCESS'].includes(String(check.status || '').toUpperCase())).length || 0;
  $('#reviewSummary').textContent = linked
    ? `PR #${review.pr_number} · ${review.state || 'UNKNOWN'} · review=${review.review_decision || '-'} · merge=${review.merge_state_status || '-'} · ${failed} failed · ${pending} pending`
    : 'No pull request linked. Publish the current worker branch when it is ready for external review.';
  $('#reviewLink').innerHTML = linked && review.pr_url
    ? `<a href="${esc(review.pr_url)}" target="_blank" rel="noreferrer">${esc(review.pr_url)}</a>`
    : '';
  const checks = review?.checks || [];
  $('#reviewChecks').innerHTML = checks.length
    ? checks.map((check) => `<div class="file-item"><b>${esc(check.name)}</b> · ${esc(check.conclusion || check.status || 'UNKNOWN')}</div>`).join('')
    : '<div class="empty-column">No check results yet.</div>';
  $('#reviewFeedback').textContent = review?.pending_feedback || 'No pending actionable feedback.';
  $('#publishReviewBtn').disabled = !['open', 'failed', 'needs_input'].includes(session.status);
  $('#publishReviewBtn').textContent = linked ? 'Push update' : 'Publish PR';
  $('#syncReviewBtn').disabled = !linked;
  $('#applyReviewBtn').disabled = !linked || !review?.pending_feedback;
}

function latestTurnId(events) {
  for (const event of [...events].reverse()) {
    const turnId = event.payload?.turn_id;
    if (turnId && event.kind === 'session.turn_started') return turnId;
  }
  return null;
}

function turnOutput(events, turnId) {
  if (!turnId) return '';
  return events
    .filter((event) => event.kind === 'session.turn_output' && event.payload?.turn_id === turnId)
    .map((event) => `${event.payload?.stream === 'stderr' ? '[stderr] ' : ''}${event.payload?.content || ''}`)
    .join('')
    .slice(-20000);
}

function renderLiveTurn(turn, events, session) {
  const panel = $('#liveTurn');
  const output = $('#turnOutput');
  const button = $('#cancelTurnBtn');
  const turnId = turn?.turn_id || latestTurnId(events);
  const replay = turnOutput(events, turnId);
  const active = Boolean(turn?.active);
  const cancelling = Boolean(turn?.cancel_requested);
  const visible = Boolean(session && (active || cancelling || replay || turn?.error));

  panel.hidden = !visible;
  panel.classList.toggle('cancelling', cancelling);
  panel.classList.toggle('complete', visible && !active && !cancelling);
  $('#liveTurnId').textContent = turnId || 'latest turn';
  button.disabled = !active || cancelling;
  button.textContent = cancelling ? 'Cancelling…' : 'Cancel turn';
  output.textContent = replay || (active ? 'Waiting for provider output…' : turn?.error || 'Turn complete.');
  if (visible) output.scrollTop = output.scrollHeight;
  $('#chatForm').hidden = !session || active || !['open', 'failed', 'needs_input'].includes(session.status);
}

function renderInspectorContent() {
  const detail = state.selectedDetail || {};
  const session = detail.session || state.selectedSession;
  const task = detail.task || state.selectedTask;
  const messages = session?.messages || [];
  $('#chatMessages').innerHTML = session
    ? (messages.length
      ? messages.map((message) => `<div class="message ${esc(message.role)}"><div class="role">${esc(message.role)}</div><p>${esc(message.content)}</p></div>`).join('')
      : '<div class="message system"><p>No conversation yet.</p></div>')
    : '<div class="message system"><p>Open this task as a persistent worker to start a conversation.</p></div>';
  const files = detail.files || session?.changed_files || [];
  $('#fileList').innerHTML = files.length
    ? files.map((file) => `<div class="file-item">${esc(file)}</div>`).join('')
    : '<div class="empty-column">No draft changes since the last commit/publish.</div>';
  $('#diffView').textContent = detail.diff || 'No uncommitted draft diff. Published commits remain on the worker branch.';
  renderReview(detail.review || null, session || null);
  $('#contextView').textContent = detail.context
    ? JSON.stringify(detail.context, null, 2)
    : 'Open a worker to freeze an immutable session context.';
  const events = detail.events || [];
  $('#workerEvents').innerHTML = events.slice().reverse().map((event) => `<div class="worker-event"><b>#${event.id}</b><span><strong>${esc(event.kind)}</strong><br>${esc(JSON.stringify(event.payload || {}))}</span></div>`).join('') || '<div class="empty-column">No events.</div>';
  $('#terminalCommand').textContent = detail.terminal_command || `arc session open ${task?.task_id || ''}`;
  renderLiveTurn(detail.turn || state.liveTurn, events, session || null);
  $('#copyTerminal').disabled = !session;
}

function showTab(name) {
  state.activeTab = name;
  document.querySelectorAll('.tab').forEach((button) => button.classList.toggle('active', button.dataset.tab === name));
  for (const tab of ['chat', 'files', 'diff', 'review', 'context', 'events', 'terminal']) {
    $(`#tab${tab[0].toUpperCase() + tab.slice(1)}`).hidden = tab !== name;
  }
}

async function openWorker() {
  if (!state.selectedTask) return;
  try {
    $('#openWorkerBtn').disabled = true;
    const session = await api(`/api/tasks/${encodeURIComponent(state.selectedTask.task_id)}/sessions`, {
      method: 'POST', body: JSON.stringify({ agent: null }),
    });
    toast(`Opened ${session.session_id}`);
    await refresh();
    state.selectedSession = session;
    await openInspector();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('#openWorkerBtn').disabled = false;
  }
}

async function submitWorker() {
  if (!state.selectedSession) return;
  if (!confirm(`Submit ${state.selectedSession.session_id} through the ARC gate?`)) return;
  try {
    $('#submitWorkerBtn').disabled = true;
    const result = await api(`/api/sessions/${encodeURIComponent(state.selectedSession.session_id)}/submit`, { method: 'POST', body: '{}' });
    toast(`Gate: ${result.status}`);
    await refresh();
    await loadInspectorDetail();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('#submitWorkerBtn').disabled = false;
  }
}

async function stopWorker() {
  if (!state.selectedSession) return;
  if (!confirm(`Discard draft workspace for ${state.selectedSession.session_id}?`)) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(state.selectedSession.session_id)}/stop`, {
      method: 'POST', body: JSON.stringify({ reason: 'ARC Workspace stop' }),
    });
    toast('Worker stopped; task returned to scheduler');
    closeInspector();
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}

async function sendChat(event) {
  event.preventDefault();
  if (!state.selectedSession) return;
  const form = event.currentTarget;
  const data = new FormData(form);
  const content = String(data.get('message') || '').trim();
  if (!content) return;
  const textarea = form.querySelector('textarea');
  const button = form.querySelector('button');
  textarea.disabled = true;
  button.disabled = true;
  try {
    const turn = await api(`/api/sessions/${encodeURIComponent(state.selectedSession.session_id)}/turn`, {
      method: 'POST', body: JSON.stringify({ content }),
    });
    state.liveTurn = turn;
    textarea.value = '';
    renderLiveTurn(turn, [], state.selectedSession);
    toast(`Live turn ${turn.turn_id || ''} started`);
  } catch (error) {
    toast(error.message, true);
    await refresh();
  } finally {
    textarea.disabled = false;
    button.disabled = false;
    textarea.focus();
  }
}

async function cancelTurn() {
  if (!state.selectedSession || !state.liveTurn?.active) return;
  const button = $('#cancelTurnBtn');
  try {
    button.disabled = true;
    const turn = await api(`/api/sessions/${encodeURIComponent(state.selectedSession.session_id)}/turn/cancel`, {
      method: 'POST', body: '{}',
    });
    state.liveTurn = turn;
    renderLiveTurn(turn, state.selectedDetail?.events || [], state.selectedSession);
    toast('Turn cancellation requested');
  } catch (error) {
    toast(error.message, true);
  }
}

async function publishReview() {
  if (!state.selectedSession) return;
  const button = $('#publishReviewBtn');
  try {
    button.disabled = true;
    const review = await api(`/api/reviews/${encodeURIComponent(state.selectedSession.session_id)}/publish`, {
      method: 'POST', body: JSON.stringify({ base: 'main', remote: 'origin', title: null }),
    });
    toast(review.pr_number ? `PR #${review.pr_number} synchronized` : 'Review branch published');
    await refresh();
    await loadInspectorDetail();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function syncReview() {
  if (!state.selectedSession) return;
  const button = $('#syncReviewBtn');
  try {
    button.disabled = true;
    const result = await api(`/api/reviews/${encodeURIComponent(state.selectedSession.session_id)}/sync`, {
      method: 'POST', body: JSON.stringify({ apply: false }),
    });
    toast(result.changed ? 'GitHub review state updated' : 'Review state already current');
    await loadInspectorDetail();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function applyReview() {
  if (!state.selectedSession) return;
  const button = $('#applyReviewBtn');
  try {
    button.disabled = true;
    const result = await api(`/api/reviews/${encodeURIComponent(state.selectedSession.session_id)}/apply`, {
      method: 'POST', body: '{}',
    });
    toast(result.applied ? 'Review feedback applied to worker' : 'No new feedback to apply');
    await refresh();
    await loadInspectorDetail();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function planObjective() {
  const objective = $('#objectiveInput').value.trim();
  if (!objective) return;
  try {
    $('#planBtn').disabled = true;
    const result = await api('/api/missions/plan', {
      method: 'POST',
      body: JSON.stringify({ objective, files: [], acceptance: [], risk: 0.5, token_budget: 24000, max_tasks: 8 }),
    });
    $('#objectiveInput').value = '';
    toast(`Planned ${result.tasks.length} task${result.tasks.length === 1 ? '' : 's'}`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('#planBtn').disabled = false;
  }
}

async function runFleet() {
  try {
    $('#runFleetBtn').disabled = true;
    toast('Running READY fleet…');
    const result = await api('/api/orchestration/run', {
      method: 'POST', body: JSON.stringify({ policy: null, max_parallel: null }),
    });
    toast(`Fleet: ${result.accepted.length} accepted, ${result.failed.length + result.rejected.length} failed/rejected`);
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('#runFleetBtn').disabled = false;
  }
}

async function createTask(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  try {
    const payload = {
      goal: data.get('goal'),
      files: split(data.get('files')),
      acceptance: String(data.get('acceptance') || '').split(';').map((item) => item.trim()).filter(Boolean),
      risk: Number(data.get('risk') || 0.5),
      token_budget: Number(data.get('token_budget') || 24000),
    };
    const task = await api('/api/tasks', { method: 'POST', body: JSON.stringify(payload) });
    $('#taskDialog').close();
    event.currentTarget.reset();
    toast(`Created ${task.task_id}`);
    await refresh();
    selectItem(task.task_id, null);
  } catch (error) {
    toast(error.message, true);
  }
}

function appendEvent(event) {
  state.cursor = Math.max(state.cursor, Number(event.id || 0));
  $('#eventCursor').textContent = `#${state.cursor}`;
  const row = document.createElement('div');
  row.className = 'trace-row';
  row.innerHTML = `<span>#${event.id}</span><span>${esc(String(event.ts || '').slice(11, 19))}</span><span class="kind">${esc(event.kind)}</span><span>${esc(event.task_id || '-')}</span><span class="payload">${esc(JSON.stringify(event.payload || {}))}</span>`;
  $('#traceRows').prepend(row);
  while ($('#traceRows').children.length > 250) $('#traceRows').lastElementChild?.remove();
}

function appendLiveTurnOutput(event) {
  if (!state.selectedSession || event.payload?.session_id !== state.selectedSession.session_id) return;
  const turnId = event.payload?.turn_id;
  if (state.liveTurn?.turn_id && turnId && state.liveTurn.turn_id !== turnId) return;
  if (!state.liveTurn) state.liveTurn = { session_id: state.selectedSession.session_id, turn_id: turnId, active: true, cancel_requested: false };
  $('#liveTurn').hidden = false;
  $('#liveTurn').classList.remove('complete');
  $('#liveTurnId').textContent = turnId || state.liveTurn.turn_id || 'live turn';
  const output = $('#turnOutput');
  const current = output.textContent === 'Waiting for provider output…' ? '' : output.textContent;
  const prefix = event.payload?.stream === 'stderr' ? '[stderr] ' : '';
  output.textContent = `${current}${prefix}${event.payload?.content || ''}`.slice(-20000);
  output.scrollTop = output.scrollHeight;
}

function reflectTurnLifecycle(event) {
  if (!state.selectedSession || event.payload?.session_id !== state.selectedSession.session_id) return;
  const turnId = event.payload?.turn_id || state.liveTurn?.turn_id;
  if (event.kind === 'session.turn_started') {
    state.liveTurn = { session_id: state.selectedSession.session_id, turn_id: turnId, active: true, done: false, cancel_requested: false, error: null };
  } else if (event.kind === 'session.turn_cancel_requested') {
    state.liveTurn = { ...(state.liveTurn || {}), session_id: state.selectedSession.session_id, turn_id: turnId, active: true, cancel_requested: true };
  } else if (['session.turn_finished', 'session.turn_cancelled', 'session.failed'].includes(event.kind)) {
    state.liveTurn = { ...(state.liveTurn || {}), session_id: state.selectedSession.session_id, turn_id: turnId, active: false, done: true, cancel_requested: false, error: event.kind === 'session.failed' ? event.payload?.error || 'Provider turn failed' : null };
  }
  renderLiveTurn(state.liveTurn, state.selectedDetail?.events || [], state.selectedSession);
}

async function loadEvents() {
  try {
    const events = await api(`/api/events?after=${state.cursor}&limit=200`);
    events.forEach(appendEvent);
  } catch (error) {
    toast(error.message, true);
  }
}

function connectEvents() {
  if (state.ws) try { state.ws.close(); } catch {}
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws/events?after=${state.cursor}`);
  state.ws = socket;
  socket.onopen = () => {
    $('#connection').textContent = 'LIVE';
    $('#connectionDot').classList.add('live');
    clearTimeout(state.reconnect);
  };
  socket.onmessage = async (message) => {
    try {
      const event = JSON.parse(message.data);
      appendEvent(event);
      if (event.kind === 'session.turn_output') {
        appendLiveTurnOutput(event);
        return;
      }
      if (event.kind.startsWith('session.turn_') || event.kind === 'session.failed') {
        reflectTurnLifecycle(event);
      }
      if (event.kind.startsWith('session.') || event.kind.startsWith('task.') || event.kind.startsWith('gate.') || event.kind.startsWith('orchestration.') || event.kind === 'recovery.retry') {
        await refresh();
        if (state.selectedSession || state.selectedTask) await loadInspectorDetail();
      }
    } catch {}
  };
  socket.onclose = () => {
    $('#connection').textContent = 'RECONNECTING';
    $('#connectionDot').classList.remove('live');
    state.reconnect = setTimeout(connectEvents, 1100);
  };
  socket.onerror = () => socket.close();
}

function switchView(view) {
  document.querySelectorAll('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  const trace = view === 'trace';
  $('#board').hidden = trace;
  $('#traceView').hidden = !trace;
  if (['workers', 'agents'].includes(view)) toast(`${view[0].toUpperCase() + view.slice(1)} are represented directly on the live worker board`);
}

$('#closeInspector').addEventListener('click', closeInspector);
document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => showTab(button.dataset.tab)));
document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
$('#openWorkerBtn').addEventListener('click', openWorker);
$('#submitWorkerBtn').addEventListener('click', submitWorker);
$('#stopWorkerBtn').addEventListener('click', stopWorker);
$('#chatForm').addEventListener('submit', sendChat);
$('#cancelTurnBtn').addEventListener('click', cancelTurn);
$('#publishReviewBtn').addEventListener('click', publishReview);
$('#syncReviewBtn').addEventListener('click', syncReview);
$('#applyReviewBtn').addEventListener('click', applyReview);
$('#copyTerminal').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('#terminalCommand').textContent);
    toast('Attach command copied');
  } catch {
    toast('Copy failed', true);
  }
});
$('#planBtn').addEventListener('click', planObjective);
$('#runFleetBtn').addEventListener('click', runFleet);
$('#newTaskBtn').addEventListener('click', () => $('#taskDialog').showModal());
$('#taskForm').addEventListener('submit', createTask);
$('#refreshBtn').addEventListener('click', () => Promise.all([refresh(), loadEvents()]));
$('#objectiveInput').addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') planObjective();
});

(async () => {
  await refresh();
  await loadEvents();
  connectEvents();
  setInterval(refresh, 5000);
})();