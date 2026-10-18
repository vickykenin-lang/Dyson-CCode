"""Gate 8: the Founder's live observatory.

On one side Dyson's own star: a real 3D sphere whose panels are the 19 parts of the system, lit
by their live status. On the other side the wiring board, drawn like a circuit board: each wire
of the master architecture, with a light running along it once for every real record that
crossed it (a model call, a tool decision, a QA verdict...). Nothing is animated without data
behind it except the star itself. The data comes from GET /dashboard (read only); nothing on
this page can act.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dyson · observatory</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{--space:#03040b;--ink:#eef0f7;--soft:#8b91a8;--dim:#4d5470;--board:#070c19;--mask:#0b1224;--line:#1b2540;
--copper:#7a6437;--gold:#ffc56b;--req:#4c9bff;--res:#3ddc97;--stop:#ff5a5f;--mon:#ffb020;--fin:#a37bff;--mem:#35d0e0;
--out:cubic-bezier(.2,.8,.2,1);--mono:"IBM Plex Mono",ui-monospace,monospace}
*{box-sizing:border-box}html{background:var(--space)}
body{margin:0;color:var(--ink);font:14px/1.5 Sora,system-ui,sans-serif;font-variant-numeric:tabular-nums;
background:radial-gradient(1100px 800px at 18% 30%,rgba(255,170,60,.10),transparent 60%),var(--space)}
a{color:inherit}:focus-visible{outline:2px solid var(--gold);outline-offset:3px;border-radius:6px}
button{font:inherit;color:inherit}
.bar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:22px;height:60px;padding:0 24px;
background:linear-gradient(var(--space),rgba(3,4,11,.6));backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
border-bottom:1px solid var(--line)}
.mark{font-weight:700;letter-spacing:.32em;font-size:15px;color:var(--gold)}
.mark span{color:var(--soft);font-weight:300;letter-spacing:.04em;margin-left:10px}
.bar nav a{color:var(--soft);text-decoration:none;font-size:13px}.bar nav a:hover{color:var(--ink)}
.pill{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--soft);font-family:var(--mono)}
.pill i{width:7px;height:7px;border-radius:50%;background:var(--res);box-shadow:0 0 10px var(--res)}
.pill.bad i{background:var(--stop);box-shadow:0 0 10px var(--stop)}.pill.warn i{background:var(--mon);box-shadow:0 0 10px var(--mon)}
.clock{margin-left:auto;text-align:right;line-height:1.25;font-family:var(--mono)}
.clock b{font-weight:500;font-size:14px;display:block}.clock small{color:var(--soft);font-size:11px}
.clock.err small{color:var(--mon)}
.obs{display:grid;grid-template-columns:minmax(380px,40fr) 60fr;min-height:calc(100vh - 60px)}
/* the star */
.star{position:sticky;top:60px;height:calc(100vh - 60px);overflow:hidden;border-right:1px solid var(--line)}
#gl{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:pan-y}
#gl:active{cursor:grabbing}
.nogl #gl{display:none}
.css-star{display:none;position:absolute;left:50%;top:38%;width:220px;height:220px;margin:-110px 0 0 -110px;border-radius:50%;
background:radial-gradient(circle at 42% 40%,#fffbe8,#ffc56b 30%,#ff8a2a 62%,#7a2a08 100%);
box-shadow:0 0 80px 30px rgba(255,170,60,.35),0 0 200px 80px rgba(255,120,30,.15)}
.nogl .css-star{display:block}
.copy{position:absolute;left:32px;right:32px;bottom:28px;pointer-events:none}
.copy h1{margin:0;font-weight:300;font-size:clamp(28px,3.1vw,48px);line-height:1.08;letter-spacing:-.02em;max-width:16ch;
transition:opacity .3s,transform .3s var(--out)}
.copy h1.swap{opacity:0;transform:translateY(8px)}
.copy p{margin:12px 0 0;color:var(--soft);max-width:42ch}
.vitals{display:flex;gap:30px;margin:22px 0 0;padding:0}
.vitals div{display:flex;flex-direction:column}
.vitals b{font-weight:600;font-size:28px;line-height:1}.vitals b small{font-size:15px;color:var(--soft);font-weight:400}
.vitals span{font-size:12px;color:var(--soft);margin-top:6px;max-width:14ch;line-height:1.3}
.vitals .hot b{color:var(--mon)}
.starnote{position:absolute;top:18px;left:32px;right:32px;margin:0;font-size:12px;color:var(--dim);pointer-events:none}
.tip{position:absolute;pointer-events:none;padding:7px 10px;border-radius:8px;background:rgba(7,12,25,.9);border:1px solid var(--line);
font-size:12px;white-space:nowrap;transform:translate(14px,-50%);opacity:0;transition:opacity .15s}
.tip.on{opacity:1}.tip small{display:block;color:var(--soft)}
/* the board */
.right{padding:22px 24px 28px;display:flex;flex-direction:column;gap:18px;min-width:0}
.panel{background:linear-gradient(180deg,rgba(11,18,36,.85),rgba(7,12,25,.85));border:1px solid var(--line);border-radius:16px}
.bhead{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 24px;padding:18px 20px 6px}
.bhead h2{margin:0;font-size:18px;font-weight:600}.bhead p{margin:2px 0 0;color:var(--soft);font-size:13px}
.replay{margin-left:auto;padding:8px 14px;border-radius:999px;border:1px solid #3a3020;background:rgba(255,197,107,.08);color:var(--gold);
font-size:12.5px;cursor:pointer;transition:background .2s,transform .1s}
.replay:hover{background:rgba(255,197,107,.16)}.replay:active{transform:scale(.97)}.replay:disabled{opacity:.6;cursor:default}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;padding:0 20px 8px;font-size:12px;color:var(--soft)}
.legend i{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle;box-shadow:0 0 6px currentColor}
.bscroll{overflow-x:auto;padding:0 8px}
#board{display:block;min-width:860px;width:100%;height:auto}
.hint{display:none;margin:0 20px 6px;font-size:12px;color:var(--soft)}
#board .grid{fill:url(#dots)}
#board .zone{fill:none;stroke:#18223c;stroke-dasharray:2 5}
#board .zl{fill:var(--dim);font:500 10px var(--mono);letter-spacing:.06em}
.tr-cu{fill:none;stroke:var(--copper);stroke-width:3;stroke-linejoin:round;opacity:.45}
.tr-halo{fill:none;stroke:var(--board);stroke-width:9}
.tr-on{fill:none;stroke-width:2;stroke-linejoin:round;transition:opacity .6s}
.tr-hit{fill:none;stroke:transparent;stroke-width:14;cursor:pointer}
.wire.sel .tr-on{stroke-width:3;opacity:1!important}
.via{fill:var(--board);stroke:var(--copper);stroke-width:1.4;opacity:.7}
.cnt rect{fill:#0a1122;stroke:#2a3554}.cnt text{fill:var(--ink);font:500 10px var(--mono)}
.cnt.zero text{fill:var(--dim)}
.chip{cursor:pointer}.chip .pkg{fill:var(--mask);stroke:#2b3a5c;stroke-width:1.2;transition:stroke .3s}
.chip:hover .pkg{stroke:#4d6390}.chip.sel .pkg{stroke:var(--gold);stroke-width:1.8}
.chip .pin{fill:var(--copper);opacity:.85}.chip .p1{fill:none;stroke:var(--dim)}
.chip .code{fill:var(--gold);font:500 10px var(--mono);letter-spacing:.06em;opacity:.85}
.chip .nm{fill:var(--ink);font:600 12.5px Sora,sans-serif}.chip .st{fill:var(--soft);font:400 10.5px Sora,sans-serif}
.chip .led{stroke:none}
.chip.st-off .nm,.chip.st-off .code{opacity:.45}.chip.st-off .pkg{stroke-dasharray:3 4}
.chip.st-live .led{animation:led 1.6s ease-in-out infinite}@keyframes led{50%{opacity:.45}}
.chip.hit .pkg{animation:hit 1s var(--out)}@keyframes hit{0%{stroke:var(--c);stroke-width:3;filter:drop-shadow(0 0 10px var(--c))}}
#detail{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;margin:6px 16px 16px;padding:12px 14px;border-radius:12px;
background:rgba(3,4,11,.55);border:1px solid var(--line);min-height:52px}
#detail.open{animation:open .35s var(--out)}@keyframes open{from{opacity:.3;transform:translateY(4px)}}
#detail h3{margin:0;font-size:14px;font-weight:600}#detail .s{font-size:12.5px;color:var(--soft)}
.chipv{display:inline-flex;gap:6px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);font-size:12px}
.chipv span{color:var(--soft)}#detail .note{flex-basis:100%;margin:0;font-size:12.5px;color:var(--soft)}
.lower{display:grid;grid-template-columns:1.25fr 1fr;gap:18px}
.lower .panel{padding:16px 18px;min-width:0}
.lower h2{margin:0 0 2px;font-size:15px;font-weight:600}.lower .sub{margin:0 0 10px;font-size:12.5px;color:var(--soft)}
#scope{display:block;width:100%;height:auto}
#scope .ln{stroke:#18223c}#scope .lb{fill:var(--soft);font:400 10.5px Sora,sans-serif}#scope .ax{fill:var(--dim);font:400 10px var(--mono)}
#scope .now{animation:led 1.8s ease-in-out infinite}
.log{list-style:none;margin:0;padding:0;max-height:250px;overflow:auto}
.log li{display:grid;grid-template-columns:56px 40px 1fr;gap:8px;padding:6px 0;border-top:1px solid var(--line);font-size:12.5px}
.log li:first-child{border-top:0}.log .t{color:var(--soft);font-family:var(--mono);font-size:11px;padding-top:1px}
.log .b{font-family:var(--mono);font-size:11px;color:var(--gold);padding-top:1px}
.log li.new{animation:arrive 2.2s var(--out)}@keyframes arrive{0%{opacity:0;transform:translateX(-10px);background:rgba(255,197,107,.12)}15%{opacity:1;transform:none}100%{background:transparent}}
.foot{color:var(--dim);font-size:12px;margin:0}
@media (max-width:1100px){.obs{grid-template-columns:1fr}.star{position:relative;top:0;height:560px;border-right:0;border-bottom:1px solid var(--line)}
.lower{grid-template-columns:1fr}}
@media (max-width:900px){.hint{display:block}}
@media (max-width:560px){.bar{gap:12px;padding:0 14px}.mark span,.pill{display:none}.star{height:520px}.copy{left:18px;right:18px;bottom:20px}
.starnote{left:18px;right:18px}.vitals{gap:20px}.right{padding:16px 12px 24px}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<header class="bar"><span class="mark">DYSON<span>Layer A observatory</span></span>
 <nav><a href="/">Conversation</a></nav>
 <span class="pill" id="ctl"><i></i><span id="ctltext">control: checking</span></span>
 <div class="clock" id="clock"><b id="hhmm">--:--:--</b><small id="clocktext">connecting…</small></div></header>
<main class="obs">
 <section class="star" id="star" aria-label="Dyson as a star: each panel of the sphere is one part of the system">
  <canvas id="gl"></canvas><div class="css-star" aria-hidden="true"></div>
  <p class="starnote">Each panel on the sphere is one part of Dyson. Bright panels are live. Drag to turn it.</p>
  <div class="copy"><h1 id="headline">Reading the system…</h1><p id="subline"></p>
   <div class="vitals" aria-live="polite"><div><b id="v-live">–</b><span>parts live right now</span></div>
    <div><b id="v-wires">–</b><span>wires that carried work today</span></div>
    <div id="v-wait-box"><b id="v-wait">–</b><span>approvals waiting for you</span></div></div></div>
  <div class="tip" id="tip"></div>
 </section>
 <section class="right">
  <div class="panel"><div class="bhead"><div><h2>Wiring</h2><p>Every light is one real record crossing that wire. Select a wire or a part.</p></div>
   <button class="replay" id="replay" type="button">Replay the last hour</button></div>
   <div class="legend"><span><i style="color:var(--req);background:var(--req)"></i>Requests</span><span><i style="color:var(--res);background:var(--res)"></i>Results</span>
    <span><i style="color:var(--stop);background:var(--stop)"></i>Control and STOP</span><span><i style="color:var(--mon);background:var(--mon)"></i>Monitoring</span>
    <span><i style="color:var(--fin);background:var(--fin)"></i>Money</span><span><i style="color:var(--mem);background:var(--mem)"></i>Memory and evidence</span></div>
   <p class="hint">Swipe the board sideways to see every wire.</p>
   <div class="bscroll"><svg id="board" viewBox="0 0 1000 650" role="group" aria-label="Dyson wiring with live activity">
    <defs><pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".9" fill="#162038"/></pattern>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <rect class="grid" width="1000" height="650"/><g id="zones"></g><g id="wires"></g><g id="sig"></g><g id="chips"></g></svg></div>
   <div id="detail" aria-live="polite"><h3>Select a wire or a part</h3><span class="s">Its live numbers appear here.</span></div>
  </div>
  <div class="lower">
   <div class="panel"><h2>Signal scope</h2><p class="sub">Every record of the last 60 minutes, by kind. Now is on the right.</p>
    <svg id="scope" viewBox="0 0 620 176" aria-hidden="true"></svg></div>
   <div class="panel"><h2>What just happened</h2><p class="sub" id="logsub">Newest first</p><ul class="log" id="log"><li>Loading…</li></ul></div>
  </div>
  <p class="foot">Read only. Approvals, STOP and PAUSE stay on Direct Founder Controls.</p>
 </section>
</main>
<script>
// Parts on the board: key, x, y (board units 1000 x 650), silkscreen code, short name.
const CHIPS = [
 ["founder", 100, 70, "FDR", "Founder"], ["app", 280, 70, "APP", "Dyson App"], ["gateway", 470, 70, "GW", "Entry Gateway"],
 ["dfc", 660, 70, "DFC", "Founder Controls"], ["vault", 860, 70, "VLT", "Bank Vault"],
 ["C", 280, 210, "C", "Model Router"], ["B", 470, 210, "B", "Conversation"], ["A", 660, 210, "A", "Governance"],
 ["E", 860, 210, "E", "Monitoring"],
 ["I", 280, 345, "I", "Memory"], ["D", 470, 345, "D", "Orchestrator"], ["G", 660, 345, "G", "Tool Hub"],
 ["hermes", 860, 345, "HRM", "Hermes"],
 ["J", 100, 345, "J", "This dashboard"], ["F", 470, 480, "F", "QA/QC"], ["T0", 660, 480, "T0", "Test Receptor"],
 ["H", 860, 480, "H", "Finance"], ["R11", 660, 612, "R11", "Receptors R11…Rn"], ["external", 860, 612, "EXT", "Business world"],
];
// How each wire is routed on the board (orthogonal, like copper on a circuit board).
const ROUTES = {
 "founder>app": [[168, 70], [212, 70]], "app>gateway": [[348, 70], [402, 70]], "gateway>B": [[470, 99], [470, 181]],
 "founder>dfc": [[100, 41], [100, 20], [660, 20], [660, 41]], "dfc>A": [[660, 99], [660, 181]],
 "vault>H": [[928, 70], [966, 70], [966, 480], [928, 480]],
 "B>C": [[402, 210], [348, 210]], "B>D": [[470, 239], [470, 316]],
 "A>D": [[628, 239], [628, 278], [502, 278], [502, 316]], "A>G": [[668, 239], [668, 316]],
 "A>T0": [[728, 226], [752, 226], [752, 466], [728, 466]], "E>A": [[792, 198], [728, 198]],
 "D>G": [[538, 345], [592, 345]], "G>T0": [[660, 374], [660, 451]], "G>hermes": [[728, 345], [792, 345]],
 "D>F": [[470, 374], [470, 451]], "D>I": [[402, 345], [348, 345]],
 "F>I": [[402, 468], [372, 468], [372, 360], [348, 360]],
 "T0>E": [[728, 490], [778, 490], [778, 280], [840, 280], [840, 239]], "T0>H": [[728, 480], [792, 480]],
};
const HALO = new Set(["G>hermes", "T0>E"]);  // drawn over a wire they cross, like a bridge
const ZONES = [[24, 10, 952, 108, "FOUNDER INTERFACE"], [24, 160, 952, 368, "DYSON CORE · AWS"],
 [570, 552, 406, 94, "RECEPTORS · BUSINESS WORLD"]];
const KC = {req: "#4c9bff", res: "#3ddc97", stop: "#ff5a5f", mon: "#ffb020", fin: "#a37bff", mem: "#35d0e0"};
const KN = {req: "Requests", res: "Results", stop: "Control", mon: "Monitoring", fin: "Money", mem: "Memory"};
const SC = {live: "#3ddc97", ok: "#2f9e72", attention: "#ffb020", stopped: "#ff5a5f", off: "#4d5470"};
const WORD = {live: "Live now", ok: "Up, quiet", attention: "Needs you", stopped: "Stopped", off: "Not connected yet"};
const NS = "http://www.w3.org/2000/svg", reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = id => document.getElementById(id);
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
 for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; };
const esc = s => String(s).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
let DATA = null, SERVER = Date.now(), AT = performance.now(), SEL = null, FIRST = true;
const now = () => SERVER + (performance.now() - AT);  // the server's clock, advanced locally
const secs = s => (now() - Date.parse(s)) / 1000;
const span = d => d < 60 ? Math.max(0, Math.round(d)) + " s" : d < 3600 ? Math.round(d / 60) + " min"
 : d < 86400 ? Math.round(d / 3600) + " h" : Math.round(d / 86400) + " d";
const ago = s => s ? span(secs(s)) + " ago" : "nothing yet";
const hms = s => new Date(s).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
window.DY = {blocks: {}, mood: "ok", speed: 0.5, select: k => select({chip: k})};

// --- the board --------------------------------------------------------------------------
for (const [x, y, w, h, t] of ZONES) { el("rect", {class: "zone", x, y, width: w, height: h, rx: 14}, $("zones"));
 el("text", {class: "zl", x: x + w - 12, y: y + 14, "text-anchor": "end"}, $("zones")).textContent = t; }
function trace(pts) {  // orthogonal copper with 45-degree corners
 const c = 9; let d = `M${pts[0][0]},${pts[0][1]}`;
 for (let i = 1; i < pts.length; i++) {
  const [x, y] = pts[i];
  if (i < pts.length - 1) { const [px, py] = pts[i - 1], [nx, ny] = pts[i + 1];
   const ax = x - Math.sign(x - px) * c, ay = y - Math.sign(y - py) * c, bx = x + Math.sign(nx - x) * c, by = y + Math.sign(ny - y) * c;
   d += ` L${ax},${ay} L${bx},${by}`; } else d += ` L${x},${y}`;
 }
 return d;
}
const WIRES = {};
function buildWires(links) {
 for (const w of links) {
  const id = `${w.a}>${w.b}`, pts = ROUTES[id]; if (!pts || WIRES[id]) continue;
  const g = el("g", {class: "wire", "data-w": id}, $("wires")), d = trace(pts);
  if (HALO.has(id)) el("path", {class: "tr-halo", d}, g);
  el("path", {class: "tr-cu", d}, g);
  const on = el("path", {class: "tr-on", d, stroke: KC[w.kind], opacity: 0}, g);
  for (const p of pts.slice(1, -1)) el("circle", {class: "via", cx: p[0], cy: p[1], r: 2.6}, g);
  // the count sits on the longest straight run
  let best = 0, mid = pts[0];
  for (let i = 1; i < pts.length; i++) { const L = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
   if (L > best) { best = L; mid = [(pts[i][0] + pts[i - 1][0]) / 2, (pts[i][1] + pts[i - 1][1]) / 2]; } }
  const cnt = el("g", {class: "cnt", transform: `translate(${mid[0]},${mid[1]})`}, g);
  el("rect", {x: -11, y: -8, width: 22, height: 16, rx: 8}, cnt);
  const ct = el("text", {"text-anchor": "middle", y: 3.5}, cnt);
  const hit = el("path", {class: "tr-hit", d}, g); const ti = el("title", {}, hit);
  hit.addEventListener("click", () => select({wire: id}));
  WIRES[id] = {g, d, on, cnt, ct, ti, kind: w.kind, a: w.a, b: w.b, len: on.getTotalLength(), seen: 0};
 }
}
const CH = {};
CHIPS.forEach(([k, x, y, code, nm]) => {
 const g = el("g", {class: "chip st-off", transform: `translate(${x - 68},${y - 29})`, tabindex: 0, role: "button", "aria-label": nm}, $("chips"));
 for (let i = 0; i < 5; i++) { el("rect", {class: "pin", x: 18 + i * 24, y: -4, width: 6, height: 5, rx: 1}, g);
  el("rect", {class: "pin", x: 18 + i * 24, y: 57, width: 6, height: 5, rx: 1}, g); }
 el("rect", {class: "pkg", width: 136, height: 58, rx: 6}, g);
 el("circle", {class: "p1", cx: 10, cy: 10, r: 2.6}, g);
 el("text", {class: "code", x: 18, y: 14}, g).textContent = code;
 el("text", {class: "nm", x: 10, y: 33}, g).textContent = nm;
 const st = el("text", {class: "st", x: 10, y: 48}, g); st.textContent = "…";
 const led = el("circle", {class: "led", cx: 124, cy: 11, r: 4, fill: SC.off}, g);
 const pick = () => select({chip: k});
 g.addEventListener("click", pick);
 g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
 g.addEventListener("pointerenter", () => document.dispatchEvent(new CustomEvent("dy:hover", {detail: k})));
 g.addEventListener("pointerleave", () => document.dispatchEvent(new CustomEvent("dy:hover", {detail: null})));
 CH[k] = {g, st, led};
});
function select(s) { SEL = s; render(); const d = $("detail"); d.classList.remove("open"); void d.offsetWidth; d.classList.add("open"); }

function signal(id, dir, delay) {  // one real record: a light runs along its wire
 const w = WIRES[id]; if (!w) return;
 setTimeout(() => {
  const to = dir > 0 ? w.b : w.a, col = KC[w.kind];
  if (!reduce) {
   const dur = Math.min(1.6, Math.max(.55, w.len / 420));
   const kp = dir > 0 ? "0;1" : "1;0";
   [[5, 1], [3.6, .55], [2.6, .3], [1.8, .16]].forEach(([r, o], i) => {
    const c = el("circle", {r, fill: i ? col : "#fff", opacity: o, filter: "url(#glow)", stroke: i ? "none" : col, "stroke-width": 2.5}, $("sig"));
    const m = el("animateMotion", {dur: dur + "s", begin: "indefinite", fill: "freeze", path: w.d, keyPoints: kp, keyTimes: "0;1",
     calcMode: "spline", keySplines: ".45 0 .25 1"}, c);
    setTimeout(() => m.beginElement(), i * 45); setTimeout(() => c.remove(), dur * 1000 + 240);
   });
   w.on.setAttribute("opacity", 1); setTimeout(() => heat(w), dur * 1000 + 300);
   setTimeout(() => arrive(to, col), dur * 1000);
  } else arrive(to, col);
 }, delay);
}
function arrive(k, col) {
 const c = CH[k]; if (c && !reduce) { c.g.style.setProperty("--c", col); c.g.classList.remove("hit"); void c.g.getBBox(); c.g.classList.add("hit");
  setTimeout(() => c.g.classList.remove("hit"), 1000); }
 document.dispatchEvent(new CustomEvent("dy:pulse", {detail: {k, color: col}}));
}
function heat(w) {  // a wire glows by how recently real work crossed it
 const l = DATA && DATA.links.find(x => x.a === w.a && x.b === w.b);
 const a = l && l.last ? secs(l.last) : Infinity;
 w.on.setAttribute("opacity", a < 300 ? .9 : a < 86400 ? .32 : 0);
 w.on.setAttribute("filter", a < 300 ? "url(#glow)" : "");
}

// --- page state ---------------------------------------------------------------------------
function headline(b) {
 const m = Object.fromEntries((b.A || {metrics: []}).metrics), waiting = +(m["Approvals waiting"] || 0);
 if (m["Control"] === "stopped") return ["Dyson is stopped.", "Nothing new runs until you resume it on Founder Controls."];
 if (b.founder && b.founder.status === "attention") return ["Survival Mode is on.", "Dyson keeps safe work going and holds anything risky until you are back."];
 const down = Object.values(b).filter(x => x.status === "stopped").map(x => x.title);
 if (down.length) return ["Dyson is running, one part is down.", `${down.join(" and ")} stopped. Everything else keeps working.`];
 if (waiting) return ["Dyson is running.", `${waiting} approval${waiting > 1 ? "s wait" : " waits"} for you on Founder Controls.`];
 return ["Dyson is running.", "Nothing needs you right now."];
}
function render() {
 if (!DATA) return;
 const b = DATA.blocks, all = Object.values(b);
 buildWires(DATA.links);
 for (const [k, c] of Object.entries(CH)) { const x = b[k]; if (!x) continue;
  const sel = SEL && SEL.chip === k;
  c.g.setAttribute("class", `chip st-${x.status}${sel ? " sel" : ""}${c.g.classList.contains("hit") ? " hit" : ""}`);
  c.g.setAttribute("aria-label", `${x.title}: ${WORD[x.status]}, ${ago(x.last)}`);
  c.st.textContent = x.last && x.status !== "off" ? `${WORD[x.status]} · ${ago(x.last)}` : WORD[x.status];
  c.led.setAttribute("fill", SC[x.status]); c.led.setAttribute("filter", x.status === "off" ? "" : "url(#glow)"); }
 for (const l of DATA.links) { const id = `${l.a}>${l.b}`, w = WIRES[id]; if (!w) continue;
  heat(w); w.g.classList.toggle("sel", !!(SEL && SEL.wire === id));
  w.ct.textContent = l.known ? (l.n > 99 ? "99+" : l.n) : "?"; w.cnt.classList.toggle("zero", !l.n);
  w.ti.textContent = `${l.label}: ${l.n} in 24 h, last ${ago(l.last)}`; }
 const [h, s] = headline(b), hl = $("headline");
 if (hl.textContent !== h) { if (FIRST || reduce) hl.textContent = h;
  else { hl.classList.add("swap"); setTimeout(() => { hl.textContent = h; hl.classList.remove("swap"); }, 300); } }
 $("subline").textContent = s;
 const am = b.A ? Object.fromEntries(b.A.metrics) : {};
 const live = all.filter(x => x.status === "live").length, wait = +(am["Approvals waiting"] || 0);
 $("v-live").innerHTML = `${live}<small> / ${all.length}</small>`;
 $("v-wires").innerHTML = `${DATA.links.filter(l => l.n > 0).length}<small> / ${DATA.links.length}</small>`;
 $("v-wait").textContent = wait; $("v-wait-box").className = wait ? "hot" : "";
 const ctl = am["Control"] || "unknown";
 $("ctltext").textContent = `control: ${ctl}`; $("ctl").className = "pill" + (ctl === "stopped" ? " bad" : ctl !== "running" ? " warn" : "");
 const d = $("detail");
 if (SEL && SEL.chip && b[SEL.chip]) { const x = b[SEL.chip];
  d.innerHTML = `<h3>${esc(x.title)}</h3><span class="s" style="color:${SC[x.status]}">${WORD[x.status]}, last activity ${ago(x.last)}</span>`
   + x.metrics.map(([k, v]) => `<span class="chipv"><span>${esc(k)}</span>${esc(v)}</span>`).join("") + (x.note ? `<p class="note">${esc(x.note)}</p>` : "");
 } else if (SEL && SEL.wire) { const l = DATA.links.find(x => `${x.a}>${x.b}` === SEL.wire);
  const A = b[l.a], B = b[l.b];
  d.innerHTML = `<h3>${esc(l.label)}</h3><span class="s">${esc(A ? A.title : l.a)} ⇄ ${esc(B ? B.title : l.b)}</span>`
   + `<span class="chipv"><span>Records, 24 h</span>${l.known ? l.n : "unknown"}</span><span class="chipv"><span>Last</span>${ago(l.last)}</span>`
   + `<span class="chipv"><span>Kind</span><b style="color:${KC[l.kind]}">${KN[l.kind]}</b></span>`
   + `<p class="note">Each light on this wire is one record that the receiving part keeps. No light means nothing crossed.</p>`;
 } else d.innerHTML = `<h3>Select a wire or a part</h3><span class="s">Its live numbers appear here.</span>`;
 DY.blocks = b; DY.speed = 0.2 + 1.2 * live / Math.max(1, all.length);
 DY.mood = all.some(x => x.status === "stopped") ? "stopped" : all.some(x => x.status === "attention") ? "attention" : "ok";
 document.dispatchEvent(new CustomEvent("dy:data"));
 log(); scope();
}
const ITEMS = new Map(), SEEN = new Set();
function log() {
 const ul = $("log");
 if (!DATA.feed.length) { ul.innerHTML = "<li>Nothing has happened in the last 24 hours.</li>"; return; }
 const keep = new Map();
 const lis = DATA.feed.map(f => { const k = f.at + "|" + f.block + "|" + f.text; let li = ITEMS.get(k);
  if (!li) { li = document.createElement("li"); li.dataset.at = f.at;
   li.innerHTML = `<span class="t">${hms(f.at)}</span><span class="b">${esc(f.block)}</span><span>${esc(f.text)}</span>`;
   if (!SEEN.has(k)) { SEEN.add(k); if (!FIRST) li.classList.add("new"); } }
  keep.set(k, li); return li; });
 ITEMS.clear(); for (const [k, v] of keep) ITEMS.set(k, v);
 ul.replaceChildren(...lis); $("logsub").textContent = `Newest first, latest ${DATA.feed.length}`;
}
function scope() {  // one lane per kind, a spike for every record in the last hour
 const sv = $("scope"), lanes = ["req", "res", "stop", "mon", "fin", "mem"], X0 = 96, W = 510;
 let h = "";
 lanes.forEach((k, i) => { const y = 22 + i * 24;
  h += `<line class="ln" x1="${X0}" x2="${X0 + W}" y1="${y}" y2="${y}"/><text class="lb" x="0" y="${y + 4}">${KN[k]}</text>`; });
 for (const m of [60, 45, 30, 15]) { const x = X0 + W - m / 60 * W; h += `<line class="ln" x1="${x}" x2="${x}" y1="8" y2="160" stroke-dasharray="2 4"/>`
  + `<text class="ax" x="${x}" y="174" text-anchor="middle">${m} min</text>`; }
 h += `<text class="ax" x="${X0 + W}" y="174" text-anchor="middle">now</text>`;
 for (const l of DATA.links) { const i = lanes.indexOf(l.kind), y = 22 + i * 24;
  for (const [at] of l.events) { const a = secs(at); if (a < 0 || a > 3600) continue;
   const x = X0 + W - a / 3600 * W, fresh = a < 300;
   h += `<path d="M${x - 4},${y} L${x},${y - (fresh ? 15 : 11)} L${x + 4},${y}" fill="none" stroke="${KC[l.kind]}" stroke-width="1.6" opacity="${fresh ? 1 : .6}"${fresh ? ' filter="url(#sglow)"' : ""}/>`; } }
 h += `<rect class="now" x="${X0 + W - 1}" y="6" width="2" height="156" fill="#ffc56b"/>`;
 sv.innerHTML = `<defs><filter id="sglow"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>` + h;
}
function tick() {  // once a second: clock, every "ago", the scope drifting left
 $("hhmm").textContent = new Date(now()).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
 if (!DATA) return;
 for (const [k, c] of Object.entries(CH)) { const x = DATA.blocks[k];
  if (x && x.last && x.status !== "off") c.st.textContent = `${WORD[x.status]} · ${ago(x.last)}`; }
 const age = Math.round((performance.now() - AT) / 1000);
 if (!$("clock").classList.contains("err")) $("clocktext").textContent = age < 2 ? "live, just updated" : `live, updated ${age} s ago`;
 scope();
}
function fresh() {  // records that arrived since the last poll, oldest first
 const out = [];
 for (const l of DATA.links) { const w = WIRES[`${l.a}>${l.b}`]; if (!w) continue;
  for (const [at, dir] of l.events) { const t = Date.parse(at); if (t > w.seen) out.push([t, `${l.a}>${l.b}`, dir]); }
  w.seen = Math.max(w.seen, ...l.events.map(([at]) => Date.parse(at))); }
 return out.sort((p, q) => p[0] - q[0]);
}
$("replay").addEventListener("click", () => {  // the last hour of real records, compressed into a few seconds
 if (!DATA) return; const btn = $("replay"), ev = [];
 for (const l of DATA.links) for (const [at, dir] of l.events) { const a = secs(at); if (a >= 0 && a <= 3600) ev.push([Date.parse(at), `${l.a}>${l.b}`, dir]); }
 if (!ev.length) { btn.textContent = "Nothing crossed in the last hour"; setTimeout(() => btn.textContent = "Replay the last hour", 2500); return; }
 ev.sort((p, q) => p[0] - q[0]); const t0 = ev[0][0], spanT = Math.max(1, ev[ev.length - 1][0] - t0);
 btn.disabled = true; btn.textContent = `Replaying ${ev.length} records…`;
 ev.slice(-80).forEach(([t, id, dir], i) => signal(id, dir, ev.length > 1 ? (t - t0) / spanT * 9000 + i * 30 : 0));
 setTimeout(() => { btn.disabled = false; btn.textContent = "Replay the last hour"; }, 11000);
});
async function refresh() {
 try {
  const r = await fetch("/dashboard/data", {cache: "no-store"});
  if (r.status === 401) { location.href = "/"; return; }
  if (!r.ok) throw new Error(r.status);
  DATA = await r.json(); SERVER = Date.parse(DATA.as_of); AT = performance.now();
  $("clock").classList.remove("err");
  render();
  const got = fresh();
  if (FIRST) {  // opening moment: the latest records run across the board, oldest first
   FIRST = false; got.slice(-16).forEach(([, id, dir], i) => signal(id, dir, 900 + i * 280));
  } else got.slice(-24).forEach(([, id, dir], i) => signal(id, dir, i * 220));
  tick();
 } catch (e) { $("clock").classList.add("err"); $("clocktext").textContent = "can't reach Dyson, retrying…"; }
}
refresh(); setInterval(refresh, 5000); setInterval(tick, 1000); tick();
</script>
<script type="module">
// The star: Dyson's own sun inside a lattice sphere. The 19 bright hexagonal panels are the
// parts of the system, coloured by their live status; a real record arriving at a part sends
// a beam from its panel into the star.
let THREE;
try { THREE = await import("/static/three.module.min.js"); } catch (e) { document.getElementById("star").classList.add("nogl"); }
if (THREE) try { start(); } catch (e) { document.getElementById("star").classList.add("nogl"); }
function start() {
 const box = document.getElementById("star"), cv = document.getElementById("gl"), tip = document.getElementById("tip");
 const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
 const renderer = new THREE.WebGLRenderer({canvas: cv, antialias: true, alpha: true});
 renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
 const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(38, 1, .1, 200);
 camera.position.set(0, 0, 7.2);
 const world = new THREE.Group(); scene.add(world);
 const rig = new THREE.Group(); world.add(rig);
 // the star
 const starMat = new THREE.ShaderMaterial({uniforms: {t: {value: 0}, heat: {value: new THREE.Color(1, .55, .15)}},
  vertexShader: `varying vec3 vP; varying vec3 vN; varying vec3 vV; void main(){ vP = position; vN = normalize(normalMatrix*normal);
   vec4 mv = modelViewMatrix*vec4(position,1.); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
  fragmentShader: `uniform float t; uniform vec3 heat; varying vec3 vP; varying vec3 vN; varying vec3 vV;
   float h(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
   float n(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);
    return mix(mix(mix(h(i),h(i+vec3(1,0,0)),f.x),mix(h(i+vec3(0,1,0)),h(i+vec3(1,1,0)),f.x),f.y),
     mix(mix(h(i+vec3(0,0,1)),h(i+vec3(1,0,1)),f.x),mix(h(i+vec3(0,1,1)),h(i+vec3(1,1,1)),f.x),f.y),f.z);}
   float fbm(vec3 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p*=2.03;a*=.5;}return v;}
   void main(){ vec3 p = vP*2.6; float g = fbm(p + vec3(0.,t*.07,t*.05)); float c = fbm(p*1.7 - g*1.6 + t*.04);
    vec3 deep = heat*.55, hot = vec3(1.,.82,.45), white = vec3(1.,.98,.9);
    vec3 col = mix(deep, hot, smoothstep(.25,.75,c)); col = mix(col, white, smoothstep(.62,.9,c));
    float rim = pow(1.-max(dot(vN,vV),0.),2.2); col += heat*rim*1.3; gl_FragColor = vec4(col,1.); }`});
 const star = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 96), starMat); rig.add(star);
 const glowTex = (() => { const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
  const r = g.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, "rgba(255,230,180,1)"); r.addColorStop(.2, "rgba(255,180,90,.55)");
  r.addColorStop(.5, "rgba(255,120,40,.12)"); r.addColorStop(1, "rgba(255,100,30,0)"); g.fillStyle = r; g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c); })();
 const halo = new THREE.Sprite(new THREE.SpriteMaterial({map: glowTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true}));
 halo.scale.set(5.2, 5.2, 1); world.add(halo);
 const corona = new THREE.Sprite(new THREE.SpriteMaterial({map: glowTex, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: .35}));
 corona.scale.set(10, 10, 1); world.add(corona);
 // the lattice shell and its collectors
 const R = 1.85;
 const shell = new THREE.LineSegments(new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(R, 3)),
  new THREE.LineBasicMaterial({color: 0xffc56b, transparent: true, opacity: .1, blending: THREE.AdditiveBlending, depthWrite: false}));
 rig.add(shell);
 const fib = (i, N, r) => { const y = 1 - 2 * (i + .5) / N, s = Math.sqrt(1 - y * y), a = i * 2.399963; return new THREE.Vector3(Math.cos(a) * s * r, y * r, Math.sin(a) * s * r); };
 const NC = 520, coll = new THREE.InstancedMesh(new THREE.CircleGeometry(.05, 6),
  new THREE.MeshBasicMaterial({color: 0xb08a4a, transparent: true, opacity: .55, side: THREE.DoubleSide}), NC);
 const m4 = new THREE.Object3D();
 for (let i = 0; i < NC; i++) { const p = fib(i, NC, R); m4.position.copy(p); m4.lookAt(p.clone().multiplyScalar(2)); m4.updateMatrix(); coll.setMatrixAt(i, m4.matrix); }
 rig.add(coll);
 // the 19 parts as panels
 const KEYS = ["founder", "app", "gateway", "dfc", "vault", "A", "B", "C", "D", "E", "hermes", "F", "G", "H", "I", "J", "T0", "R11", "external"];
 const SCOL = {live: 0x3ddc97, ok: 0x2f9e72, attention: 0xffb020, stopped: 0xff5a5f, off: 0x2a3150};
 const WORD = {live: "Live now", ok: "Up, quiet", attention: "Needs you", stopped: "Stopped", off: "Not connected yet"};
 const panels = {}, pick = [];
 KEYS.forEach((k, i) => { const p = fib(i, KEYS.length, R + .02);
  const g = new THREE.Group(); g.position.copy(p); g.lookAt(p.clone().multiplyScalar(2));
  const face = new THREE.Mesh(new THREE.CircleGeometry(.12, 6), new THREE.MeshBasicMaterial({color: SCOL.off, transparent: true, opacity: .9, side: THREE.DoubleSide}));
  const ring = new THREE.Mesh(new THREE.RingGeometry(.14, .155, 6), new THREE.MeshBasicMaterial({color: 0xffc56b, transparent: true, opacity: .5, side: THREE.DoubleSide}));
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({map: glowTex, color: SCOL.off, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0}));
  glow.scale.set(.6, .6, 1); g.add(face, ring, glow); rig.add(g); face.userData.k = k; pick.push(face);
  panels[k] = {g, face, ring, glow, flash: 0, status: "off"}; });
 // beams into the star, and orbit rings
 const beams = [];
 function beam(k, color) { const P = panels[k]; if (!P) return; P.flash = 1;
  const a = P.g.position.clone(), geo = new THREE.BufferGeometry().setFromPoints([a, a.clone().multiplyScalar(.5)]);
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({color: new THREE.Color(color), transparent: true, opacity: 1, blending: THREE.AdditiveBlending}));
  rig.add(line); beams.push({line, life: 1}); }
 for (const [r, tx, tz] of [[2.6, 1.25, .2], [3.05, 1.05, -.45]]) {
  const ringM = new THREE.Mesh(new THREE.RingGeometry(r, r + .008, 160), new THREE.MeshBasicMaterial({color: 0xffc56b, transparent: true, opacity: .22, side: THREE.DoubleSide, blending: THREE.AdditiveBlending}));
  ringM.rotation.set(tx, 0, tz); world.add(ringM); }
 // distant stars
 const sp = new Float32Array(2400 * 3);
 for (let i = 0; i < 2400; i++) { const v = fib(i, 2400, 40 + (i * 7919 % 40)); sp.set([v.x, v.y, v.z], i * 3); }
 const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.BufferAttribute(sp, 3));
 scene.add(new THREE.Points(sg, new THREE.PointsMaterial({color: 0x9aa4c8, size: .09, transparent: true, opacity: .7})));
 // status from the page
 const MOOD = {ok: new THREE.Color(1, .55, .15), attention: new THREE.Color(1, .62, .1), stopped: new THREE.Color(1, .18, .12)};
 function apply() { for (const [k, P] of Object.entries(panels)) { const b = DY.blocks[k]; const st = b ? b.status : "off"; P.status = st;
   P.face.material.color.setHex(SCOL[st]); P.glow.material.color.setHex(SCOL[st]); P.ring.material.opacity = st === "off" ? .15 : .55; }
  starMat.uniforms.heat.value.copy(MOOD[DY.mood] || MOOD.ok); if (reduce) draw(0); }
 document.addEventListener("dy:data", apply);
 document.addEventListener("dy:pulse", e => beam(e.detail.k, e.detail.color));
 let hover = null; document.addEventListener("dy:hover", e => { hover = e.detail; });
 // turning it by hand, with inertia
 let yaw = .4, pitch = .18, vy = 0, drag = null;
 cv.addEventListener("pointerdown", e => { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); });
 cv.addEventListener("pointerup", () => { drag = null; });
 const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
 cv.addEventListener("pointermove", e => {
  if (drag) { const dx = e.clientX - drag[0], dy = e.clientY - drag[1]; drag = [e.clientX, e.clientY];
   yaw += dx * .006; vy = dx * .006; pitch = Math.max(-.9, Math.min(.9, pitch + dy * .004)); }
  const r = cv.getBoundingClientRect(); mouse.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(pick)[0];
  if (hit) { const k = hit.object.userData.k, b = DY.blocks[k];
   tip.innerHTML = `${b ? b.title : k}<small>${b ? WORD[b.status] : ""}</small>`;
   tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px";
   tip.classList.add("on"); cv.style.cursor = "pointer"; hover = k; } else { tip.classList.remove("on"); cv.style.cursor = ""; }
 });
 cv.addEventListener("pointerleave", () => tip.classList.remove("on"));
 cv.addEventListener("click", () => { ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(pick)[0]; if (hit) DY.select(hit.object.userData.k); });
 function size() { const w = box.clientWidth, h = box.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h;
  camera.position.z = w / h < .8 ? 10.2 : 8.6; camera.updateProjectionMatrix(); world.position.y = h > 600 ? .55 : .45; }
 new ResizeObserver(size).observe(box); size();
 let last = performance.now(), T = 0;
 function draw(dt) {
  T += dt; starMat.uniforms.t.value = T;
  if (!drag) { vy *= .95; yaw += dt * .12 * DY.speed + vy * .2; }
  rig.rotation.set(pitch, yaw, 0); shell.rotation.y = T * .015;
  const pulse = .5 + .5 * Math.sin(T * 3);
  for (const [k, P] of Object.entries(panels)) {
   P.flash = Math.max(0, P.flash - dt * 1.3);
   const live = P.status === "live", att = P.status === "attention" || P.status === "stopped";
   P.glow.material.opacity = (live ? .4 : att ? .3 + .3 * pulse : 0) + P.flash * .9 + (hover === k ? .6 : 0);
   const s = 1 + P.flash * .7 + (hover === k ? .35 : 0); P.g.scale.set(s, s, s);
  }
  for (let i = beams.length - 1; i >= 0; i--) { const B = beams[i]; B.life -= dt * 1.2; B.line.material.opacity = Math.max(0, B.life);
   if (B.life <= 0) { rig.remove(B.line); B.line.geometry.dispose(); B.line.material.dispose(); beams.splice(i, 1); } }
  halo.material.opacity = .9 + .1 * Math.sin(T * .8);
  renderer.render(scene, camera);
 }
 function frame(t) { const dt = Math.min(.05, (t - last) / 1000); last = t; draw(dt); if (!document.hidden) requestAnimationFrame(frame); }
 document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduce) { last = performance.now(); requestAnimationFrame(frame); } });
 apply(); if (reduce) draw(0); else requestAnimationFrame(frame);
}
</script></body></html>"""
