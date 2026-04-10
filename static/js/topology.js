'use strict';
/* ═══════════════════════════════════════════════════════════════
   FoxEx Network Monitor – Topology Editor (Konva.js)
═══════════════════════════════════════════════════════════════ */

const ICON_SIZE = 48;
const MIN_ZOOM  = 0.3;
const MAX_ZOOM  = 3.0;
const ZOOM_STEP = 0.15;

let stage, bgLayer, connLayer, shapeLayer, deviceLayer;
let currentMode   = 'select';
let connectSource = null;
let selectedNodeId  = null;
let selectedEdgeIdx = null;
let selectedShapeId = null;
let transformer     = null;

let nodes  = {};
let edges  = [];
let shapes = [];
let isDirty = false;

// ── Snap to Grid ──────────────────────────────────────────────
const GRID_SIZE = 40;
let snapEnabled = false;

// ── Multi-Select ──────────────────────────────────────────────
let multiSelected        = [];   // [{type:'node'|'shape', id}]
let _dragSelecting       = false;
let _dragSelStart        = {x: 0, y: 0};
let _dragSelRect         = null;
let _multiDragAnchorId   = null;
let _multiDragAnchorType = null;
let _multiDragStarts     = new Map();

// middle-mouse pan state
let _mmPanning = false;
let _mmStart = {x:0,y:0}, _mmOrigin = {x:0,y:0};

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initStage();
  await loadTopology();
  initPalette();
  initShapePalette();
  window.addEventListener('resize', resizeStage);
});

// ── Stage ─────────────────────────────────────────────────────
function initStage() {
  const wrapper = document.getElementById('topology-canvas');
  stage = new Konva.Stage({ container: 'topology-canvas', width: wrapper.clientWidth, height: wrapper.clientHeight });

  bgLayer     = new Konva.Layer({ listening: false });
  connLayer   = new Konva.Layer();
  shapeLayer  = new Konva.Layer();
  deviceLayer = new Konva.Layer();
  stage.add(bgLayer, connLayer, shapeLayer, deviceLayer);

  transformer = new Konva.Transformer({
    rotateEnabled: true,
    rotationSnaps: [0, 45, 90, 135, 180, 225, 270, 315],
    borderStroke: '#ffc107', borderStrokeWidth: 1.5,
    anchorFill: '#ffc107', anchorStroke: '#111318', anchorSize: 8,
    keepRatio: false,
  });
  shapeLayer.add(transformer);

  stage.on('click tap', (e) => {
    if (e.target === stage) {
      if (currentMode === 'text') {
        const rect = stage.container().getBoundingClientRect();
        const sx = (e.evt.clientX - rect.left - stage.x()) / stage.scaleX();
        const sy = (e.evt.clientY - rect.top  - stage.y()) / stage.scaleY();
        promptNewText(sx, sy);
      } else {
        deselectAll();
        if (currentMode === 'connect') cancelConnect();
      }
    }
  });

  stage.container().addEventListener('wheel', (e) => {
    e.preventDefault();
    applyZoom(e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP, { x: e.clientX, y: e.clientY });
  }, { passive: false });

  // ── Middle-mouse pan (always available) ──────────────────────
  stage.container().addEventListener('mousedown', (e) => {
    if (e.button !== 1) return;
    e.preventDefault();
    _mmPanning = true;
    _mmStart  = {x: e.clientX, y: e.clientY};
    _mmOrigin = {x: stage.x(), y: stage.y()};
    stage.container().style.cursor = 'grabbing';
  });
  window.addEventListener('mousemove', (e) => {
    if (!_mmPanning) return;
    stage.x(_mmOrigin.x + (e.clientX - _mmStart.x));
    stage.y(_mmOrigin.y + (e.clientY - _mmStart.y));
    stage.batchDraw();
  });
  window.addEventListener('mouseup', (e) => {
    if (_mmPanning && e.button === 1) {
      _mmPanning = false;
      stage.container().style.cursor = currentMode === 'pan' ? 'grab' : 'default';
    }
  });
  stage.container().addEventListener('auxclick', (e) => { if (e.button === 1) e.preventDefault(); });

  // ── Stage drag events for pan mode cursor ─────────────────────
  stage.on('dragstart', () => { if (currentMode === 'pan') stage.container().style.cursor = 'grabbing'; });
  stage.on('dragend',   () => { if (currentMode === 'pan') stage.container().style.cursor = 'grab'; });

  // ── Drag-rectangle multi-select ───────────────────────────────
  stage.on('mousedown', (e) => {
    if (currentMode !== 'select' || e.target !== stage || e.evt.button !== 0) return;
    _dragSelecting = true;
    _dragSelStart  = _stageLocalPos();
    _dragSelRect   = new Konva.Rect({
      x: _dragSelStart.x, y: _dragSelStart.y, width: 0, height: 0,
      stroke: '#ffc107', strokeWidth: 1, dash: [5, 4],
      fill: 'rgba(255,193,7,0.07)', listening: false,
    });
    shapeLayer.add(_dragSelRect);
    shapeLayer.batchDraw();
  });

  stage.on('mousemove', () => {
    if (!_dragSelecting || !_dragSelRect) return;
    const pos = _stageLocalPos();
    _dragSelRect.x(Math.min(pos.x, _dragSelStart.x));
    _dragSelRect.y(Math.min(pos.y, _dragSelStart.y));
    _dragSelRect.width(Math.abs(pos.x  - _dragSelStart.x));
    _dragSelRect.height(Math.abs(pos.y - _dragSelStart.y));
    shapeLayer.batchDraw();
  });

  stage.on('mouseup', () => {
    if (!_dragSelecting) return;
    _dragSelecting = false;
    if (!_dragSelRect) return;
    const rx1 = _dragSelRect.x(), ry1 = _dragSelRect.y();
    const rx2 = rx1 + _dragSelRect.width(), ry2 = ry1 + _dragSelRect.height();
    _dragSelRect.destroy(); _dragSelRect = null; shapeLayer.batchDraw();
    if (rx2 - rx1 < 5 && ry2 - ry1 < 5) return;
    const found = [];
    Object.entries(nodes).forEach(([nid, n]) => {
      const cx = n.group.x() + ICON_SIZE / 2, cy = n.group.y() + ICON_SIZE / 2;
      if (cx >= rx1 && cx <= rx2 && cy >= ry1 && cy <= ry2) found.push({type: 'node', id: parseInt(nid)});
    });
    shapes.forEach(s => {
      const sx = s.shape.x(), sy = s.shape.y();
      if (sx >= rx1 && sx <= rx2 && sy >= ry1 && sy <= ry2) found.push({type: 'shape', id: s.id});
    });
    if (found.length > 1) {
      setMultiSelection(found);
    } else if (found.length === 1) {
      const item = found[0];
      if (item.type === 'node') { selectNode(item.id); if (nodes[item.id]) showDetailPanel(nodes[item.id].device); }
      else selectShape(item.id);
    }
  });
}

function resizeStage() {
  const w = document.getElementById('topology-canvas');
  stage.width(w.clientWidth);
  stage.height(w.clientHeight);
}

// ── Load ──────────────────────────────────────────────────────
async function loadTopology() {
  const r    = await fetch('/api/topology');
  const data = await r.json();
  deviceLayer.destroyChildren();
  connLayer.destroyChildren();
  nodes = {}; edges = []; shapes = [];

  for (const node of (data.nodes  || [])) await addNodeToCanvas(node.device, node.x, node.y, false);
  for (const edge of (data.edges  || [])) addEdgeToCanvas(edge.source_device_id, edge.target_device_id, edge, false);
  for (const s    of (data.shapes || [])) addShapeToCanvas(s, false);

  deviceLayer.draw(); connLayer.draw(); shapeLayer.draw();
  updatePaletteState();
}

// ── Device Nodes ──────────────────────────────────────────────
async function addNodeToCanvas(device, x, y, autosave = true) {
  const imgEl = await loadImage(iconUrl(device));
  const group = new Konva.Group({ x, y, draggable: true, id: `node-${device.id}` });

  const selRect = new Konva.Rect({ x:-4, y:-4, width:ICON_SIZE+8, height:ICON_SIZE+8, cornerRadius:6, stroke:'#ffc107', strokeWidth:2, fill:'rgba(255,193,7,0.08)', visible:false });
  const img     = new Konva.Image({ image:imgEl, width:ICON_SIZE, height:ICON_SIZE });
  const dot     = new Konva.Circle({ x:ICON_SIZE-6, y:6, radius:5, fill:statusColor(device.status), stroke:'#0f1117', strokeWidth:1.5 });
  const name    = new Konva.Text({ text:device.name, x:-30, y:ICON_SIZE+5, width:ICON_SIZE+60, align:'center', fontSize:11, fill:'#c9cdd8', fontFamily:'Segoe UI, sans-serif' });
  const ip      = new Konva.Text({ text:device.ip_address, x:-30, y:ICON_SIZE+18, width:ICON_SIZE+60, align:'center', fontSize:9, fill:'#6c7293', fontFamily:'monospace' });

  group.add(selRect, img, dot, name, ip);
  deviceLayer.add(group);

  group.on('mouseenter', () => { stage.container().style.cursor = currentMode==='connect'&&connectSource!==device.id ? 'crosshair' : 'pointer'; if (selectedNodeId!==device.id) { selRect.visible(true); selRect.stroke('#4a9eff'); selRect.fill('rgba(74,158,255,0.06)'); deviceLayer.draw(); } });
  group.on('mouseleave', () => { stage.container().style.cursor='default'; if (selectedNodeId!==device.id) { selRect.visible(false); deviceLayer.draw(); } });
  group.on('click tap', (e) => {
    e.cancelBubble = true;
    if (currentMode === 'pan') return;
    if (currentMode === 'connect') { handleConnectClick(device.id); return; }
    if (e.evt.shiftKey) { toggleMultiSelectItem({type:'node', id:device.id}); return; }
    if (multiSelected.length > 0) clearMultiSelection();
    selectNode(device.id); showDetailPanel(device);
  });
  group.on('dragstart', () => {
    group.moveToTop();
    if (multiSelected.find(m => m.type === 'node' && m.id === device.id)) {
      _multiDragAnchorId = device.id; _multiDragAnchorType = 'node';
      _multiDragStarts.clear();
      multiSelected.forEach(m => {
        if (m.type === 'node' && nodes[m.id]) _multiDragStarts.set(`node_${m.id}`, {x: nodes[m.id].group.x(), y: nodes[m.id].group.y()});
        if (m.type === 'shape') { const s = shapes.find(s => s.id === m.id); if (s) _multiDragStarts.set(`shape_${m.id}`, {x: s.shape.x(), y: s.shape.y()}); }
      });
    }
  });
  group.on('dragmove', () => {
    updateEdgesForNode(device.id);
    if (_multiDragAnchorType === 'node' && _multiDragAnchorId === device.id) {
      const anc = _multiDragStarts.get(`node_${device.id}`);
      if (anc) {
        const dx = group.x() - anc.x, dy = group.y() - anc.y;
        multiSelected.forEach(m => {
          if (m.type === 'node' && m.id !== device.id && nodes[m.id]) {
            const st = _multiDragStarts.get(`node_${m.id}`); if (st) { nodes[m.id].group.x(st.x+dx); nodes[m.id].group.y(st.y+dy); updateEdgesForNode(m.id); }
          }
          if (m.type === 'shape') { const s = shapes.find(s=>s.id===m.id); const st = _multiDragStarts.get(`shape_${m.id}`); if (s&&st) { s.shape.x(st.x+dx); s.shape.y(st.y+dy); if (s.labelNode) updateLabelPos(s.shape, s.labelNode); } }
        });
        connLayer.draw(); shapeLayer.draw();
      }
    }
  });
  group.on('dragend', () => {
    const isAnchor = _multiDragAnchorType === 'node' && _multiDragAnchorId === device.id;
    if (isAnchor) {
      multiSelected.forEach(m => {
        if (m.type === 'node' && nodes[m.id]) { if (snapEnabled) { nodes[m.id].group.x(snapVal(nodes[m.id].group.x())); nodes[m.id].group.y(snapVal(nodes[m.id].group.y())); } updateEdgesForNode(m.id); }
        if (m.type === 'shape') { const s = shapes.find(s=>s.id===m.id); if (s) { if (snapEnabled) { s.shape.x(snapVal(s.shape.x())); s.shape.y(snapVal(s.shape.y())); } if (s.labelNode) updateLabelPos(s.shape, s.labelNode); } }
      });
      _multiDragAnchorId = null; _multiDragAnchorType = null; _multiDragStarts.clear();
    } else {
      if (snapEnabled) { group.x(snapVal(group.x())); group.y(snapVal(group.y())); }
    }
    updateEdgesForNode(device.id);
    deviceLayer.draw(); connLayer.draw(); shapeLayer.draw();
    markDirty();
  });

  nodes[device.id] = { group, device, selRect, dot };
  if (autosave) { markDirty(); updatePaletteState(); deviceLayer.draw(); }
  return group;
}

// ── Edges ─────────────────────────────────────────────────────
function _applyDash(line, dash) {
  if (dash === 'dashed') { line.dash([14, 8]);  line.lineCap('butt'); }
  else if (dash === 'dotted') { line.dash([2, 8]); line.lineCap('round'); }
  else { line.dash([]); line.lineCap('round'); }
}

function addEdgeToCanvas(srcId, tgtId, props = {}, autosave = true) {
  if (!nodes[srcId] || !nodes[tgtId]) return;
  if (edges.find(e => e.source_device_id===srcId && e.target_device_id===tgtId)) return;
  const p = (props && typeof props === 'object') ? props : {};
  const color = p.color  || '#4a9eff';
  const dash  = p.dash   || 'solid';
  const width = p.width  ? Number(p.width) : 2;
  const line = new Konva.Line({ points:edgePoints(srcId,tgtId), stroke:color, strokeWidth:width, opacity:.7, hitStrokeWidth:12 });
  _applyDash(line, dash);
  line.on('click tap', (e) => { e.cancelBubble=true; if (currentMode==='select') selectEdge(srcId,tgtId); });
  line.on('mouseenter', () => { line.opacity(1); connLayer.draw(); stage.container().style.cursor='pointer'; });
  line.on('mouseleave', () => { line.opacity(.7); connLayer.draw(); stage.container().style.cursor='default'; });
  connLayer.add(line);
  edges.push({ source_device_id:srcId, target_device_id:tgtId, line, color, dash, width });
  if (autosave) { markDirty(); connLayer.draw(); }
}

function edgePoints(srcId, tgtId) {
  const sg=nodes[srcId].group, tg=nodes[tgtId].group;
  return [sg.x()+ICON_SIZE/2, sg.y()+ICON_SIZE/2, tg.x()+ICON_SIZE/2, tg.y()+ICON_SIZE/2];
}

function updateEdgesForNode(id) {
  edges.forEach(e => { if (e.source_device_id===id||e.target_device_id===id) e.line.points(edgePoints(e.source_device_id,e.target_device_id)); });
  connLayer.draw();
}

// ── Shapes ────────────────────────────────────────────────────
const S_FILL   = '#162038';
const S_STROKE = '#4a9eff';
const S_SW     = 2;

function addShapeToCanvas(data, autosave = true) {
  const id   = data.id || `sh_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,5)}`;
  const type = data.type;
  let shape  = null;

  try {
    if (type === 'text') {
      shape = new Konva.Text({
        x: data.x ?? 150, y: data.y ?? 150,
        text: data.text || 'Text',
        fontSize:   data.fontSize  ?? 16,
        fill:       data.fill      ?? '#d0d4df',
        fontFamily: 'Segoe UI, sans-serif',
        fontStyle:  data.fontStyle ?? 'normal',
        draggable:  true, id,
      });

    } else if (type === 'circle') {
      shape = new Konva.Ellipse({
        x:       (data.x ?? 150) + (data.rX ?? 70),
        y:       (data.y ?? 150) + (data.rY ?? 45),
        radiusX: data.rX ?? 70,
        radiusY: data.rY ?? 45,
        fill: data.fill ?? S_FILL, stroke: data.stroke ?? S_STROKE, strokeWidth: data.sw ?? S_SW,
        draggable: true, id,
      });

    } else if (type === 'diamond') {
      const w = data.width ?? 100, h = data.height ?? 100;
      shape = new Konva.Line({
        x: data.x ?? 150, y: data.y ?? 150,
        points: [w/2,0, w,h/2, w/2,h, 0,h/2],
        closed: true,
        fill: data.fill ?? S_FILL, stroke: data.stroke ?? S_STROKE, strokeWidth: data.sw ?? S_SW,
        draggable: true, id,
      });

    } else if (type === 'cloud') {
      // Proper cloud silhouette via Path
      shape = new Konva.Path({
        x: data.x ?? 150, y: data.y ?? 150,
        data: 'M 20,68 Q 0,68 0,52 Q 0,32 16,30 Q 10,6 36,8 Q 48,0 64,14 Q 78,2 96,16 Q 120,8 124,30 Q 142,32 142,52 Q 142,66 122,68 Z',
        scaleX: data.scaleX ?? 1,
        scaleY: data.scaleY ?? 1,
        fill: data.fill ?? '#0d1f38', stroke: data.stroke ?? '#6aaaff', strokeWidth: data.sw ?? 2,
        draggable: true, id,
      });

    } else if (type === 'arrow' || type === 'arrow-curved') {
      shape = new Konva.Arrow({
        x: data.x ?? 150, y: data.y ?? 150,
        points: data.points ?? (type === 'arrow-curved' ? [0,0, 60,-30, 120,0] : [0,0, 120,0]),
        pointerLength: 12, pointerWidth: 9,
        tension: type === 'arrow-curved' ? 0.5 : 0,
        fill:   data.fill   ?? S_STROKE,
        stroke: data.stroke ?? S_STROKE,
        strokeWidth: data.sw ?? 2,
        draggable: true, id,
      });

    } else {
      // rect / roundrect
      shape = new Konva.Rect({
        x: data.x ?? 150, y: data.y ?? 150,
        width: data.width ?? 140, height: data.height ?? 80,
        cornerRadius: type === 'roundrect' ? 12 : (data.cr ?? 0),
        fill: data.fill ?? S_FILL, stroke: data.stroke ?? S_STROKE, strokeWidth: data.sw ?? S_SW,
        draggable: true, id,
      });
    }
  } catch (err) {
    console.error('addShapeToCanvas error:', err);
    return null;
  }

  // Optional label
  let labelNode = null;
  if (type !== 'text' && data.label) {
    labelNode = new Konva.Text({ text: data.label, fill: data.lc ?? '#c9cdd8', fontSize: data.lfs ?? 12, fontFamily: 'Segoe UI, sans-serif', listening: false });
    shapeLayer.add(labelNode);
    updateLabelPos(shape, labelNode);
  }

  // Apply opacity and fill-enabled
  shape.opacity(data.op ?? 1);
  if (type !== 'text' && type !== 'arrow' && type !== 'arrow-curved') {
    shape.fillEnabled(data.fe !== false);
  }

  shapeLayer.add(shape);
  shapes.push({ id, type, shape, labelNode, data: { ...data, id } });

  shape.on('click tap', (e) => {
    e.cancelBubble = true;
    if (currentMode !== 'select') return;
    if (e.evt.shiftKey) { toggleMultiSelectItem({type:'shape', id}); return; }
    if (multiSelected.length > 0) clearMultiSelection();
    selectShape(id);
  });
  shape.on('dblclick dbltap', (e) => { e.cancelBubble = true; editShapeInline(id); });
  shape.on('dragstart', () => {
    if (multiSelected.find(m => m.type === 'shape' && m.id === id)) {
      _multiDragAnchorId = id; _multiDragAnchorType = 'shape';
      _multiDragStarts.clear();
      multiSelected.forEach(m => {
        if (m.type === 'node' && nodes[m.id]) _multiDragStarts.set(`node_${m.id}`, {x: nodes[m.id].group.x(), y: nodes[m.id].group.y()});
        if (m.type === 'shape') { const s = shapes.find(s => s.id === m.id); if (s) _multiDragStarts.set(`shape_${m.id}`, {x: s.shape.x(), y: s.shape.y()}); }
      });
    }
  });
  shape.on('dragmove', () => {
    if (labelNode) updateLabelPos(shape, labelNode);
    if (_multiDragAnchorType === 'shape' && _multiDragAnchorId === id) {
      const anc = _multiDragStarts.get(`shape_${id}`);
      if (anc) {
        const dx = shape.x() - anc.x, dy = shape.y() - anc.y;
        multiSelected.forEach(m => {
          if (m.type === 'shape' && m.id !== id) { const s = shapes.find(s=>s.id===m.id); const st = _multiDragStarts.get(`shape_${m.id}`); if (s&&st) { s.shape.x(st.x+dx); s.shape.y(st.y+dy); if (s.labelNode) updateLabelPos(s.shape, s.labelNode); } }
          if (m.type === 'node' && nodes[m.id]) { const st = _multiDragStarts.get(`node_${m.id}`); if (st) { nodes[m.id].group.x(st.x+dx); nodes[m.id].group.y(st.y+dy); updateEdgesForNode(m.id); } }
        });
        shapeLayer.draw(); deviceLayer.draw(); connLayer.draw();
      }
    }
  });
  shape.on('dragend', () => {
    const isAnchor = _multiDragAnchorType === 'shape' && _multiDragAnchorId === id;
    if (isAnchor) {
      multiSelected.forEach(m => {
        if (m.type === 'shape') { const s = shapes.find(s=>s.id===m.id); if (s) { if (snapEnabled) { s.shape.x(snapVal(s.shape.x())); s.shape.y(snapVal(s.shape.y())); } if (s.labelNode) updateLabelPos(s.shape, s.labelNode); } }
        if (m.type === 'node' && nodes[m.id]) { if (snapEnabled) { nodes[m.id].group.x(snapVal(nodes[m.id].group.x())); nodes[m.id].group.y(snapVal(nodes[m.id].group.y())); } updateEdgesForNode(m.id); }
      });
      _multiDragAnchorId = null; _multiDragAnchorType = null; _multiDragStarts.clear();
    } else {
      if (snapEnabled) { shape.x(snapVal(shape.x())); shape.y(snapVal(shape.y())); }
    }
    if (labelNode) updateLabelPos(shape, labelNode);
    shapeLayer.draw(); markDirty();
  });
  shape.on('transformend', () => { if (labelNode) updateLabelPos(shape, labelNode); markDirty(); });
  shape.on('mouseenter',   () => { stage.container().style.cursor = 'move'; });
  shape.on('mouseleave',   () => { stage.container().style.cursor = 'default'; });

  if (autosave) { markDirty(); shapeLayer.draw(); }
  return shape;
}

function updateLabelPos(shape, lbl) {
  try {
    const box = shape.getClientRect({ relativeTo: shapeLayer });
    lbl.x(box.x + (box.width  - lbl.width())  / 2);
    lbl.y(box.y + (box.height - lbl.height()) / 2);
  } catch (_) {}
}

function selectShape(id) {
  deselectAll();
  selectedShapeId = id;
  const entry = shapes.find(s => s.id === id);
  if (!entry) return;
  transformer.nodes([entry.shape]);
  shapeLayer.draw();
  closeDetailPanel();

  const panel = document.getElementById('shape-style-panel');
  if (panel) {
    panel.style.display = '';
    const isText = entry.type === 'text';
    document.getElementById('shape-fill-picker').value       = toHex(isText ? entry.shape.fill()   : entry.shape.fill?.())   || '#162038';
    document.getElementById('shape-stroke-picker').value     = toHex(isText ? '#4a9eff'             : entry.shape.stroke?.()) || '#4a9eff';
    document.getElementById('shape-text-color-picker').value = toHex(isText ? entry.shape.fill()   : entry.labelNode?.fill()) || '#d0d4df';
    document.getElementById('shape-font-size').value         = isText ? entry.shape.fontSize() : (entry.labelNode?.fontSize() ?? 12);
    const opPct = Math.round(entry.shape.opacity() * 100);
    document.getElementById('shape-opacity').value           = opPct;
    document.getElementById('shape-opacity-val').textContent = opPct + '%';
    const feEl = document.getElementById('shape-fill-enabled');
    feEl.checked = !isText && entry.shape.fillEnabled();
    feEl.closest('.d-flex').style.display = isText ? 'none' : '';
  }
}

function applyShapeColor() {
  if (!selectedShapeId) return;
  const entry = shapes.find(s => s.id === selectedShapeId);
  if (!entry) return;
  const fill    = document.getElementById('shape-fill-picker').value;
  const stroke  = document.getElementById('shape-stroke-picker').value;
  const tc      = document.getElementById('shape-text-color-picker').value;
  const fs      = parseInt(document.getElementById('shape-font-size').value) || 14;
  const opacity = parseInt(document.getElementById('shape-opacity').value) / 100;
  const fe      = document.getElementById('shape-fill-enabled').checked;
  if (entry.type === 'text') {
    entry.shape.fill(tc);
    entry.shape.fontSize(fs);
  } else {
    if (typeof entry.shape.fill   === 'function') entry.shape.fill(fill);
    if (typeof entry.shape.stroke === 'function') entry.shape.stroke(stroke);
    entry.shape.fillEnabled(fe);
    if (entry.labelNode) { entry.labelNode.fill(tc); entry.labelNode.fontSize(fs); }
  }
  entry.shape.opacity(opacity);
  shapeLayer.draw();
  markDirty();
}

// ── Inline text edit ──────────────────────────────────────────
function editShapeInline(id) {
  const entry = shapes.find(s => s.id === id);
  if (!entry) return;
  const ta = document.getElementById('topo-text-editor');
  if (!ta) return;

  const absPos  = entry.shape.getAbsolutePosition();
  const stageBox = stage.container().getBoundingClientRect();
  ta.style.display  = 'block';
  ta.style.left     = (stageBox.left + absPos.x * stage.scaleX() + stage.x()) + 'px';
  ta.style.top      = (stageBox.top  + absPos.y * stage.scaleY() + stage.y()) + 'px';
  ta.style.fontSize = ((entry.type === 'text' ? entry.shape.fontSize() : 12) * stage.scaleX()) + 'px';
  ta.style.width    = '180px'; ta.style.height = '60px';
  ta.value = entry.type === 'text' ? entry.shape.text() : (entry.labelNode?.text() ?? '');
  ta.focus(); ta.select();

  const commit = () => {
    const val = ta.value;
    ta.style.display = 'none';
    if (entry.type === 'text') {
      entry.shape.text(val || 'Text');
    } else {
      if (!entry.labelNode) {
        const lbl = new Konva.Text({ text: val, fill: '#c9cdd8', fontSize: 12, fontFamily: 'Segoe UI, sans-serif', listening: false });
        entry.labelNode = lbl;
        shapeLayer.add(lbl);
      } else {
        entry.labelNode.text(val);
      }
      updateLabelPos(entry.shape, entry.labelNode);
      entry.data.label = val;
    }
    shapeLayer.draw(); markDirty();
    ta.removeEventListener('blur', commit);
    ta.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { ta.style.display='none'; ta.removeEventListener('blur',commit); ta.removeEventListener('keydown',onKey); }
    else if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); commit(); }
  };
  ta.addEventListener('blur', commit, { once: true });
  ta.addEventListener('keydown', onKey);
}

function promptNewText(x, y) {
  const ta = document.getElementById('topo-text-editor');
  if (!ta) return;
  const stageBox = stage.container().getBoundingClientRect();
  ta.style.display  = 'block';
  ta.style.left     = (stageBox.left + x * stage.scaleX() + stage.x()) + 'px';
  ta.style.top      = (stageBox.top  + y * stage.scaleY() + stage.y()) + 'px';
  ta.style.fontSize = '14px'; ta.style.width = '160px'; ta.style.height = '50px';
  ta.value = ''; ta.focus();

  const commit = () => {
    const val = ta.value.trim(); ta.style.display = 'none';
    if (val) addShapeToCanvas({ type: 'text', x, y, text: val });
    ta.removeEventListener('blur', commit); ta.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => {
    if (e.key==='Escape') { ta.style.display='none'; ta.removeEventListener('blur',commit); ta.removeEventListener('keydown',onKey); }
    else if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); commit(); }
  };
  ta.addEventListener('blur', commit, { once: true });
  ta.addEventListener('keydown', onKey);
}

// ── Connect Mode ──────────────────────────────────────────────
function handleConnectClick(deviceId) {
  if (!connectSource) {
    connectSource = deviceId;
    const n = nodes[deviceId];
    if (n) { n.selRect.visible(true); n.selRect.stroke('#ffc107'); deviceLayer.draw(); }
    document.getElementById('topo-mode-label').textContent = 'Verbinden: Zielgerät wählen…';
  } else {
    if (connectSource !== deviceId) addEdgeToCanvas(connectSource, deviceId);
    cancelConnect();
  }
}

function cancelConnect() {
  if (connectSource && nodes[connectSource]) { nodes[connectSource].selRect.visible(false); deviceLayer.draw(); }
  connectSource = null;
  document.getElementById('topo-mode-label').textContent = 'Modus: Verbinden';
}

// ── Selection ─────────────────────────────────────────────────
function selectNode(deviceId) {
  deselectAll(); selectedNodeId = deviceId;
  const n = nodes[deviceId];
  if (n) { n.selRect.visible(true); n.selRect.stroke('#ffc107'); n.selRect.fill('rgba(255,193,7,0.08)'); deviceLayer.draw(); }
}

function selectEdge(srcId, tgtId) {
  deselectAll();
  selectedEdgeIdx = edges.findIndex(e => e.source_device_id===srcId && e.target_device_id===tgtId);
  if (selectedEdgeIdx >= 0) {
    const e = edges[selectedEdgeIdx];
    e.line.stroke('#ff6b6b'); e.line.opacity(1); connLayer.draw();
    const panel = document.getElementById('edge-style-panel');
    if (panel) {
      panel.style.display = '';
      document.getElementById('edge-color-picker').value = toHex(e.color) || '#4a9eff';
      document.getElementById('edge-dash-select').value  = e.dash  || 'solid';
      document.getElementById('edge-width-input').value  = e.width || 2;
    }
  }
}

function applyEdgeStyle() {
  if (selectedEdgeIdx === null || selectedEdgeIdx < 0) return;
  const e     = edges[selectedEdgeIdx];
  const color = document.getElementById('edge-color-picker').value;
  const dash  = document.getElementById('edge-dash-select').value;
  const width = Math.max(1, parseInt(document.getElementById('edge-width-input').value) || 2);
  e.color = color; e.dash = dash; e.width = width;
  e.line.stroke('#ff6b6b');   // keep selection highlight
  e.line.strokeWidth(width);
  _applyDash(e.line, dash);
  connLayer.draw();
  markDirty();
}

function deselectAll() {
  // Clear multi-selection
  multiSelected.forEach(m => { if (m.type === 'node' && nodes[m.id]) nodes[m.id].selRect.visible(false); });
  multiSelected = [];
  _multiDragAnchorId = null; _multiDragAnchorType = null; _multiDragStarts.clear();
  updateMultiActionBar();

  if (selectedNodeId !== null && nodes[selectedNodeId])   { nodes[selectedNodeId].selRect.visible(false); deviceLayer.draw(); }
  if (selectedEdgeIdx !== null && edges[selectedEdgeIdx]) {
    const _e = edges[selectedEdgeIdx];
    _e.line.stroke(_e.color || '#4a9eff'); _e.line.opacity(.7); connLayer.draw();
    const _ep = document.getElementById('edge-style-panel');
    if (_ep) _ep.style.display = 'none';
  }
  if (selectedShapeId !== null) {
    transformer.nodes([]); shapeLayer.draw();
    const p = document.getElementById('shape-style-panel');
    if (p) p.style.display = 'none';
  }
  selectedNodeId = null; selectedEdgeIdx = null; selectedShapeId = null;
}

// ── Delete ────────────────────────────────────────────────────
function deleteSelected() {
  if (multiSelected.length > 0) { deleteMultiSelected(); return; }
  if (selectedNodeId !== null) {
    const id = selectedNodeId;
    edges = edges.filter(e => { if (e.source_device_id===id||e.target_device_id===id) { e.line.destroy(); return false; } return true; });
    nodes[id].group.destroy(); delete nodes[id];
    selectedNodeId = null; deviceLayer.draw(); connLayer.draw();
    updatePaletteState(); markDirty(); closeDetailPanel();
  } else if (selectedEdgeIdx !== null) {
    edges[selectedEdgeIdx].line.destroy(); edges.splice(selectedEdgeIdx, 1);
    selectedEdgeIdx = null; connLayer.draw(); markDirty();
  } else if (selectedShapeId !== null) {
    const idx = shapes.findIndex(s => s.id === selectedShapeId);
    if (idx >= 0) { shapes[idx].shape.destroy(); shapes[idx].labelNode?.destroy(); shapes.splice(idx, 1); }
    transformer.nodes([]); selectedShapeId = null;
    const p = document.getElementById('shape-style-panel');
    if (p) p.style.display = 'none';
    shapeLayer.draw(); markDirty();
  }
}

// ── Mode ──────────────────────────────────────────────────────
function setMode(mode) {
  const wasPan = currentMode === 'pan';
  currentMode = mode; cancelConnect(); deselectAll(); clearMultiSelection();

  // Restore node/shape draggability when leaving pan mode
  if (wasPan) {
    stage.draggable(false);
    Object.values(nodes).forEach(n => n.group.draggable(true));
    shapes.forEach(s => s.shape.draggable(true));
  }

  // Enter pan mode: stage becomes draggable, nodes/shapes not
  if (mode === 'pan') {
    stage.draggable(true);
    Object.values(nodes).forEach(n => n.group.draggable(false));
    shapes.forEach(s => s.shape.draggable(false));
  }

  document.querySelectorAll('.topo-btn[id^="btn-"]').forEach(b => b.removeAttribute('data-active'));
  const btn = document.getElementById(`btn-${mode}`);
  if (btn) btn.setAttribute('data-active', 'true');

  const labels = { select:'Auswählen', pan:'Verschieben', connect:'Verbinden', text:'Text platzieren' };
  document.getElementById('topo-mode-label').textContent = `Modus: ${labels[mode] || mode}`;
  stage.container().style.cursor = mode==='connect' ? 'crosshair' : mode==='text' ? 'text' : mode==='pan' ? 'grab' : 'default';
}

// ── Zoom ──────────────────────────────────────────────────────
function applyZoom(delta, pointer) {
  const os = stage.scaleX(), ns = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, os + delta));
  const pt = pointer || { x: stage.width()/2, y: stage.height()/2 };
  const mp = { x:(pt.x-stage.x())/os, y:(pt.y-stage.y())/os };
  stage.scale({x:ns,y:ns}); stage.position({x:pt.x-mp.x*ns, y:pt.y-mp.y*ns}); stage.batchDraw();
  document.getElementById('zoom-label').textContent = Math.round(ns*100)+'%';
}
function zoomIn()    { applyZoom(ZOOM_STEP); }
function zoomOut()   { applyZoom(-ZOOM_STEP); }
function resetZoom() { stage.scale({x:1,y:1}); stage.position({x:0,y:0}); stage.batchDraw(); document.getElementById('zoom-label').textContent='100%'; }

// ── Save ──────────────────────────────────────────────────────
async function saveTopology() {
  const ser = shapes.map(s => {
    const sh = s.shape;
    const base = { id:s.id, type:s.type, label:s.data?.label||'', lc:s.labelNode?.fill(), lfs:s.labelNode?.fontSize(), op:sh.opacity(), fe:sh.fillEnabled() };
    if (s.type==='text')   return { ...base, x:sh.x(), y:sh.y(), text:sh.text(), fontSize:sh.fontSize(), fill:sh.fill(), fontStyle:sh.fontStyle() };
    if (s.type==='circle') return { ...base, x:sh.x()-sh.radiusX(), y:sh.y()-sh.radiusY(), rX:sh.radiusX()*sh.scaleX(), rY:sh.radiusY()*sh.scaleY(), fill:sh.fill(), stroke:sh.stroke(), sw:sh.strokeWidth() };
    if (s.type==='diamond'){ const pts=sh.points(),w=pts[2]-pts[0],h=pts[5]-pts[1]; return { ...base, x:sh.x(), y:sh.y(), width:w*sh.scaleX(), height:h*sh.scaleY(), fill:sh.fill(), stroke:sh.stroke(), sw:sh.strokeWidth() }; }
    if (s.type==='cloud')  return { ...base, x:sh.x(), y:sh.y(), scaleX:sh.scaleX(), scaleY:sh.scaleY(), fill:sh.fill(), stroke:sh.stroke(), sw:sh.strokeWidth() };
    if (s.type==='arrow'||s.type==='arrow-curved') return { ...base, x:sh.x(), y:sh.y(), points:sh.points(), fill:sh.fill(), stroke:sh.stroke(), sw:sh.strokeWidth() };
    return { ...base, x:sh.x(), y:sh.y(), width:(sh.width?.()||100)*sh.scaleX(), height:(sh.height?.()||60)*sh.scaleY(), fill:sh.fill?.(), stroke:sh.stroke?.(), sw:sh.strokeWidth?.(), cr:sh.cornerRadius?.() };
  });

  const payload = {
    nodes:  Object.entries(nodes).map(([id,n])=>({device_id:parseInt(id), x:n.group.x(), y:n.group.y()})),
    edges:  edges.map(e=>({source_device_id:e.source_device_id, target_device_id:e.target_device_id, color:e.color||'#4a9eff', dash:e.dash||'solid', width:e.width||2, label:''})),
    shapes: ser,
  };
  const r = await fetch('/api/topology', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  if (r.ok) {
    isDirty = false;
    const msg = document.getElementById('save-msg');
    msg.textContent = '✓ Gespeichert';
    setTimeout(()=>{ msg.textContent=''; }, 2000);
  }
}
function markDirty() { isDirty = true; }
setInterval(()=>{ if(isDirty) saveTopology(); }, 60000);

// ── Palettes ──────────────────────────────────────────────────
function initPalette() {
  document.querySelectorAll('.palette-item').forEach(item => {
    item.draggable = true;
    item.addEventListener('dragstart', (e) => { e.dataTransfer.setData('dtype', 'device'); e.dataTransfer.setData('device_id', item.dataset.deviceId); });
  });

  // Use the wrapper div so dragover/drop fire even over Konva's internal <canvas> children
  const wrapper = document.querySelector('.topo-canvas-wrapper');
  const canvasEl = document.getElementById('topology-canvas');

  wrapper.addEventListener('dragover', (e) => e.preventDefault());
  wrapper.addEventListener('drop', async (e) => {
    e.preventDefault();
    // Only handle drops that land inside the canvas area
    if (!canvasEl.contains(e.target) && e.target !== canvasEl) return;
    const dtype = e.dataTransfer.getData('dtype');
    const rect  = canvasEl.getBoundingClientRect();
    const sx    = (e.clientX - rect.left - stage.x()) / stage.scaleX();
    const sy    = (e.clientY - rect.top  - stage.y()) / stage.scaleY();

    if (dtype === 'shape') {
      const shapeType = e.dataTransfer.getData('shape_type');
      if (shapeType === 'text') promptNewText(sx, sy);
      else addShapeToCanvas({ type: shapeType, x: sx - 70, y: sy - 40 });
      return;
    }
    const deviceId = parseInt(e.dataTransfer.getData('device_id'));
    if (!deviceId || nodes[deviceId]) return;
    const item = document.querySelector(`.palette-item[data-device-id="${deviceId}"]`);
    if (!item) return;
    await addNodeToCanvas({ id:deviceId, name:item.dataset.deviceName, ip_address:item.dataset.deviceIp, device_type:item.dataset.deviceType, status:item.dataset.deviceStatus, icon_name:item.dataset.iconName||null }, sx-ICON_SIZE/2, sy-ICON_SIZE/2);
  });
  updatePaletteState();
}

function initShapePalette() {
  document.querySelectorAll('.shape-palette-item').forEach(item => {
    // Drag-and-drop
    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('dtype', 'shape');
      e.dataTransfer.setData('shape_type', item.dataset.shape);
    });
    // Click-to-add at canvas center
    item.addEventListener('click', () => {
      const cx = (stage.width()  / 2 - stage.x()) / stage.scaleX();
      const cy = (stage.height() / 2 - stage.y()) / stage.scaleY();
      if (item.dataset.shape === 'text') promptNewText(cx, cy);
      else addShapeToCanvas({ type: item.dataset.shape, x: cx - 70, y: cy - 40 });
    });
  });
}

function updatePaletteState() {
  const onMap = new Set(Object.keys(nodes).map(Number));
  document.querySelectorAll('.palette-item').forEach(item => {
    item.classList.toggle('on-map', onMap.has(parseInt(item.dataset.deviceId)));
  });
}

// ── Detail Panel ──────────────────────────────────────────────
async function showDetailPanel(device) {
  const panel = document.getElementById('detail-panel');
  panel.style.display = 'flex';
  const sm = { online:'🟢 Online', offline:'🔴 Offline', unknown:'⚪ Unbekannt' };
  document.getElementById('detail-content').innerHTML = `
    <div class="text-center py-2">
      <img src="${iconUrl(device)}" width="40" height="40" class="mb-2" onerror="this.src='/static/icons/generic.svg'">
      <div class="fw-semibold">${escHtml(device.name)}</div>
      <code class="text-muted small">${device.ip_address}</code><br>
      <span class="small">${sm[device.status]||device.status}</span>
    </div>
    <hr class="border-secondary my-2">
    <a href="/devices/${device.id}" class="btn btn-sm btn-outline-warning w-100 mb-2">
      <i class="bi bi-eye"></i> Gerät öffnen
    </a>
    <div id="panel-metrics" class="mt-2"><div class="text-muted small text-center">Lade...</div></div>
  `;
  try {
    const r = await fetch(`/api/devices/${device.id}/metrics/latest`);
    const d = await r.json();
    const L = { icmp_latency:'Latenz', icmp_packet_loss:'Verlust', snmp_sysUpTime:'Uptime', snmp_cpuLoad:'CPU', snmp_memTotal:'RAM', snmp_ifInOctets:'IF1 In', snmp_ifOutOctets:'IF1 Out' };
    let h = '<div class="small">';
    const f = Object.entries(d).filter(([k])=>k in L);
    if (!f.length) h += '<div class="text-muted text-center">Keine Metriken</div>';
    else f.forEach(([k,v])=>{ h+=`<div class="metric-row"><span class="metric-label">${L[k]}</span><span>${v.value_str??'–'}${v.unit?' '+v.unit:''}</span></div>`; });
    h += '</div>';
    document.getElementById('panel-metrics').innerHTML = h;
  } catch {}
}

function closeDetailPanel() {
  document.getElementById('detail-panel').style.display = 'none';
  document.getElementById('detail-content').innerHTML = '';
}

// ── Helpers ───────────────────────────────────────────────────
function iconUrl(d) {
  if (d.icon_name && d.icon_name.startsWith('custom_')) return `/uploads/icons/${d.icon_name}`;
  return `/static/icons/${d.icon_name || d.device_type || 'generic'}.svg`;
}
function statusColor(s) { return {online:'#28a745',offline:'#dc3545',unknown:'#6c757d'}[s]??'#6c757d'; }
function loadImage(src) {
  return new Promise(r => { const i=new Image(); i.onload=()=>r(i); i.onerror=()=>{ const f=new Image(); f.onload=()=>r(f); f.src='/static/icons/generic.svg'; }; i.src=src; });
}
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function toHex(c) {
  if (!c) return null;
  if (/^#[0-9a-f]{6}$/i.test(c)) return c;
  try { const m=c.match(/[\d.]+/g); if(m&&m.length>=3) return '#'+[0,1,2].map(i=>Math.min(255,parseInt(m[i])).toString(16).padStart(2,'0')).join(''); } catch {}
  return null;
}
// ── Snap to Grid ──────────────────────────────────────────────
function snapVal(v) { return Math.round(v / GRID_SIZE) * GRID_SIZE; }

function toggleSnap() {
  snapEnabled = !snapEnabled;
  const btn = document.getElementById('btn-snap');
  if (btn) btn.setAttribute('data-active', snapEnabled ? 'true' : 'false');
  drawGrid();
}

function drawGrid() {
  bgLayer.destroyChildren();
  if (snapEnabled) {
    const W = 8000, H = 8000;
    const lineStyle = { stroke: '#1e2840', strokeWidth: 1, listening: false };
    for (let x = 0; x <= W; x += GRID_SIZE) bgLayer.add(new Konva.Line({ points: [x, 0, x, H], ...lineStyle }));
    for (let y = 0; y <= H; y += GRID_SIZE) bgLayer.add(new Konva.Line({ points: [0, y, W, y], ...lineStyle }));
  }
  bgLayer.draw();
}

// ── Multi-Select ──────────────────────────────────────────────
function _stageLocalPos() {
  const pos = stage.getPointerPosition();
  if (!pos) return {x: 0, y: 0};
  return { x: (pos.x - stage.x()) / stage.scaleX(), y: (pos.y - stage.y()) / stage.scaleY() };
}

function setMultiSelection(items) {
  deselectAll();
  multiSelected = items;
  items.forEach(m => {
    if (m.type === 'node' && nodes[m.id]) {
      nodes[m.id].selRect.visible(true);
      nodes[m.id].selRect.stroke('#ffc107');
      nodes[m.id].selRect.fill('rgba(255,193,7,0.08)');
    }
  });
  deviceLayer.draw(); shapeLayer.draw();
  updateMultiActionBar();
}

function clearMultiSelection() {
  multiSelected.forEach(m => { if (m.type === 'node' && nodes[m.id]) nodes[m.id].selRect.visible(false); });
  multiSelected = [];
  _multiDragAnchorId = null; _multiDragAnchorType = null; _multiDragStarts.clear();
  deviceLayer.draw();
  updateMultiActionBar();
}

function toggleMultiSelectItem(item) {
  // Ensure no single selection is active
  if (selectedNodeId !== null && nodes[selectedNodeId]) { nodes[selectedNodeId].selRect.visible(false); selectedNodeId = null; }
  if (selectedShapeId !== null)  { transformer.nodes([]); selectedShapeId  = null; const p=document.getElementById('shape-style-panel'); if(p) p.style.display='none'; }
  if (selectedEdgeIdx !== null && edges[selectedEdgeIdx]) { const e=edges[selectedEdgeIdx]; e.line.stroke(e.color||'#4a9eff'); e.line.opacity(.7); selectedEdgeIdx=null; const ep=document.getElementById('edge-style-panel'); if(ep) ep.style.display='none'; }

  const idx = multiSelected.findIndex(m => m.type === item.type && m.id === item.id);
  if (idx >= 0) {
    if (item.type === 'node' && nodes[item.id]) nodes[item.id].selRect.visible(false);
    multiSelected.splice(idx, 1);
  } else {
    multiSelected.push(item);
    if (item.type === 'node' && nodes[item.id]) {
      nodes[item.id].selRect.visible(true);
      nodes[item.id].selRect.stroke('#ffc107');
      nodes[item.id].selRect.fill('rgba(255,193,7,0.08)');
    }
  }
  deviceLayer.draw(); shapeLayer.draw();
  updateMultiActionBar();
}

function updateMultiActionBar() {
  const bar = document.getElementById('multi-action-bar');
  if (!bar) return;
  if (multiSelected.length > 1) {
    bar.style.display = '';
    document.getElementById('multi-sel-count').textContent = `${multiSelected.length} Objekte ausgewählt`;
    const copyBtn = document.getElementById('btn-multi-copy');
    if (copyBtn) copyBtn.style.display = multiSelected.some(m => m.type === 'shape') ? '' : 'none';
  } else {
    bar.style.display = 'none';
  }
}

function deleteMultiSelected() {
  multiSelected.forEach(m => {
    if (m.type === 'node') {
      const id = m.id;
      edges = edges.filter(e => { if (e.source_device_id===id||e.target_device_id===id) { e.line.destroy(); return false; } return true; });
      nodes[id]?.group.destroy(); delete nodes[id];
    }
    if (m.type === 'shape') {
      const idx = shapes.findIndex(s => s.id === m.id);
      if (idx >= 0) { shapes[idx].shape.destroy(); shapes[idx].labelNode?.destroy(); shapes.splice(idx, 1); }
    }
  });
  multiSelected = [];
  transformer.nodes([]);
  deviceLayer.draw(); connLayer.draw(); shapeLayer.draw();
  updatePaletteState(); markDirty(); closeDetailPanel();
  updateMultiActionBar();
}

function copyMultiSelected() {
  const OFFSET = 20;
  const shapeItems = multiSelected.filter(m => m.type === 'shape');
  if (!shapeItems.length) return;
  clearMultiSelection();
  const newSel = [];
  shapeItems.forEach(item => {
    const entry = shapes.find(s => s.id === item.id);
    if (!entry) return;
    const newData = { ...entry.data, id: undefined,
      x: (entry.shape.x()) + OFFSET,
      y: (entry.shape.y()) + OFFSET };
    addShapeToCanvas(newData, false);
    if (shapes.length) newSel.push({type: 'shape', id: shapes[shapes.length - 1].id});
  });
  if (newSel.length > 1) setMultiSelection(newSel);
  else if (newSel.length === 1) selectShape(newSel[0].id);
  shapeLayer.draw(); markDirty();
}

window.addEventListener('beforeunload', (e) => { if (isDirty) { e.preventDefault(); e.returnValue=''; } });
