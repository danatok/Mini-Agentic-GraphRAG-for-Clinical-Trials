"""Render the local networkx graph as a self-contained, interactive HTML file.

No external JS/CSS dependencies (works offline) — a hand-written force-directed
layout on an HTML5 canvas, with drag, pan/zoom, a search box, and a toggle to
show/hide Site nodes (213 of them, mostly generic facility names, which would
otherwise clutter the initial view).

Output: graph_visualization.html at the project root — open it directly in a
browser.
"""
import json
import pickle
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
GRAPH_PATH = ROOT / "data" / "processed" / "graph.gpickle"
OUTPUT_PATH = ROOT / "graph_visualization.html"

COLORS = {
    "Trial": "#4f7cff",
    "Condition": "#2fb87d",
    "Intervention": "#f5a623",
    "Site": "#9aa0ac",
}


def build_export(g: nx.MultiDiGraph) -> dict:
    nodes = []
    for node_id, data in g.nodes(data=True):
        kind = data.get("kind", "Unknown")
        if kind == "Trial":
            label = data.get("title") or node_id
        elif kind == "Site":
            label = data.get("facility") or node_id
        else:
            label = node_id
        nodes.append({"id": node_id, "kind": kind, "label": label})

    edges = []
    seen = set()
    for source, target, data in g.edges(data=True):
        key = (source, target, data.get("relation"))
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": source, "target": target, "relation": data.get("relation", "")})

    counts = {}
    for n in nodes:
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1

    return {"nodes": nodes, "edges": edges, "counts": counts}


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Clinical Trials Knowledge Graph</title>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f1115; }
  #canvas { display: block; width: 100%; height: 100%; cursor: grab; }
  #canvas.dragging { cursor: grabbing; }

  #panel { position: fixed; top: 16px; left: 16px; background: rgba(22,24,30,0.92);
    border: 1px solid #2a2d36; border-radius: 10px; padding: 14px 16px; color: #e6e8ee;
    width: 260px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  #panel h1 { font-size: 14px; margin: 0 0 10px; font-weight: 600; color: #fff; }
  #panel input[type=text] { width: 100%; box-sizing: border-box; padding: 7px 9px;
    border-radius: 6px; border: 1px solid #383c46; background: #14161c; color: #e6e8ee;
    font-size: 13px; margin-bottom: 10px; }
  #panel input[type=text]:focus { outline: none; border-color: #4f7cff; }
  .legend-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px;
    padding: 3px 0; cursor: pointer; user-select: none; color: #c7cad3; }
  .legend-row.off { opacity: 0.4; }
  .swatch { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
  .legend-count { margin-left: auto; color: #7b7f8a; font-variant-numeric: tabular-nums; }
  #hint { margin-top: 10px; padding-top: 10px; border-top: 1px solid #2a2d36;
    font-size: 11px; color: #6b6f79; line-height: 1.5; }

  #tooltip { position: fixed; pointer-events: none; background: rgba(22,24,30,0.96);
    border: 1px solid #383c46; border-radius: 8px; padding: 8px 11px; color: #e6e8ee;
    font-size: 12.5px; max-width: 320px; line-height: 1.4; display: none; z-index: 10;
    box-shadow: 0 6px 18px rgba(0,0,0,0.4); }
  #tooltip .kind { color: #8b93ff; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.03em; margin-bottom: 3px; }
</style>
</head>
<body>
<canvas id="canvas"></canvas>

<div id="panel">
  <h1>Clinical Trials Knowledge Graph</h1>
  <input type="text" id="search" placeholder="Search nodes…" autocomplete="off">
  <div id="legend"></div>
  <div id="hint">Drag nodes &middot; scroll to zoom &middot; drag background to pan<br>Click a legend row to toggle a node type</div>
</div>

<div id="tooltip"></div>

<script>
const DATA = __GRAPH_DATA_JSON__;
const COLORS = __COLORS_JSON__;

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const searchBox = document.getElementById('search');
const legendEl = document.getElementById('legend');

function resize() {
  canvas.width = window.innerWidth * devicePixelRatio;
  canvas.height = window.innerHeight * devicePixelRatio;
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
}
window.addEventListener('resize', resize);
resize();

// ---- build simulation nodes/edges ----
const nodeById = {};
const nodes = DATA.nodes.map((n, i) => {
  const angle = (i / DATA.nodes.length) * Math.PI * 2;
  const r = 300 + Math.random() * 200;
  const node = {
    id: n.id, kind: n.kind, label: n.label,
    x: Math.cos(angle) * r, y: Math.sin(angle) * r,
    vx: 0, vy: 0, fixed: false, visible: true,
  };
  nodeById[n.id] = node;
  return node;
});
const edges = DATA.edges
  .map(e => ({ source: nodeById[e.source], target: nodeById[e.target], relation: e.relation }))
  .filter(e => e.source && e.target);

// visibility toggles per kind (Site starts hidden — too many to be legible by default)
const visibleKinds = {};
Object.keys(DATA.counts).forEach(k => { visibleKinds[k] = (k !== 'Site'); });
function applyVisibility() {
  nodes.forEach(n => { n.visible = !!visibleKinds[n.kind]; });
}
applyVisibility();

// ---- legend ----
function renderLegend() {
  legendEl.innerHTML = '';
  Object.keys(DATA.counts).sort().forEach(kind => {
    const row = document.createElement('div');
    row.className = 'legend-row' + (visibleKinds[kind] ? '' : ' off');
    row.innerHTML = `<span class="swatch" style="background:${COLORS[kind] || '#888'}"></span>
      <span>${kind}</span><span class="legend-count">${DATA.counts[kind]}</span>`;
    row.onclick = () => { visibleKinds[kind] = !visibleKinds[kind]; applyVisibility(); renderLegend(); };
    legendEl.appendChild(row);
  });
}
renderLegend();

// ---- force simulation (simple, dependency-free) ----
const REPEL = 2600;
const SPRING_LEN = 70;
const SPRING_K = 0.02;
const CENTER_K = 0.0015;
const DAMPING = 0.86;
let simActive = true;
let coolTicks = 0;

function step() {
  const visNodes = nodes.filter(n => n.visible && !n.fixed);
  const allVis = nodes.filter(n => n.visible);

  // repulsion (all-pairs, only among visible nodes)
  for (let i = 0; i < allVis.length; i++) {
    const a = allVis[i];
    for (let j = i + 1; j < allVis.length; j++) {
      const b = allVis[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let distSq = dx * dx + dy * dy || 0.01;
      let dist = Math.sqrt(distSq);
      let force = REPEL / distSq;
      let fx = (dx / dist) * force, fy = (dy / dist) * force;
      if (!a.fixed) { a.vx += fx; a.vy += fy; }
      if (!b.fixed) { b.vx -= fx; b.vy -= fy; }
    }
  }

  // spring attraction along edges
  edges.forEach(e => {
    if (!e.source.visible || !e.target.visible) return;
    let dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
    let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    let force = (dist - SPRING_LEN) * SPRING_K;
    let fx = (dx / dist) * force, fy = (dy / dist) * force;
    if (!e.source.fixed) { e.source.vx += fx; e.source.vy += fy; }
    if (!e.target.fixed) { e.target.vx -= fx; e.target.vy -= fy; }
  });

  // gravity to center + integrate
  visNodes.forEach(n => {
    n.vx -= n.x * CENTER_K;
    n.vy -= n.y * CENTER_K;
    n.vx *= DAMPING; n.vy *= DAMPING;
    n.x += n.vx; n.y += n.vy;
  });
}

// ---- camera (pan/zoom) ----
let camX = 0, camY = 0, camZoom = 0.9;
let dragging = null, panStart = null, camStart = null;

function worldToScreen(x, y) {
  return [
    (x - camX) * camZoom + window.innerWidth / 2,
    (y - camY) * camZoom + window.innerHeight / 2,
  ];
}
function screenToWorld(sx, sy) {
  return [
    (sx - window.innerWidth / 2) / camZoom + camX,
    (sy - window.innerHeight / 2) / camZoom + camY,
  ];
}

function nodeRadius(n) {
  return n.kind === 'Trial' ? 8 : n.kind === 'Site' ? 4 : 6;
}

let searchTerm = '';
function matchesSearch(n) {
  return searchTerm.length > 0 && n.label.toLowerCase().includes(searchTerm);
}

function draw() {
  ctx.save();
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  ctx.fillStyle = '#0f1115';
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

  const highlightActive = searchTerm.length > 0;

  // edges
  ctx.lineWidth = 1;
  edges.forEach(e => {
    if (!e.source.visible || !e.target.visible) return;
    const [sx, sy] = worldToScreen(e.source.x, e.source.y);
    const [tx, ty] = worldToScreen(e.target.x, e.target.y);
    const dim = highlightActive && !matchesSearch(e.source) && !matchesSearch(e.target);
    ctx.strokeStyle = dim ? 'rgba(120,124,138,0.08)' : 'rgba(140,145,160,0.35)';
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(tx, ty);
    ctx.stroke();
  });

  // nodes
  nodes.forEach(n => {
    if (!n.visible) return;
    const [sx, sy] = worldToScreen(n.x, n.y);
    const r = nodeRadius(n) * Math.min(1.6, Math.max(0.6, camZoom));
    const dim = highlightActive && !matchesSearch(n);
    const match = matchesSearch(n);

    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI * 2);
    ctx.fillStyle = dim ? 'rgba(120,124,138,0.15)' : (COLORS[n.kind] || '#888');
    ctx.globalAlpha = dim ? 0.4 : 1;
    ctx.fill();
    if (match) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ffffff';
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  });

  ctx.restore();
}

function loop() {
  if (simActive) {
    step();
    coolTicks++;
    if (coolTicks > 500) simActive = false; // settle, then stop burning CPU
  }
  draw();
  requestAnimationFrame(loop);
}
loop();

// ---- interaction ----
function findNodeAt(sx, sy) {
  let best = null, bestDist = 14;
  for (const n of nodes) {
    if (!n.visible) continue;
    const [nx_, ny_] = worldToScreen(n.x, n.y);
    const d = Math.hypot(nx_ - sx, ny_ - sy);
    if (d < bestDist) { best = n; bestDist = d; }
  }
  return best;
}

canvas.addEventListener('mousedown', (ev) => {
  const hit = findNodeAt(ev.clientX, ev.clientY);
  if (hit) {
    dragging = hit;
    hit.fixed = true;
    canvas.classList.add('dragging');
  } else {
    panStart = [ev.clientX, ev.clientY];
    camStart = [camX, camY];
    canvas.classList.add('dragging');
  }
});

window.addEventListener('mousemove', (ev) => {
  if (dragging) {
    const [wx, wy] = screenToWorld(ev.clientX, ev.clientY);
    dragging.x = wx; dragging.y = wy; dragging.vx = 0; dragging.vy = 0;
    simActive = true; coolTicks = 0;
  } else if (panStart) {
    camX = camStart[0] - (ev.clientX - panStart[0]) / camZoom;
    camY = camStart[1] - (ev.clientY - panStart[1]) / camZoom;
  } else {
    const hit = findNodeAt(ev.clientX, ev.clientY);
    if (hit) {
      tooltip.style.display = 'block';
      tooltip.style.left = (ev.clientX + 14) + 'px';
      tooltip.style.top = (ev.clientY + 14) + 'px';
      tooltip.innerHTML = `<div class="kind">${hit.kind}</div>${hit.label}`;
    } else {
      tooltip.style.display = 'none';
    }
  }
});

window.addEventListener('mouseup', () => {
  if (dragging) { dragging.fixed = false; dragging = null; simActive = true; coolTicks = 0; }
  panStart = null;
  canvas.classList.remove('dragging');
});

canvas.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  const factor = ev.deltaY < 0 ? 1.1 : 0.9;
  camZoom = Math.min(4, Math.max(0.15, camZoom * factor));
}, { passive: false });

searchBox.addEventListener('input', () => {
  searchTerm = searchBox.value.trim().toLowerCase();
});
</script>
</body>
</html>
"""


def main() -> None:
    with open(GRAPH_PATH, "rb") as f:
        g = pickle.load(f)

    export = build_export(g)
    html = HTML_TEMPLATE.replace("__GRAPH_DATA_JSON__", json.dumps(export))
    html = html.replace("__COLORS_JSON__", json.dumps(COLORS))

    OUTPUT_PATH.write_text(html)
    print(f"Wrote interactive graph visualization to {OUTPUT_PATH}")
    print(f"Nodes: {export['counts']}")
    print(f"Edges: {len(export['edges'])}")
    print(f"\nOpen it with: open {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
