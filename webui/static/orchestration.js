const $ = selector => document.querySelector(selector);

function toast(message, error = false) {
  const el = $('#toast');
  if (!el) return;
  el.textContent = message;
  el.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(el._arcTimer);
  el._arcTimer = setTimeout(() => { el.className = 'toast'; }, 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options,
  });
  let body;
  try { body = await response.json(); }
  catch { body = {detail: await response.text()}; }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function splitComma(value) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean);
}

function splitSemi(value) {
  return String(value || '').split(';').map(item => item.trim()).filter(Boolean);
}

function currentTaskId() {
  return document.querySelector('.task-row.active')?.dataset?.task || null;
}

async function refreshMainUi() {
  $('#refresh')?.click();
}

const planButton = $('#planObjective');
const planDialog = $('#missionDialog');
if (planButton && planDialog) {
  planButton.addEventListener('click', () => planDialog.showModal());
}

const missionForm = $('#missionForm');
if (missionForm) {
  missionForm.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(missionForm);
    const submit = missionForm.querySelector('button.primary');
    const original = submit?.textContent || 'Create plan';
    if (submit) { submit.disabled = true; submit.textContent = 'PLANNING…'; }
    try {
      const payload = {
        objective: data.get('objective'),
        files: splitComma(data.get('files')),
        acceptance: splitSemi(data.get('acceptance')),
        risk: Number(data.get('risk') || 0.5),
        token_budget: Number(data.get('token_budget') || 24000),
        max_tasks: Number(data.get('max_tasks') || 8),
      };
      const plan = await api('/api/missions/plan', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      planDialog.close();
      missionForm.reset();
      toast(`Planned ${plan.tasks.length} task${plan.tasks.length === 1 ? '' : 's'}`);
      await refreshMainUi();

      if (data.get('run_after') === 'on') {
        await runFleet();
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (submit) { submit.disabled = false; submit.textContent = original; }
    }
  });
}

async function runFleet() {
  const button = $('#runFleet');
  if (!button) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = '◉ ORCHESTRATING…';
  try {
    const result = await api('/api/orchestration/run', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    const accepted = result.accepted?.length || 0;
    const failed = (result.failed?.length || 0) + (result.rejected?.length || 0);
    toast(`Fleet ${result.run_id}: ${accepted} accepted${failed ? ` · ${failed} failed/rejected` : ''}`, failed > 0);
    await refreshMainUi();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

$('#runFleet')?.addEventListener('click', runFleet);

$('#explainRoute')?.addEventListener('click', async () => {
  const taskId = currentTaskId();
  if (!taskId) {
    toast('Select a READY task first', true);
    return;
  }
  const preview = $('#routePreview');
  try {
    const route = await api(`/api/tasks/${encodeURIComponent(taskId)}/route`);
    if (preview) {
      preview.hidden = false;
      preview.textContent = [
        `ROUTE // ${route.task_id}`,
        `agent   ${route.agent_name}`,
        `policy  ${route.policy}`,
        `score   ${Number(route.score).toFixed(2)}`,
        '',
        ...(route.reasons || []).map(reason => `• ${reason}`),
      ].join('\n');
    }
  } catch (error) {
    toast(error.message, true);
  }
});

$('#tasks')?.addEventListener('click', () => {
  const preview = $('#routePreview');
  if (preview) preview.hidden = true;
});
