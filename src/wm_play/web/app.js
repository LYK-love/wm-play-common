const socket = io({ transports: ['websocket', 'polling'] });

const els = {
  conn: document.getElementById('conn'),
  frame: document.getElementById('frame'),
  caption: document.getElementById('caption'),
  pause: document.getElementById('pause'),
  step: document.getElementById('step'),
  reset: document.getElementById('reset'),
  controller: document.getElementById('controller'),
  prev: document.getElementById('prev'),
  next: document.getElementById('next'),
  fps: document.getElementById('fps'),
  fpsValue: document.getElementById('fps-value'),
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
  socket.emit('event', payload);
}

function pygameKey(event) {
  if (event.key in keyMap) return keyMap[event.key];
  if (event.key.length === 1) return event.key.toLowerCase().charCodeAt(0);
  return null;
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

fetchSnapshot();
setInterval(() => {
  if (!lastFrameAt || Date.now() - lastFrameAt > 2000) fetchSnapshot();
}, 1000);

els.pause.onclick = () => send({ type: 'set_paused', paused: !latest.paused });
els.step.onclick = () => send({ type: 'keydown', key: 101, mod: 0 });
els.reset.onclick = () => send({ type: 'keydown', key: 13, mod: 0 });
els.controller.onclick = () => send({ type: 'keydown', key: 109, mod: 0 });
els.prev.onclick = () => send({ type: 'keydown', key: 1073741904, mod: 0 });
els.next.onclick = () => send({ type: 'keydown', key: 1073741903, mod: 0 });
els.fps.oninput = () => {
  const fps = Number.parseInt(els.fps.value, 10);
  els.fpsValue.textContent = String(fps);
  send({ type: 'set_fps', fps });
};
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
  send({ type: 'keydown', key, mod: 0 });
});
window.addEventListener('keyup', (event) => {
  if (isInputLike(event.target)) return;
  const key = pygameKey(event);
  if (key === null) return;
  send({ type: 'keyup', key, mod: 0 });
});
