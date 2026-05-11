"""
Multi-Agent System v2 — Web UI

FastAPI + SSE streaming with:
  - Project folder input + task prompt
  - Dynamic agent cards (spawn as they appear)
  - Per-agent messaging
  - Streaming output log
  - Plan approval modal
  - Rollback button
"""
import asyncio
import json
import os
import queue
import threading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

from config import MODEL, MODELS
from orchestrator import run_orchestrator
from checkpoint import rollback_to_checkpoint

app = FastAPI()

# ── Session state ────────────────────────────────────────────────────────────
_active_plan_q: list = [None]
_agent_queues: dict = {}
_checkpoint_hash: list = [None]
_project_path: list = [None]


# ── HTML ─────────────────────────────────────────────────────────────────────

def _build_html() -> str:
    model_opts = "\n".join(
        f'<option value="{m}"{"selected" if m == MODEL else ""}>{m}</option>'
        for m in MODELS
    )

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi-Agent System v2</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
  --border: #30363d; --text: #e6edf3; --dim: #8b949e;
  --accent: #58a6ff; --green: #3fb950; --yellow: #d29922;
  --red: #f85149; --orange: #f78c6c; --purple: #bc8cff;
}
body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; }

/* ── Header ───────────────────── */
.header { background:var(--bg2); border-bottom:1px solid var(--border); padding:16px 24px; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.header h1 { font-size:18px; font-weight:600; color:var(--accent); white-space:nowrap; }
.header select, .header input[type=text] {
  background:var(--bg3); border:1px solid var(--border); color:var(--text);
  padding:6px 12px; border-radius:6px; font-size:13px;
}
.header input[type=text] { width:340px; }
.header select { width:200px; }

/* ── Main Layout ──────────────── */
.main { display:flex; height:calc(100vh - 60px); }

/* ── Left: Agent Panel ────────── */
.agent-panel {
  width:360px; min-width:300px; background:var(--bg2);
  border-right:1px solid var(--border); overflow-y:auto;
  padding:12px; display:flex; flex-direction:column; gap:8px;
}
.agent-panel-header { font-size:13px; color:var(--dim); text-transform:uppercase; letter-spacing:1px; padding:4px 0 8px; }
.agent-panel-empty { color:var(--dim); font-size:13px; padding:20px 0; text-align:center; }

.agent-card {
  background:var(--bg3); border:1px solid var(--border); border-radius:8px;
  padding:12px; transition:border-color 0.2s;
}
.agent-card.working { border-color:var(--accent); }
.agent-card.done { border-color:var(--green); }
.agent-card.blocked { border-color:var(--red); }

.agent-card-top { display:flex; align-items:center; gap:8px; margin-bottom:6px; }
.agent-icon { width:28px; height:28px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:14px; color:#fff; font-weight:700; }
.agent-name { font-size:14px; font-weight:600; }
.agent-type-badge {
  font-size:10px; padding:2px 6px; border-radius:10px;
  background:var(--bg); color:var(--dim); margin-left:auto;
  text-transform:uppercase; letter-spacing:0.5px;
}
.agent-status { font-size:12px; color:var(--dim); margin-bottom:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.agent-status .dot { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:4px; }
.dot-working { background:var(--accent); }
.dot-done { background:var(--green); }
.dot-blocked { background:var(--red); }
.dot-starting { background:var(--yellow); }

.agent-action { font-size:11px; color:var(--dim); font-family:'Cascadia Code','Fira Code',monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:6px; }

.agent-messages { max-height:100px; overflow-y:auto; font-size:12px; margin-bottom:6px; }
.agent-msg { padding:2px 0; border-bottom:1px solid rgba(255,255,255,0.04); }
.agent-msg.from-user { color:var(--accent); }
.agent-msg.from-agent { color:var(--green); }

.agent-input-row { display:flex; gap:4px; }
.agent-input-row input {
  flex:1; background:var(--bg); border:1px solid var(--border); color:var(--text);
  padding:4px 8px; border-radius:4px; font-size:12px;
}
.agent-input-row button {
  background:var(--accent); color:#fff; border:none; padding:4px 10px;
  border-radius:4px; cursor:pointer; font-size:12px; font-weight:600;
}
.agent-input-row button:hover { opacity:0.85; }

/* ── Right: Output + Input ────── */
.content { flex:1; display:flex; flex-direction:column; }

/* Task input area */
.task-area { padding:16px 24px; border-bottom:1px solid var(--border); background:var(--bg2); }
.task-area label { font-size:12px; color:var(--dim); display:block; margin-bottom:4px; }
.task-area textarea {
  width:100%; min-height:120px; background:var(--bg); border:1px solid var(--border);
  color:var(--text); padding:12px; border-radius:8px; font-size:14px;
  font-family:inherit; resize:vertical; line-height:1.5;
}
.task-area textarea:focus { outline:none; border-color:var(--accent); }
.task-row { display:flex; gap:8px; margin-top:8px; align-items:center; }
.btn-start {
  background:var(--green); color:#fff; border:none; padding:10px 28px;
  border-radius:6px; font-size:14px; font-weight:600; cursor:pointer;
  transition:opacity 0.2s;
}
.btn-start:hover { opacity:0.85; }
.btn-start:disabled { opacity:0.4; cursor:not-allowed; }
.btn-rollback {
  background:var(--red); color:#fff; border:none; padding:8px 20px;
  border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;
  display:none;
}
.btn-rollback:hover { opacity:0.85; }

/* Phase bar */
.phase-bar {
  display:flex; gap:0; background:var(--bg3); border-bottom:1px solid var(--border);
  font-size:12px; overflow-x:auto;
}
.phase-item {
  padding:8px 16px; color:var(--dim); border-right:1px solid var(--border);
  white-space:nowrap; transition:all 0.3s;
}
.phase-item.active { color:var(--accent); background:rgba(88,166,255,0.08); font-weight:600; }
.phase-item.done { color:var(--green); }

/* Stream output */
.stream-area { flex:1; overflow-y:auto; padding:16px 24px; font-family:'Cascadia Code','Fira Code',monospace; font-size:13px; line-height:1.6; }
.stream-line { margin-bottom:2px; }
.stream-line .agent-tag { font-weight:700; margin-right:6px; }
.stream-line .tool-name { color:var(--purple); }
.stream-line .dim { color:var(--dim); }
.stream-line .error { color:var(--red); }

/* ── Plan Modal ───────────────── */
.modal-overlay {
  display:none; position:fixed; top:0; left:0; width:100%; height:100%;
  background:rgba(0,0,0,0.7); z-index:100; justify-content:center; align-items:center;
}
.modal-overlay.visible { display:flex; }
.modal {
  background:var(--bg2); border:1px solid var(--border); border-radius:12px;
  max-width:750px; width:90%; max-height:85vh; overflow-y:auto; padding:28px;
}
.modal h2 { font-size:18px; margin-bottom:16px; color:var(--accent); }
.modal pre {
  background:var(--bg); padding:16px; border-radius:8px; font-size:13px;
  overflow-x:auto; white-space:pre-wrap; word-break:break-word; line-height:1.5;
  margin-bottom:16px; border:1px solid var(--border);
}
.modal-actions { display:flex; gap:12px; justify-content:flex-end; }
.modal-actions button {
  padding:10px 24px; border:none; border-radius:6px; font-size:14px;
  font-weight:600; cursor:pointer;
}
.btn-approve { background:var(--green); color:#fff; }
.btn-reject { background:var(--red); color:#fff; }

/* ── Parallel Toggle ──────────── */
.toggle-label { display:flex; align-items:center; gap:8px; cursor:pointer; font-size:13px; color:var(--dim); user-select:none; white-space:nowrap; }
.toggle-label input[type=checkbox] { display:none; }
.toggle-track { width:36px; height:20px; background:var(--bg3); border:1px solid var(--border); border-radius:10px; position:relative; transition:background 0.2s; flex-shrink:0; }
.toggle-track::after { content:''; position:absolute; top:2px; left:2px; width:14px; height:14px; background:var(--dim); border-radius:50%; transition:left 0.2s, background 0.2s; }
.toggle-label input:checked + .toggle-track { background:var(--accent); border-color:var(--accent); }
.toggle-label input:checked + .toggle-track::after { left:18px; background:#fff; }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <h1>Multi-Agent System v2</h1>
  <input type="text" id="projectPath" placeholder="Project folder path (e.g. C:/my-project)">
  <select id="modelSelect">""" + model_opts + """</select>
  <label class="toggle-label">
    <input type="checkbox" id="parallelToggle">
    <span class="toggle-track"></span>
    Parallel Agents
  </label>
</div>

<!-- Main -->
<div class="main">
  <!-- Agent Panel -->
  <div class="agent-panel">
    <div class="agent-panel-header">Agents</div>
    <div id="agentCards" class="agent-panel-empty">No agents spawned yet</div>
  </div>

  <!-- Content -->
  <div class="content">
    <div class="task-area">
      <label>Task Prompt</label>
      <textarea id="taskInput" placeholder="Describe everything you need. Be thorough — the agents will work autonomously based on this prompt."></textarea>
      <div class="task-row">
        <button class="btn-start" id="btnStart" onclick="startTask()">Start</button>
        <button class="btn-rollback" id="btnRollback" onclick="doRollback()">Rollback to Checkpoint</button>
        <span id="statusText" style="font-size:12px;color:var(--dim);margin-left:auto;"></span>
      </div>
    </div>

    <div class="phase-bar" id="phaseBar"></div>

    <div class="stream-area" id="streamArea"></div>
  </div>
</div>

<!-- Plan Approval Modal -->
<div class="modal-overlay" id="planModal">
  <div class="modal">
    <h2>Spawn Plan — Review & Approve</h2>
    <pre id="planContent"></pre>
    <div class="modal-actions">
      <button class="btn-reject" onclick="rejectPlan()">Reject</button>
      <button class="btn-approve" onclick="approvePlan()">Approve & Start</button>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let evtSource = null;
const agentStates = {};
const COLORS = {
  code_analyst: '#79c0ff',
  analyst: '#79c0ff',
  frontend: '#f78c6c',
  backend: '#3fb950',
  orchestrator: '#bc8cff',
};
const ICONS = {
  code_analyst: 'AN',
  analyst: 'AN',
  frontend: 'FE',
  backend: 'BE',
};

function startTask() {
  const task = $('#taskInput').value.trim();
  const projectPath = $('#projectPath').value.trim();
  if (!task) return alert('Enter a task prompt.');
  if (!projectPath) return alert('Enter the project folder path.');

  $('#btnStart').disabled = true;
  $('#btnRollback').style.display = 'none';
  $('#streamArea').innerHTML = '';
  $('#agentCards').innerHTML = '';
  $('#agentCards').classList.add('agent-panel-empty');
  $('#agentCards').textContent = 'Waiting for agents...';
  $('#phaseBar').innerHTML = '';
  $('#statusText').textContent = 'Running...';

  const model = $('#modelSelect').value;

  fetch('/api/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task, model, project_path: projectPath, parallel_mode: $('#parallelToggle').checked}),
  });

  // Start SSE
  if (evtSource) evtSource.close();
  evtSource = new EventSource('/api/stream');
  evtSource.onmessage = e => {
    try { handleEvent(JSON.parse(e.data)); }
    catch(err) { console.error('SSE parse error:', err); }
  };
  evtSource.onerror = () => {
    $('#statusText').textContent = 'Stream ended.';
    evtSource.close();
  };
}

function handleEvent(ev) {
  switch(ev.type) {
    case 'phase_change':
      addPhase(ev.phase_name || ev.phase, ev.description || '');
      appendStream(`[Phase] ${ev.phase_name || ev.phase}: ${ev.description || ''}`, 'var(--accent)');
      break;

    case 'plan_ready':
      showPlanModal(ev.plan);
      break;

    case 'plan_approved':
      appendStream('[Plan approved — spawning agents]', 'var(--green)');
      break;

    case 'plan_rejected':
      appendStream('[Plan rejected by user]', 'var(--red)');
      $('#btnStart').disabled = false;
      $('#statusText').textContent = 'Plan rejected.';
      break;

    case 'planner_reasoning':
      appendStream('[Planner] ' + (ev.text || '').substring(0, 300) + '...', 'var(--purple)');
      break;

    case 'checkpoint_created':
      appendStream('[Checkpoint created: ' + ev.hash + ']', 'var(--dim)');
      break;

    case 'checkpoint_skipped':
      appendStream('[Checkpoint skipped: ' + (ev.reason || '') + ']', 'var(--dim)');
      break;

    case 'agent_start':
      registerAgent(ev.agent, ev.agent_type, ev.agent_name, ev.task || '');
      appendStream(`[${ev.agent}] Started — ${ev.task || ''}`.substring(0, 200), agentColor(ev.agent_type));
      break;

    case 'agent_step':
      updateAgentStatus(ev.agent, 'WORKING', `Step ${ev.n}`);
      break;

    case 'agent_tool_call':
      updateAgentStatus(ev.agent, 'WORKING', `${ev.name}(${(ev.args_str||'').substring(0,60)})`);
      appendStream(`[${ev.agent}] <span class="tool-name">${ev.name}</span>(${escHtml((ev.args_str||'').substring(0,80))})`, agentColor(ev.agent_type));
      break;

    case 'agent_tool_result':
      // Only show first 150 chars in stream
      const preview = (ev.preview || ev.text || '').substring(0, 150);
      appendStream(`<span class="dim">  → ${escHtml(preview)}</span>`, null);
      break;

    case 'agent_done':
      updateAgentStatus(ev.agent, 'DONE', 'Complete');
      appendStream(`[${ev.agent}] Done`, 'var(--green)');
      break;

    case 'agent_error':
      updateAgentStatus(ev.agent, 'ERROR', ev.error || 'Error');
      appendStream(`[${ev.agent}] <span class="error">Error: ${escHtml(ev.error || '')}</span>`, null);
      break;

    case 'agent_message_user':
      addAgentMessage(ev.agent, ev.message, 'from-agent');
      appendStream(`[${ev.agent} → you] ${escHtml(ev.message || '')}`, 'var(--green)');
      break;

    case 'bus_event':
      handleBusEvent(ev.event);
      break;

    case 'final':
      appendStream('\\n━━━ DELIVERY SUMMARY ━━━\\n' + escHtml(ev.text || ''), 'var(--accent)');
      $('#btnStart').disabled = false;
      $('#statusText').textContent = 'Complete.';
      // Show rollback if checkpoint exists
      if (ev.checkpoint_hash) {
        $('#btnRollback').style.display = 'inline-block';
      }
      break;

    case 'rollback_result':
      appendStream('[Rollback] ' + escHtml(ev.message || ''), ev.success ? 'var(--green)' : 'var(--red)');
      break;

    case 'error':
      appendStream('<span class="error">[Error] ' + escHtml(ev.text || '') + '</span>', null);
      $('#btnStart').disabled = false;
      $('#statusText').textContent = 'Error.';
      break;
  }
}

function handleBusEvent(busEv) {
  if (!busEv) return;
  const t = busEv.event_type;
  if (t === 'direct_message' && busEv.target === 'user') {
    // Agent messaging user already handled via agent_message_user
    return;
  }
  // We don't log all bus events to stream to avoid noise
}

// ── Agent Cards ─────────────────

function registerAgent(id, type, name, task) {
  if (agentStates[id]) return;
  agentStates[id] = {id, type, name, task, status: 'STARTING', action: '', messages: []};

  const container = $('#agentCards');
  if (container.classList.contains('agent-panel-empty')) {
    container.classList.remove('agent-panel-empty');
    container.innerHTML = '';
  }

  const card = document.createElement('div');
  card.className = 'agent-card working';
  card.id = 'card-' + id;
  card.innerHTML = `
    <div class="agent-card-top">
      <div class="agent-icon" style="background:${agentColor(type)}">${ICONS[type] || '??'}</div>
      <span class="agent-name">${escHtml(name || id)}</span>
      <span class="agent-type-badge">${escHtml(type)}</span>
    </div>
    <div class="agent-status" id="status-${id}"><span class="dot dot-starting"></span>Starting...</div>
    <div class="agent-action" id="action-${id}"></div>
    <div class="agent-messages" id="msgs-${id}"></div>
    <div class="agent-input-row">
      <input type="text" id="input-${id}" placeholder="Message ${name || id}..." onkeydown="if(event.key==='Enter')sendAgentMsg('${id}')">
      <button onclick="sendAgentMsg('${id}')">Send</button>
    </div>
  `;
  container.appendChild(card);
}

function updateAgentStatus(id, status, action) {
  const state = agentStates[id];
  if (!state) return;
  state.status = status;
  state.action = action || '';

  const card = document.getElementById('card-' + id);
  if (!card) return;

  card.className = 'agent-card ' + status.toLowerCase();

  const dotClass = {WORKING:'dot-working', DONE:'dot-done', ERROR:'dot-blocked', BLOCKED:'dot-blocked', STARTING:'dot-starting'}[status] || 'dot-starting';
  const statusEl = document.getElementById('status-' + id);
  if (statusEl) statusEl.innerHTML = `<span class="dot ${dotClass}"></span>${status}`;

  const actionEl = document.getElementById('action-' + id);
  if (actionEl) actionEl.textContent = action;
}

function addAgentMessage(id, text, cls) {
  const msgsEl = document.getElementById('msgs-' + id);
  if (!msgsEl) return;
  const div = document.createElement('div');
  div.className = 'agent-msg ' + cls;
  div.textContent = (cls === 'from-user' ? 'You: ' : 'Agent: ') + text;
  msgsEl.appendChild(div);
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function sendAgentMsg(id) {
  const input = document.getElementById('input-' + id);
  if (!input) return;
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  addAgentMessage(id, msg, 'from-user');

  fetch('/api/message/' + id, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: msg}),
  });
}

// ── Plan Modal ──────────────────

function showPlanModal(plan) {
  $('#planContent').textContent = JSON.stringify(plan, null, 2);
  $('#planModal').classList.add('visible');
}

function approvePlan() {
  $('#planModal').classList.remove('visible');
  fetch('/api/approve', {method: 'POST'});
}

function rejectPlan() {
  $('#planModal').classList.remove('visible');
  fetch('/api/reject', {method: 'POST'});
}

// ── Rollback ────────────────────

function doRollback() {
  if (!confirm('This will undo all agent changes. Continue?')) return;
  fetch('/api/rollback', {method: 'POST'});
  $('#btnRollback').style.display = 'none';
}

// ── Phase Bar ───────────────────

function addPhase(name, desc) {
  const bar = $('#phaseBar');
  // Mark previous as done
  bar.querySelectorAll('.phase-item.active').forEach(el => {
    el.classList.remove('active');
    el.classList.add('done');
  });
  const item = document.createElement('div');
  item.className = 'phase-item active';
  item.textContent = name;
  item.title = desc;
  bar.appendChild(item);
}

// ── Stream ──────────────────────

function appendStream(html, color) {
  const area = $('#streamArea');
  const div = document.createElement('div');
  div.className = 'stream-line';
  if (color) div.style.color = color;
  div.innerHTML = html;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function agentColor(type) {
  return COLORS[type] || 'var(--text)';
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
</script>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return _build_html()


@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json()
    task = body.get("task", "")
    model = body.get("model", MODEL)
    project_path = body.get("project_path", "")
    parallel_mode = bool(body.get("parallel_mode", False))

    _project_path[0] = project_path

    # Create fresh plan approval queue
    _active_plan_q[0] = queue.Queue()

    # Run orchestrator in background thread
    def _worker():
        result = run_orchestrator(
            task=task,
            model=model,
            on_event=_push_event,
            plan_approval_fn=_plan_approval_fn,
            project_path=project_path,
            parallel_mode=parallel_mode,
        )
        # Store checkpoint hash and agent queues
        if isinstance(result, dict):
            _checkpoint_hash[0] = result.get("checkpoint_hash")
            _agent_queues.update(result.get("agent_queues", {}))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return {"status": "started"}


# ── SSE Stream ───────────────────────────────────────────────────────────────

_sse_queue: queue.Queue = queue.Queue()


def _push_event(event: dict):
    _sse_queue.put(event)


@app.get("/api/stream")
async def api_stream():
    async def generate():
        while True:
            try:
                event = _sse_queue.get(timeout=0.1)
                yield f"data: {json.dumps(event, default=str)}\n\n"
                # Stop streaming after final
                if event.get("type") == "final":
                    break
            except queue.Empty:
                # Send keepalive
                await asyncio.sleep(0.1)
                yield ": keepalive\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Plan Approval ────────────────────────────────────────────────────────────

def _plan_approval_fn(plan: dict) -> bool:
    """Block until user approves or rejects."""
    q = _active_plan_q[0]
    if q is None:
        return True
    try:
        result = q.get(timeout=300)  # 5 min timeout
        return result
    except queue.Empty:
        return False


@app.post("/api/approve")
async def api_approve():
    q = _active_plan_q[0]
    if q:
        q.put(True)
    return {"status": "approved"}


@app.post("/api/reject")
async def api_reject():
    q = _active_plan_q[0]
    if q:
        q.put(False)
    return {"status": "rejected"}


# ── Agent Messaging ──────────────────────────────────────────────────────────

@app.post("/api/message/{agent_id}")
async def api_message(agent_id: str, request: Request):
    body = await request.json()
    message = body.get("message", "")
    q = _agent_queues.get(agent_id)
    if q:
        q.put(message)
        return {"status": "sent"}
    return {"status": "agent_not_found", "error": f"No queue for {agent_id}"}


@app.post("/api/broadcast")
async def api_broadcast(request: Request):
    body = await request.json()
    message = body.get("message", "")
    for aid, q in _agent_queues.items():
        q.put(message)
    return {"status": "broadcast", "count": len(_agent_queues)}


# ── Rollback ─────────────────────────────────────────────────────────────────

@app.post("/api/rollback")
async def api_rollback():
    ch = _checkpoint_hash[0]
    pp = _project_path[0]
    if not ch or not pp:
        _push_event({"type": "rollback_result", "success": False, "message": "No checkpoint available."})
        return {"status": "no_checkpoint"}

    success = rollback_to_checkpoint(pp, ch)
    msg = f"Rolled back to {ch}" if success else f"Rollback failed for {ch}"
    _push_event({"type": "rollback_result", "success": success, "message": msg})
    return {"status": "ok" if success else "failed"}


# ── Run ──────────────────────────────────────────────────────────────────────

def start_ui(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="warning")
