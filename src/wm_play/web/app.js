const socket = window.io ? io({ transports: ['websocket', 'polling'] }) : null;

const els = {
  conn: document.getElementById('conn'),
  frame: document.getElementById('frame'),
  caption: document.getElementById('caption'),
  pause: document.getElementById('pause'),
  step: document.getElementById('step'),
  reset: document.getElementById('reset'),
  controller: document.getElementById('controller'),
  next: document.getElementById('next'),
  fps: document.getElementById('fps'),
  fpsValue: document.getElementById('fps-value'),
  horizon: document.getElementById('horizon'),
  record: document.getElementById('record'),
  export: document.getElementById('export'),
  snapshot: document.getElementById('snapshot'),
  deleteRecording: document.getElementById('delete-recording'),
  recordStatus: document.getElementById('record-status'),
  exportPaths: document.getElementById('export-paths'),
  statusLines: document.getElementById('status-lines'),
  ramPanel: document.getElementById('ram-panel'),
  ramWatch: document.getElementById('ram-watch'),
  ramAll: document.getElementById('ram-all'),
  toggleAllRam: document.getElementById('toggle-all-ram'),
  editDim: document.getElementById('edit-dim'),
  editValue: document.getElementById('edit-value'),
  applyOnce: document.getElementById('apply-once'),
  persist: document.getElementById('persist'),
  clearPersistent: document.getElementById('clear-persistent'),
};

let latest = {};
let allRamOpen = false;
let lastFrameAt = 0;
const pressedActionKeys = new Set();

const keyMap = {
  Backspace: 8,
  Tab: 9,
  Enter: 13,
  ' ': 32,
  '-': 45,
  '=': 61,
  '.': 46,
  ArrowUp: 1073741906,
  ArrowDown: 1073741905,
  ArrowRight: 1073741903,
  ArrowLeft: 1073741904,
  a: 97,
  d: 100,
  e: 101,
  m: 109,
  s: 115,
  w: 119,
};

function send(payload) {
  if (socket) {
    socket.emit('event', payload);
    return;
  }
  fetch('/event', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function pygameKey(event) {
  if (event.key in keyMap) return keyMap[event.key];
  if (event.key.length === 1) return event.key.toLowerCase().charCodeAt(0);
  return null;
}

function pygameMod(event) {
  let mod = 0;
  if (event.shiftKey) mod |= 3;
  if (event.ctrlKey) mod |= 192;
  if (event.altKey) mod |= 768;
  if (event.metaKey) mod |= 3072;
  return mod;
}

function isInputLike(target) {
  return target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement;
}

function dimLabel(dim) {
  return `${dim.name || `ram_${dim.dim}`} - RAM[${dim.dim}]`;
}

function renderStatus(data) {
  const lines = data.header_lines || [];
  els.statusLines.innerHTML = '';
  for (const line of lines) {
    const div = document.createElement('div');
    div.textContent = line;
    els.statusLines.appendChild(div);
  }
  els.caption.textContent = `${data.env_id || 'WM Play'} - ${data.paused ? 'Paused' : 'Running'} - action ${data.last_action_name || 'noop'}`;
  els.pause.textContent = data.paused ? 'Resume' : 'Pause';
  els.step.disabled = !data.paused;
  els.fps.value = String(data.fps || 15);
  els.fpsValue.textContent = String(data.fps || 15);
  const horizonEditable = !!data.horizon_editable;
  els.horizon.disabled = !horizonEditable;
  if (document.activeElement !== els.horizon) {
    els.horizon.value = data.horizon_display || '';
  }
  renderRecord(data);
}

function renderRecord(data) {
  const recording = !!data.recording;
  const pending = !!data.recording_pending;
  const frames = data.record_frame_count || 0;
  const actions = data.record_action_count || 0;
  els.record.textContent = recording ? 'Stop' : 'Record';
  els.export.disabled = recording || !pending;
  els.deleteRecording.disabled = recording || !pending;
  els.recordStatus.textContent = recording
    ? `recording ${actions} steps`
    : pending
      ? `pending ${frames} frames`
      : 'idle';
  const paths = data.last_exported_paths || [];
  els.exportPaths.innerHTML = '';
  for (const path of paths) {
    const row = document.createElement('div');
    row.className = 'export-path-row';
    const input = document.createElement('input');
    input.className = 'export-path-input';
    input.type = 'text';
    input.readOnly = true;
    input.value = path;
    input.onclick = () => input.select();
    input.onfocus = () => input.select();
    const copy = document.createElement('button');
    copy.className = 'btn export-copy';
    copy.type = 'button';
    copy.textContent = 'Copy';
    copy.onclick = async () => {
      input.select();
      try {
        await navigator.clipboard.writeText(path);
        copy.textContent = 'Copied';
        setTimeout(() => {
          copy.textContent = 'Copy';
        }, 900);
      } catch (err) {
        document.execCommand('copy');
      }
    };
    row.appendChild(input);
    row.appendChild(copy);
    els.exportPaths.appendChild(row);
  }
  if (data.last_export_error) {
    const div = document.createElement('div');
    div.className = 'export-error';
    div.textContent = data.last_export_error;
    els.exportPaths.appendChild(div);
  }
}

function renderRam(data) {
  const enabled = !!data.ram_enabled;
  els.ramPanel.classList.toggle('hidden', !enabled);
  if (!enabled) return;

  const dims = data.all_dims || [];
  const focus = data.focus_dims || [];
  const visible = allRamOpen ? dims : focus;
  els.toggleAllRam.textContent = allRamOpen ? 'Focus RAM' : 'All RAM';
  els.ramWatch.classList.toggle('hidden', allRamOpen);
  els.ramAll.classList.toggle('hidden', !allRamOpen);

  els.ramWatch.innerHTML = '';
  for (const dim of focus) {
    const row = document.createElement('button');
    row.className = `ram-row ${dim.persistent ? 'persistent' : ''}`;
    row.innerHTML = `<span>${dim.name}</span><code>RAM[${dim.dim}]</code><strong>${dim.formatted ?? dim.value}</strong>`;
    row.onclick = () => send({ type: 'select_dim', dim: dim.dim });
    els.ramWatch.appendChild(row);
  }

  els.ramAll.innerHTML = '';
  for (const dim of visible) {
    const cell = document.createElement('button');
    cell.className = `ram-cell ${dim.persistent ? 'persistent' : ''}`;
    cell.innerHTML = `<span>${dim.dim}</span><strong>${dim.formatted ?? dim.value}</strong><small>${dim.name}</small>`;
    cell.onclick = () => send({ type: 'select_dim', dim: dim.dim });
    els.ramAll.appendChild(cell);
  }

  const current = els.editDim.value;
  els.editDim.innerHTML = '';
  for (const dim of dims) {
    const opt = document.createElement('option');
    opt.value = String(dim.dim);
    opt.textContent = dimLabel(dim);
    els.editDim.appendChild(opt);
  }
  if (current) els.editDim.value = current;
  if (!els.editDim.value && data.selected_dim !== undefined) {
    els.editDim.value = String(data.selected_dim);
  }
  const canEdit = !!data.can_edit;
  els.editDim.disabled = !canEdit;
  els.editValue.disabled = !canEdit;
  els.applyOnce.disabled = !canEdit;
  els.persist.disabled = !canEdit;
  els.clearPersistent.disabled = !canEdit;
}

function handleData(data) {
  latest = { ...latest, ...data };
  if (data.image) {
    els.frame.src = `data:image/jpeg;base64,${data.image}`;
    lastFrameAt = Date.now();
  }
  renderStatus(latest);
  renderRam(latest);
}

async function fetchSnapshot() {
  try {
    const resp = await fetch('/snapshot', { cache: 'no-store' });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.ready) handleData(data);
  } catch (err) {
    // SocketIO is the normal transport; this is only a first-frame fallback.
  }
}

if (socket) {
  socket.on('connect', () => {
    els.conn.textContent = 'connected';
    els.conn.classList.add('connected');
    fetchSnapshot();
  });
  socket.on('disconnect', () => {
    els.conn.textContent = 'disconnected';
    els.conn.classList.remove('connected');
  });
  socket.on('state', handleData);
  socket.on('frame', handleData);
} else {
  els.conn.textContent = 'http polling';
  els.conn.classList.add('connected');
}

fetchSnapshot();
setInterval(() => {
  if (!socket || !lastFrameAt || Date.now() - lastFrameAt > 2000) fetchSnapshot();
}, 100);

els.pause.onclick = () => send({ type: 'set_paused', paused: !latest.paused });
els.step.onclick = () => send({ type: 'keydown', key: 101, mod: 0 });
els.reset.onclick = () => send({ type: 'keydown', key: 13, mod: 0 });
els.controller.onclick = () => {
  els.controller.blur();
  send({ type: 'keydown', key: 109, mod: 0 });
};
els.next.onclick = () => send({ type: 'keydown', key: 1073741903, mod: 0 });
els.fps.oninput = () => {
  const fps = Number.parseInt(els.fps.value, 10);
  els.fpsValue.textContent = String(fps);
  send({ type: 'set_fps', fps });
};
function commitHorizon() {
  if (els.horizon.disabled) return;
  const horizon = Number.parseInt(els.horizon.value, 10);
  if (Number.isFinite(horizon) && horizon >= 1) {
    send({ type: 'set_horizon', horizon });
  }
}
els.horizon.onchange = commitHorizon;
els.horizon.onkeydown = (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    commitHorizon();
    els.horizon.blur();
  }
};
els.record.onclick = () => send({ type: 'toggle_recording' });
els.export.onclick = () => send({ type: 'export_now' });
els.snapshot.onclick = () => send({ type: 'export_snapshot' });
els.deleteRecording.onclick = () => send({ type: 'delete_recording' });
els.toggleAllRam.onclick = () => {
  allRamOpen = !allRamOpen;
  renderRam(latest);
};
els.applyOnce.onclick = () => {
  send({ type: 'apply_dim_value', dim: Number(els.editDim.value), value: Number(els.editValue.value) });
};
els.persist.onclick = () => {
  send({ type: 'persist_dim_value', dim: Number(els.editDim.value), value: Number(els.editValue.value) });
};
els.clearPersistent.onclick = () => send({ type: 'clear_persistent' });

window.addEventListener('keydown', (event) => {
  if (isInputLike(event.target)) return;
  const key = pygameKey(event);
  if (key === null) return;
  if ([' ', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault();
  }
  if ([32, 97, 100, 115, 119].includes(key)) pressedActionKeys.add(key);
  send({ type: 'keydown', key, mod: pygameMod(event) });
});
window.addEventListener('keyup', (event) => {
  if (isInputLike(event.target)) return;
  const key = pygameKey(event);
  if (key === null) return;
  pressedActionKeys.delete(key);
  send({ type: 'keyup', key, mod: pygameMod(event) });
});

function releaseActionKeys() {
  for (const key of pressedActionKeys) {
    send({ type: 'keyup', key, mod: 0 });
  }
  pressedActionKeys.clear();
  send({ type: 'clear_keys' });
}

window.addEventListener('blur', releaseActionKeys);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) releaseActionKeys();
});
