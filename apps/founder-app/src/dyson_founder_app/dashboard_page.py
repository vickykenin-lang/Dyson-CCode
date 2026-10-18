"""Gate 8: the Founder's live circuit map.

The master architecture, drawn as it is in the Founder's diagram, with every block's status and
the flows between them lit only when they really carried something in the last 5 minutes. The
data comes from GET /dashboard (read only); nothing on this page can act.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dyson · live map</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet"
 href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap">
<style>
:root{--night:#101a33;--deck:#16223f;--deck2:#1c2a4b;--line:#2a3a60;--ink:#e6ecf8;--soft:#8a97b4;
--req:#3b82f6;--res:#22a06b;--stop:#e5484d;--mon:#f59e0b;--fin:#8b5cf6;--mem:#5fb3c9;--off:#4a5675}
*{box-sizing:border-box}html,body{margin:0;background:var(--night);color:var(--ink)}
body{font:15px/1.5 Manrope,system-ui,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--ink)}a:focus-visible,button:focus-visible,[tabindex]:focus-visible{
outline:2px solid var(--req);outline-offset:3px;border-radius:6px}
header{display:flex;align-items:center;gap:20px;padding:14px 24px;border-bottom:1px solid var(--line)}
header .brand{font-weight:800;letter-spacing:.14em;color:#f2b84b}
header nav{display:flex;gap:16px;font-size:14px;white-space:nowrap}header nav a{opacity:.8;text-decoration:none}
header nav a[aria-current]{opacity:1;border-bottom:2px solid var(--req)}
header .clock{margin-left:auto;font-size:13px;color:var(--soft)}
.hero{padding:26px 24px 8px;max-width:1500px;margin:0 auto}
.hero h1{margin:0;font-size:clamp(24px,3.2vw,38px);font-weight:700;letter-spacing:-.01em;
line-height:1.15;max-width:34ch}
.hero p{margin:8px 0 0;color:var(--soft);max-width:70ch}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px;padding:16px 24px 32px;
max-width:1500px;margin:0 auto}
.mapbox{background:var(--deck);border:1px solid var(--line);border-radius:14px;overflow-x:auto}
svg{display:block;min-width:880px;width:100%;height:auto}
.node rect.body{fill:var(--deck2);stroke:var(--line);stroke-width:1.2;rx:10}
.node{cursor:pointer}.node:hover rect.body{stroke:#5a6d99}
.node.sel rect.body{stroke:var(--ink);stroke-width:2}
.node text{fill:var(--ink);font-family:Manrope,system-ui,sans-serif}
.node .ttl{font-size:14px;font-weight:700}.node .sub{font-size:11.5px;fill:var(--soft)}
.node .key{font-size:12px;font-weight:600}
.node rect.bar{rx:2}
.st-live rect.bar{fill:var(--res)}.st-ok rect.bar{fill:#2f7d5b}.st-attention rect.bar{fill:var(--mon)}
.st-stopped rect.bar{fill:var(--stop)}.st-off rect.bar{fill:var(--off)}
.st-off text{opacity:.6}
.node .ring{fill:none;stroke-width:2;opacity:0}
.st-live .ring{stroke:var(--res);animation:ring 2.4s ease-out infinite}
@keyframes ring{0%{opacity:.45}100%{opacity:0;transform:scale(1.05)}}
.node .ring{transform-box:fill-box;transform-origin:center}
.zone{fill:none;stroke:var(--line);stroke-dasharray:3 5;rx:16}
.zonelbl{fill:var(--soft);font-size:12px;font-weight:600;font-family:Manrope,system-ui,sans-serif}
path.edge{fill:none;stroke-width:1.6;opacity:.28}
path.edge.on{opacity:.85}
path.edge.req{stroke:var(--req)}path.edge.res{stroke:var(--res)}path.edge.stop{stroke:var(--stop);
stroke-dasharray:5 5}path.edge.mon{stroke:var(--mon);stroke-dasharray:2 4}
path.edge.fin{stroke:var(--fin);stroke-dasharray:6 3}path.edge.mem{stroke:var(--mem)}
circle.pkt{r:3.2}
aside{display:flex;flex-direction:column;gap:16px}
.panel{background:var(--deck);border:1px solid var(--line);border-radius:14px;padding:16px}
.panel h2{margin:0 0 4px;font-size:17px}.panel .state{font-size:13px;color:var(--soft);margin:0 0 10px}
.row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-top:1px solid var(--line);
font-size:14px}.row span{color:var(--soft)}.row b{font-weight:600;text-align:right}
.note{font-size:13px;color:var(--soft);margin:10px 0 0}
.feed{list-style:none;margin:0;padding:0;max-height:420px;overflow:auto}
.feed li{display:grid;grid-template-columns:62px 22px 1fr;gap:6px;padding:6px 0;
border-top:1px solid var(--line);font-size:13px}
.feed .t{color:var(--soft)}.feed .b{font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--soft);padding:10px 14px;
border-top:1px solid var(--line)}
.legend i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:6px;
vertical-align:middle}
.foot{max-width:1500px;margin:0 auto;padding:0 24px 28px;color:var(--soft);font-size:13px}
.err{color:var(--mon)}
@media (max-width:980px){.wrap{grid-template-columns:1fr}}
.hint{display:none;margin:0;padding:8px 14px 0;font-size:13px;color:var(--soft)}
@media (max-width:880px){.hint{display:block}}
@media (max-width:560px){header{flex-wrap:wrap;gap:10px 18px;padding:12px 16px}
header .clock{margin-left:0;width:100%}.hero,.wrap,.foot{padding-left:16px;padding-right:16px}}
@media (prefers-reduced-motion:reduce){.st-live .ring{animation:none;opacity:.5}circle.pkt{display:none}}
</style></head><body>
<header><span class="brand">DYSON</span>
<nav><a href="/">Conversation</a><a href="/dashboard" aria-current="page">Live map</a></nav>
<span class="clock" id="clock">Connecting…</span></header>
<section class="hero"><h1 id="headline">Reading the system…</h1>
<p id="subline">Each block is a part of Dyson. A moving light on a line means that connection
was used in the last 5 minutes. Select a block to see its numbers.</p></section>
<div class="wrap">
 <div class="mapbox"><p class="hint">Swipe the map sideways to see every block.</p><svg id="map" viewBox="0 0 1200 800" role="group"
  aria-label="Dyson architecture with live status"></svg>
  <div class="legend">
   <span><i style="background:var(--req)"></i>Requests</span>
   <span><i style="background:var(--res)"></i>Results and verification</span>
   <span><i style="background:var(--stop)"></i>STOP path</span>
   <span><i style="background:var(--mon)"></i>Monitoring</span>
   <span><i style="background:var(--fin)"></i>Money</span>
   <span><i style="background:var(--mem)"></i>Memory and evidence</span>
  </div></div>
 <aside>
  <div class="panel" id="detail" aria-live="polite"><h2>Select a block</h2>
   <p class="state">Its live numbers appear here.</p></div>
  <div class="panel"><h2>What just happened</h2><ul class="feed" id="feed"><li>Loading…</li></ul></div>
 </aside>
</div>
<p class="foot">Read only. Approvals, STOP and PAUSE stay on Direct Founder Controls.</p>
<script>
const NODES = [
 // Founder interface
 ["founder", 30, 70, "Founder"], ["app", 230, 70, "Dyson App"], ["gateway", 430, 70, "Entry Gateway"],
 ["dfc", 700, 70, "Founder Controls"], ["vault", 990, 70, "Bank Vault"],
 // Dyson Core
 ["A", 30, 250, "A · Governance"], ["B", 225, 250, "B · Conversation"], ["C", 420, 250, "C · Model Router"],
 ["D", 615, 250, "D · Orchestrator"], ["E", 810, 250, "E · Monitoring"], ["hermes", 1005, 250, "Hermes"],
 ["F", 30, 410, "F · QA/QC"], ["G", 270, 410, "G · Tool Hub"], ["H", 510, 410, "H · Finance"],
 ["I", 750, 410, "I · Memory"], ["J", 990, 410, "J · Dashboard"],
 // Receptors and the world
 ["external", 30, 640, "Business world"], ["T0", 400, 640, "T0 test Receptor"],
 ["R11", 640, 640, "R11 … Rn"],
];
const W = 172, H = 74;
const EDGES = [
 ["founder","app","req"],["app","gateway","req"],["gateway","B","req"],["B","C","req"],
 ["B","D","req"],["D","G","req"],["G","T0","req"],["hermes","C","req"],["hermes","G","req"],
 ["T0","F","res"],["F","D","res"],["D","B","res"],["gateway","app","res"],["app","founder","res"],
 ["founder","dfc","stop"],["dfc","A","stop"],["A","D","stop"],["A","G","stop"],["A","T0","stop"],
 ["T0","E","mon"],["E","A","mon"],["E","J","mon"],
 ["vault","H","fin"],["T0","H","fin"],["H","J","fin"],
 ["B","I","mem"],["D","I","mem"],["F","I","mem"],
];
const ZONES = [[14, 38, 1172, 128, "Founder interface"], [14, 220, 1172, 278, "Dyson Core on AWS"],
 [14, 610, 868, 128, "Receptors and the business world"]];
const WORD = {live:"Live now", ok:"Up, quiet", attention:"Needs you", stopped:"Stopped",
 off:"Not connected yet"};
const svgNS = "http://www.w3.org/2000/svg";
const map = document.getElementById("map");
const pos = Object.fromEntries(NODES.map(([k, x, y]) => [k, {x, y}]));
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
let DATA = null, NOW = Date.now(), SEL = null;

const el = (tag, attrs, parent) => { const e = document.createElementNS(svgNS, tag);
 for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e);
 return e; };
for (const [x, y, w, h, label] of ZONES) {
 el("rect", {class: "zone", x, y, width: w, height: h}, map);
 el("text", {class: "zonelbl", x: x + 14, y: y - 7}, map).textContent = label;
}
function anchor(a, b) {  // edge from side of a toward b
 const A = pos[a], B = pos[b], ax = A.x + W / 2, ay = A.y + H / 2, bx = B.x + W / 2, by = B.y + H / 2;
 if (Math.abs(ay - by) < 20) {
  const s = bx > ax ? 1 : -1; return [ax + s * W / 2, ay, bx - s * W / 2, by, "h"]; }
 const s = by > ay ? 1 : -1; return [ax, ay + s * H / 2, bx, by - s * H / 2, "v"];
}
const edgeEls = EDGES.map(([a, b, kind], i) => {
 let [x1, y1, x2, y2, o] = anchor(a, b);
 const back = EDGES.findIndex(([p, q]) => p === b && q === a);
 const off = back >= 0 ? (back < i ? 7 : -7) : 0;  // two-way pairs sit side by side
 if (o === "h") { y1 += off; y2 += off; } else { x1 += off; x2 += off; }
 const d = o === "h" ? `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`
  : `M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}`;
 const path = el("path", {class: `edge ${kind}`, d}, map);
 return {a, b, kind, path, pkt: null};
});
const nodeEls = {};
for (const [k, x, y, title] of NODES) {
 const g = el("g", {class: "node st-off", transform: `translate(${x},${y})`, tabindex: 0,
  role: "button", "aria-label": title}, map);
 el("rect", {class: "ring", x: -3, y: -3, width: W + 6, height: H + 6, rx: 12}, g);
 el("rect", {class: "body", width: W, height: H}, g);
 el("rect", {class: "bar", x: 0, y: 10, width: 4, height: H - 20}, g);
 const t = el("text", {class: "ttl", x: 14, y: 24}, g); t.textContent = title;
 const s = el("text", {class: "sub", x: 14, y: 42}, g); s.textContent = "…";
 const v = el("text", {class: "key", x: 14, y: 60}, g); v.textContent = "";
 const pick = () => { SEL = k; render(); };
 g.addEventListener("click", pick);
 g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }});
 nodeEls[k] = {g, s, v};
}
const ago = s => { if (!s) return "no activity yet"; const d = (NOW - Date.parse(s)) / 1000;
 if (d < 60) return Math.max(0, Math.round(d)) + " s ago"; if (d < 3600) return Math.round(d / 60) + " min ago";
 if (d < 86400) return Math.round(d / 3600) + " h ago"; return Math.round(d / 86400) + " d ago"; };
const esc = s => String(s).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const fit = s => s.length > 24 ? s.slice(0, 23) + "…" : s;

function headline(b) {
 const A = b.A || {metrics: []}; const m = Object.fromEntries(A.metrics);
 const waiting = +(m["Approvals waiting"] || 0);
 if (m["Control"] === "stopped") return ["Dyson is stopped.", "Nothing new runs until you resume it on Founder Controls."];
 if (b.founder && b.founder.status === "attention") return ["Dyson is in Survival Mode.",
  "It keeps safe work going and holds anything risky until you are back."];
 const down = Object.values(b).filter(x => x.status === "stopped").map(x => x.title);
 if (down.length) return [`Dyson is running, but ${down.join(" and ")} ${down.length > 1 ? "are" : "is"} down.`,
  "Everything else keeps working. Select the red block for details."];
 if (waiting) return [`Dyson is running. ${waiting} approval${waiting > 1 ? "s are" : " is"} waiting for you.`,
  "Approve or reject on Founder Controls."];
 const live = Object.values(b).filter(x => x.status === "live").length;
 return ["Dyson is running. Nothing needs you right now.",
  `${live} part${live === 1 ? " is" : "s are"} active at the moment. Select a block to see its numbers.`];
}

function render() {
 if (!DATA) return;
 const b = DATA.blocks;
 for (const [k, n] of Object.entries(nodeEls)) {
  const x = b[k]; if (!x) continue;
  n.g.setAttribute("class", `node st-${x.status}${SEL === k ? " sel" : ""}`);
  n.g.setAttribute("aria-label", `${x.title}: ${WORD[x.status]}, ${ago(x.last)}`);
  n.s.textContent = x.last ? `${WORD[x.status]} · ${ago(x.last)}` : WORD[x.status];
  n.v.textContent = x.metrics.length ? fit(`${x.metrics[0][0]}: ${x.metrics[0][1]}`) : "";
 }
 for (const e of edgeEls) {
  const A = b[e.a], B = b[e.b];
  const on = e.kind === "stop" ? (b.A && b.A.status === "stopped")
   : !!(A && B && A.status === "live" && B.status === "live");
  e.path.classList.toggle("on", on);
  if (on && !e.pkt && !reduce) {
   e.pkt = el("circle", {class: "pkt", r: 3.2, fill: getComputedStyle(e.path).stroke}, map);
   const am = el("animateMotion", {dur: `${2.2 + Math.random()}s`, repeatCount: "indefinite",
    path: e.path.getAttribute("d")}, e.pkt);
  } else if (!on && e.pkt) { e.pkt.remove(); e.pkt = null; }
 }
 const [h, s] = headline(b);
 document.getElementById("headline").textContent = h;
 document.getElementById("subline").textContent = s;
 const d = document.getElementById("detail");
 const x = SEL && b[SEL];
 d.innerHTML = x ? `<h2>${esc(x.title)}</h2><p class="state">${WORD[x.status]}, last activity ${ago(x.last)}</p>`
  + x.metrics.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("")
  + (x.note ? `<p class="note">${esc(x.note)}</p>` : "")
  : `<h2>Select a block</h2><p class="state">Its live numbers appear here.</p>`;
 document.getElementById("feed").innerHTML = DATA.feed.length ? DATA.feed.map(f =>
  `<li><span class="t">${ago(f.at)}</span><span class="b">${esc(f.block)}</span><span>${esc(f.text)}</span></li>`
 ).join("") : "<li>Nothing has happened in the last 24 hours.</li>";
}

async function refresh() {
 const clock = document.getElementById("clock");
 try {
  const r = await fetch("/dashboard/data", {cache: "no-store"});
  if (r.status === 401) { location.href = "/"; return; }
  if (!r.ok) throw new Error(r.status);
  DATA = await r.json(); NOW = Date.parse(DATA.as_of);
  clock.textContent = "Updated " + new Date(NOW).toLocaleTimeString();
  clock.classList.remove("err");
  render();
 } catch (e) { clock.textContent = "Can't reach Dyson, retrying…"; clock.classList.add("err"); }
}
refresh(); setInterval(refresh, 5000);
</script></body></html>"""
