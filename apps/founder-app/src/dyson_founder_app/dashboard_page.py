"""Gate 8: the Founder's live command view.

Dyson Core as a glowing sphere with its parts around it, the Founder interface, receptors and the
business world beside it, and every movement driven by real data: a light runs along a line only
when that part was active in the last 5 minutes, a new event fires a burst into its part, and the
sphere turns faster the more parts are live. The data comes from GET /dashboard (read only);
nothing on this page can act.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dyson · live</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet"
 href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap">
<style>
:root{--bg:#06071a;--glass:rgba(22,20,58,.58);--glass2:rgba(34,30,84,.55);--edge:rgba(150,130,255,.18);
--edge2:rgba(170,150,255,.32);--ink:#eceafe;--soft:#9a97c4;--dim:#615e8c;--vio:#8b5cf6;--lil:#c4b5fd;
--cyan:#22d3ee;--green:#34d399;--amber:#fbbf24;--red:#f87171;--blue:#60a5fa;--out:cubic-bezier(.2,.8,.2,1)}
*{box-sizing:border-box}html{background:var(--bg)}
body{margin:0;min-height:100vh;color:var(--ink);font:14px/1.45 Manrope,system-ui,sans-serif;
font-variant-numeric:tabular-nums;background:
radial-gradient(1200px 600px at 85% -10%,rgba(139,92,246,.35),transparent 60%),
radial-gradient(900px 500px at -10% 110%,rgba(34,211,238,.12),transparent 60%),var(--bg)}
a{color:inherit}a:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--lil);outline-offset:3px;border-radius:10px}
.frame{max-width:1560px;margin:0 auto;padding:16px}
.glass{background:var(--glass);border:1px solid var(--edge);border-radius:18px;backdrop-filter:blur(14px);
-webkit-backdrop-filter:blur(14px);box-shadow:inset 0 1px 0 rgba(255,255,255,.05)}
.ph{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 12px}
.ph h2{margin:0;font-size:12.5px;font-weight:700;letter-spacing:.08em;color:var(--lil)}
.live{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--soft)}
.live::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);
animation:blink 2s ease-in-out infinite}@keyframes blink{50%{opacity:.35}}
/* top bar */
.top{display:flex;align-items:center;gap:22px;padding:14px 18px;margin-bottom:14px}
.logo{display:flex;align-items:center;gap:12px;min-width:220px}
.orb{width:38px;height:38px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#fff 0,#c4b5fd 18%,#7c3aed 55%,#1e1b4b 100%);
box-shadow:0 0 18px rgba(139,92,246,.8),0 0 0 3px rgba(139,92,246,.18)}
.logo b{display:block;font-size:17px;letter-spacing:.12em}.logo small{color:var(--soft);font-size:11.5px}
.greet b{display:block;font-size:16px;font-weight:700}.greet span{color:var(--soft);transition:opacity .25s}
.greet span.swap{opacity:0}
.pill{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;border:1px solid var(--edge2);
background:var(--glass2);font-size:13px;white-space:nowrap}
.pill i{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
.pill.bad i{background:var(--red);box-shadow:0 0 10px var(--red)}.pill.warn i{background:var(--amber);box-shadow:0 0 10px var(--amber)}
.tr{margin-left:auto;display:flex;align-items:center;gap:18px}
.navl{font-size:13px;color:var(--soft);text-decoration:none;padding:7px 12px;border-radius:999px;border:1px solid var(--edge)}
.navl:hover{color:var(--ink);border-color:var(--edge2)}
.bell{position:relative;width:22px;height:22px}.bell svg{width:22px;height:22px}
.bell em{position:absolute;top:-6px;right:-8px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:var(--vio);
font:700 11px/17px Manrope,sans-serif;text-align:center;font-style:normal;box-shadow:0 0 10px var(--vio)}
.bell em:empty{display:none}
.clock{text-align:right;line-height:1.2}.clock b{font-size:17px;display:block}.clock small{color:var(--soft);font-size:11.5px}
.clock.err small{color:var(--amber)}
/* main grid */
.grid{display:grid;grid-template-columns:290px minmax(0,1fr) 350px;gap:14px}
.col{display:flex;flex-direction:column;gap:14px;min-width:0}
.card{padding:16px}
/* health */
.ringbox{position:relative;width:200px;height:200px;margin:4px auto 10px}
.ringbox svg{position:absolute;inset:0;width:100%;height:100%}
.spin{animation:spin 30s linear infinite;transform-origin:50% 50%}.spin.rev{animation-duration:46s;animation-direction:reverse}
@keyframes spin{to{transform:rotate(360deg)}}
.ringnum{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.ringnum b{font-size:46px;font-weight:700;line-height:1}.ringnum small{color:var(--soft);font-size:11.5px;max-width:110px}
.ringnum span{margin-top:4px;font-weight:700;font-size:13px}
.grp{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid rgba(150,130,255,.09);font-size:13px}
.grp .ic{width:26px;height:26px}.grp .n{flex:1}.grp .v{font-weight:700}
.ic{display:inline-grid;place-items:center;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid var(--edge)}
.ic svg{width:62%;height:62%}
/* hub */
.hubcard{padding:16px 16px 12px;display:flex;flex-direction:column}
.hubscroll{overflow-x:auto;overflow-y:hidden;margin:0 -6px}
#hub{position:relative;min-width:760px;aspect-ratio:1000/640}
#hub svg.lines{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
#core{position:absolute;left:50%;top:50%;width:36%;aspect-ratio:1;transform:translate(-50%,-50%)}
.corelbl{position:absolute;left:50%;top:calc(50% + 22%);transform:translateX(-50%);font-size:11.5px;color:var(--soft);white-space:nowrap}
.ag{position:absolute;width:190px;transform:translate(-50%,-50%);display:flex;gap:10px;align-items:center;padding:10px 12px;
border-radius:14px;background:rgba(18,16,50,.82);border:1px solid var(--edge);cursor:pointer;
transition:border-color .3s,box-shadow .3s,opacity .3s;animation:enter .7s var(--out) both}
@keyframes enter{from{opacity:0;transform:translate(-50%,-40%) scale(.96)}}
.ag:hover{border-color:var(--edge2)}
.ag .ic{width:38px;height:38px;flex:none;border-color:var(--ac);box-shadow:0 0 14px -4px var(--ac)}
.ag b{display:block;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ag small{display:block;color:var(--soft);font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ag .m{color:var(--ink);opacity:.85}
.ag .dot{position:absolute;top:9px;right:10px;width:7px;height:7px;border-radius:50%;background:var(--dim)}
.st-live .dot{background:var(--green);box-shadow:0 0 8px var(--green)}.st-ok .dot{background:#3f9f7c}
.st-attention .dot{background:var(--amber);box-shadow:0 0 8px var(--amber)}.st-stopped .dot{background:var(--red);box-shadow:0 0 8px var(--red)}
.ag.st-live{border-color:color-mix(in srgb,var(--ac) 45%,transparent);box-shadow:0 0 22px -10px var(--ac)}
.ag.st-attention{border-color:rgba(251,191,36,.55)}.ag.st-stopped{border-color:rgba(248,113,113,.7);box-shadow:0 0 22px -8px var(--red)}
.ag.st-off{opacity:.5}.ag.sel{border-color:var(--lil);box-shadow:0 0 0 1px var(--lil),0 0 26px -6px var(--vio)}
.row{position:relative}.hit::after{content:"";position:absolute;inset:-1px;border-radius:14px;pointer-events:none;
animation:hit 1.1s var(--out) forwards}
@keyframes hit{0%{box-shadow:0 0 0 2px var(--c,#fff),0 0 34px 0 var(--c,#fff)}100%{box-shadow:0 0 0 0 transparent}}
path.ln{fill:none;stroke-width:1.4;opacity:.18;transition:opacity .5s}path.ln.on{opacity:.75}
#detail{margin-top:8px;padding:12px 14px;border-radius:14px;background:rgba(18,16,50,.7);border:1px solid var(--edge);
display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;min-height:56px}
#detail.open{animation:open .35s var(--out)}@keyframes open{from{opacity:.3;transform:translateY(4px)}}
#detail h3{margin:0;font-size:14px}#detail .s{color:var(--soft);font-size:12.5px}
.chip{display:inline-flex;gap:6px;padding:5px 10px;border-radius:999px;background:rgba(255,255,255,.04);border:1px solid var(--edge);font-size:12.5px}
.chip span{color:var(--soft)}#detail .note{flex-basis:100%;color:var(--soft);font-size:12.5px;margin:0}
/* timeline */
.tl{list-style:none;margin:0;padding:0 0 0 4px;max-height:330px;overflow:auto;position:relative}
.tl li{display:grid;grid-template-columns:58px 30px 1fr 22px;gap:8px;align-items:center;padding:7px 0;position:relative}
.tl li::before{content:"";position:absolute;left:72px;top:-8px;bottom:-8px;width:1px;background:rgba(150,130,255,.2);z-index:-1}
.tl .t{color:var(--soft);font-size:11.5px}.tl .ic{width:30px;height:30px}
.tl .x{padding:7px 10px;border-radius:12px;background:rgba(255,255,255,.03);border:1px solid rgba(150,130,255,.1);min-width:0}
.tl .x b{display:block;font-size:13px}.tl .x small{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;color:var(--soft);font-size:12px;overflow:hidden}
.tl .ok{width:22px;height:22px;border-radius:50%;border:1px solid var(--edge);display:grid;place-items:center}
.tl .ok svg{width:12px;height:12px}
.tl li.new{animation:arrive 2.4s var(--out)}
@keyframes arrive{0%{opacity:0;transform:translateX(-12px)}12%{opacity:1;transform:none}}
.tl li.new .x{animation:glowx 2.4s var(--out)}@keyframes glowx{0%{border-color:var(--c);box-shadow:0 0 18px -4px var(--c)}100%{}}
.foot{display:flex;justify-content:space-between;color:var(--soft);font-size:12px;margin-top:10px}
/* queue */
.q{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:12px;background:rgba(255,255,255,.03);
border:1px solid rgba(150,130,255,.1);margin-bottom:8px}
.q .ic{width:30px;height:30px}.q .n{flex:1;min-width:0}.q .n b{display:block;font-size:13px}.q .n small{color:var(--soft);font-size:11.5px}
.q .v{font-weight:700;padding:5px 11px;border-radius:9px;background:rgba(139,92,246,.18);border:1px solid var(--edge2);font-size:12.5px}
.q.hot .v{background:rgba(251,191,36,.16);border-color:rgba(251,191,36,.5);color:var(--amber)}
.badge{font-size:12px;color:var(--amber);font-weight:700}
/* bottom */
.bottom{display:grid;grid-template-columns:1.05fr 1.2fr 1fr 1.05fr;gap:14px;margin-top:14px}.grid>*,.bottom>*{min-width:0}
.row{display:flex;align-items:center;gap:10px;padding:7px 0;border-top:1px solid rgba(150,130,255,.08);cursor:pointer;border-radius:8px}
.row:first-of-type{border-top:0}.row .ic{width:28px;height:28px}.row .n{flex:1;min-width:0}
.row .n b{display:block;font-size:13px}.row .n small{display:block;color:var(--soft);font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .d{width:8px;height:8px;border-radius:50%;background:var(--dim)}
.row.st-live .d{background:var(--green);box-shadow:0 0 8px var(--green)}.row.st-ok .d{background:#3f9f7c}
.row.st-attention .d{background:var(--amber)}.row.st-stopped .d{background:var(--red)}.row.st-off{opacity:.55}
#wave{width:100%;height:120px;display:block}
.big{display:flex;align-items:baseline;gap:10px;margin-top:6px}.big b{font-size:30px;font-weight:700}.big span{color:var(--soft);font-size:12.5px}
.ask{display:flex;align-items:center;gap:14px;margin-top:14px;padding:10px 12px;text-decoration:none}
.ask .orb{width:30px;height:30px}.ask span{flex:1;color:var(--soft)}.ask em{font-style:normal;font-size:12.5px;color:var(--lil)}
.ask:hover{border-color:var(--edge2)}
.hint{display:none;color:var(--soft);font-size:12px;margin:0 0 6px}
@media (max-width:1280px){.grid{grid-template-columns:270px minmax(0,1fr)}.grid>.col:last-child{grid-column:1/-1;flex-direction:row}
.grid>.col:last-child>*{flex:1}.bottom{grid-template-columns:1fr 1fr}}
@media (max-width:860px){.grid{grid-template-columns:1fr}.grid>.col:last-child{flex-direction:column}
.bottom{grid-template-columns:1fr}.top{flex-wrap:wrap;gap:12px}.tr{margin-left:0;width:100%;justify-content:space-between}
.hint{display:block}.logo{min-width:0}}
@media (max-width:520px){.frame{padding:10px}.pill{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}circle.pkt{display:none}}
</style></head><body><div class="frame">
<header class="top glass">
 <div class="logo"><div class="orb"></div><div><b>DYSON</b><small>Sphere · Layer A</small></div></div>
 <div class="greet"><b id="hello">Hello, Founder.</b><span id="headline">Reading the system…</span></div>
 <div class="pill" id="ctl"><i></i><span id="ctltext">Control: checking</span></div>
 <div class="tr"><a class="navl" href="/">Conversation</a>
  <div class="bell" title="Approvals waiting"><svg viewBox="0 0 24 24" fill="none" stroke="#c4b5fd" stroke-width="1.6"
   stroke-linecap="round"><path d="M6 16V11a6 6 0 0112 0v5l2 2H4l2-2zM10 20a2 2 0 004 0"/></svg><em id="bellnum"></em></div>
  <div class="clock" id="clock"><b id="hhmm">--:--</b><small id="clocktext">Connecting…</small></div></div>
</header>
<div class="grid">
 <div class="col">
  <section class="glass card"><div class="ph"><h2>SYSTEM HEALTH</h2><span class="live">Live</span></div>
   <div class="ringbox"><svg viewBox="0 0 200 200" aria-hidden="true"><defs>
    <linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".5" stop-color="#8b5cf6"/>
    <stop offset="1" stop-color="#f472b6"/></linearGradient><filter id="rglow"><feGaussianBlur stdDeviation="3"/></filter></defs>
    <circle cx="100" cy="100" r="92" fill="none" stroke="rgba(150,130,255,.25)" stroke-width="1" stroke-dasharray="1 5" class="spin"/>
    <circle cx="100" cy="100" r="84" fill="none" stroke="rgba(150,130,255,.12)" stroke-width="10"/>
    <circle id="arcglow" cx="100" cy="100" r="84" fill="none" stroke="url(#rg)" stroke-width="10" stroke-linecap="round"
     transform="rotate(-90 100 100)" stroke-dasharray="0 528" filter="url(#rglow)" opacity=".7"/>
    <circle id="arc" cx="100" cy="100" r="84" fill="none" stroke="url(#rg)" stroke-width="6" stroke-linecap="round"
     transform="rotate(-90 100 100)" stroke-dasharray="0 528" style="transition:stroke-dasharray 1s var(--out)"/>
    <circle cx="100" cy="100" r="70" fill="none" stroke="rgba(196,181,253,.3)" stroke-width="1" stroke-dasharray="2 9" class="spin rev"/>
   </svg><div class="ringnum"><b id="hnum">–</b><small id="hsub">connected parts healthy</small><span id="hword"></span></div></div>
   <div id="groups"></div>
  </section>
 </div>
 <div class="col">
  <section class="glass hubcard"><div class="ph"><h2>DYSON CORE</h2><span class="live">Live, lights show work in the last 5 minutes</span></div>
   <p class="hint">Swipe sideways to see every part.</p>
   <div class="hubscroll"><div id="hub" role="group" aria-label="Dyson Core parts with live status">
    <svg class="lines" id="lines" viewBox="0 0 1000 640" preserveAspectRatio="none" aria-hidden="true"><defs>
     <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.6" result="b"/>
     <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><g id="lg"></g><g id="pk"></g></svg>
    <canvas id="core" aria-hidden="true"></canvas><div class="corelbl">Dyson Core on AWS</div>
   </div></div>
   <div id="detail" aria-live="polite"><h3>Select any part</h3><span class="s">Its live numbers appear here.</span></div>
  </section>
 </div>
 <div class="col">
  <section class="glass card"><div class="ph"><h2>WHAT JUST HAPPENED</h2><span class="live">Live</span></div>
   <ul class="tl" id="feed"><li>Loading…</li></ul><div class="foot"><span id="feedn"></span><span>Newest first</span></div></section>
  <section class="glass card"><div class="ph"><h2>WAITING FOR YOU</h2><span class="badge" id="pending"></span></div>
   <div id="queue"></div><div class="foot"><span>Approve, STOP or PAUSE on Direct Founder Controls.</span></div></section>
 </div>
</div>
<div class="bottom">
 <section class="glass card"><div class="ph"><h2>FOUNDER ACCESS</h2><span class="live">Live</span></div><div id="access"></div></section>
 <section class="glass card"><div class="ph"><h2>ACTIVITY, LAST 60 MINUTES</h2><span class="live">Live</span></div>
  <svg id="wave" viewBox="0 0 300 120" preserveAspectRatio="none" aria-hidden="true"></svg>
  <div class="big"><b id="lastev">–</b><span>since the last event</span></div></section>
 <section class="glass card"><div class="ph"><h2>WORK AND CHECKS</h2><span class="live">Live</span></div><div id="work"></div></section>
 <section class="glass card"><div class="ph"><h2>RECEPTORS AND THE WORLD</h2><span class="live">Live</span></div><div id="world"></div></section>
</div>
<a class="ask glass" href="/"><div class="orb"></div><span>Ask Dyson anything</span><em>Opens Conversation</em></a>
</div>
<script>
const IC = {
 shield:"M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z", chat:"M4 5h16v11H9l-5 4V5z",
 chip:"M6 6h12v12H6zM9.5 9.5h5v5h-5zM9 2.5v3M15 2.5v3M9 18.5v3M15 18.5v3M2.5 9h3M2.5 15h3M18.5 9h3M18.5 15h3",
 lock:"M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 017 0v3", db:"M5 6c0-1.6 3.1-3 7-3s7 1.4 7 3-3.1 3-7 3-7-1.4-7-3zM5 6v12c0 1.6 3.1 3 7 3s7-1.4 7-3V6M5 12c0 1.6 3.1 3 7 3s7-1.4 7-3",
 flow:"M4 5h5v5H4zM15 14h5v5h-5zM15 4h5v5h-5zM9 7.5h6M17.5 9v5", tool:"M14.5 5.5a4 4 0 00-5 5l-6 6 2 2 6-6a4 4 0 005-5l-2.2 2.2-2-2 2.2-2.2z",
 check:"M12 3a9 9 0 110 18 9 9 0 010-18zM8 12.5l2.8 2.8L16 9.5", pulse:"M3 12h4l2-5 4 10 2-5h6",
 rupee:"M7 4h10M7 8.5h10M8 4c4.5 0 6.5 2 6.5 4.5S12.5 13 8 13l7.5 7", grid:"M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
 user:"M12 12a4 4 0 100-8 4 4 0 000 8zM4.5 20.5c.5-3.6 3.8-5.5 7.5-5.5s7 1.9 7.5 5.5", phone:"M8 3h8a1 1 0 011 1v16a1 1 0 01-1 1H8a1 1 0 01-1-1V4a1 1 0 011-1zM11 18h2",
 door:"M5 21V4h10v17M15 8l4-1v14M11.5 12.5h.5", stop:"M8.3 3h7.4L21 8.3v7.4L15.7 21H8.3L3 15.7V8.3zM9 12h6",
 vault:"M4 5h16v14H4zM12 8.5a3.5 3.5 0 110 7 3.5 3.5 0 010-7zM12 8.5V7M12 17v-1.5", receptor:"M12 3v4M12 17v4M3 12h4M17 12h4M12 9a3 3 0 110 6 3 3 0 010-6z",
 hex:"M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5", globe:"M12 3a9 9 0 110 18 9 9 0 010-18zM3 12h18M12 3c3.2 3.4 3.2 14.6 0 18M12 3c-3.2 3.4-3.2 14.6 0 18",
 tick:"M5 12.5l4.5 4.5L19 7.5", hold:"M8 5v14M16 5v14", sos:"M12 3l9 16H3zM12 9v5M12 16.5v.5",
};
const ico = (k, c) => `<span class="ic" style="--ac:${c}"><svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.6"
 stroke-linecap="round" stroke-linejoin="round"><path d="${IC[k]}"/></svg></span>`;
// The parts of Dyson Core around the sphere: key, x, y (hub units 1000 x 640), icon, colour.
const CORE = [
 ["A", 500, 62, "shield", "#fbbf24", "A · Governance"],
 ["B", 150, 110, "chat", "#60a5fa", "B · Conversation"], ["C", 150, 230, "chip", "#22d3ee", "C · Model Router"],
 ["hermes", 150, 350, "lock", "#2dd4bf", "Hermes"], ["I", 150, 470, "db", "#38bdf8", "I · Memory"],
 ["D", 850, 110, "flow", "#a78bfa", "D · Orchestrator"], ["G", 850, 230, "tool", "#f472b6", "G · Tool Hub"],
 ["F", 850, 350, "check", "#34d399", "F · QA/QC"], ["E", 850, 470, "pulse", "#fb923c", "E · Monitoring"],
 ["H", 370, 592, "rupee", "#4ade80", "H · Finance"], ["J", 630, 592, "grid", "#c4b5fd", "J · Dashboard"],
];
const OTHER = {founder: ["user", "#c4b5fd"], app: ["phone", "#60a5fa"], gateway: ["door", "#22d3ee"],
 dfc: ["stop", "#f87171"], vault: ["vault", "#4ade80"], T0: ["receptor", "#34d399"], R11: ["hex", "#a78bfa"],
 external: ["globe", "#38bdf8"]};
const LOOK = Object.fromEntries([...CORE.map(([k, , , i, c]) => [k, [i, c]]), ...Object.entries(OTHER)]);
const GROUPS = [["Governance and control", ["A", "dfc"], "shield"], ["Conversation and models", ["B", "C", "hermes"], "chat"],
 ["Work and tools", ["D", "G", "F"], "flow"], ["Monitoring and memory", ["E", "I", "J"], "pulse"],
 ["Money", ["H", "vault"], "rupee"], ["Receptors", ["T0", "R11", "external"], "receptor"],
 ["Founder access", ["founder", "app", "gateway"], "user"]];
const WORD = {live: "Live now", ok: "Up, quiet", attention: "Needs you", stopped: "Stopped", off: "Not connected yet"};
const SC = {live: "#34d399", ok: "#3f9f7c", attention: "#fbbf24", stopped: "#f87171", off: "#615e8c"};
const NS = "http://www.w3.org/2000/svg", reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = id => document.getElementById(id);
let DATA = null, SERVER = Date.now(), AT = performance.now(), SEL = null, FIRST = true;
const now = () => SERVER + (performance.now() - AT);  // the server's clock, advanced locally
const SEEN = new Set(), PREV = {};
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
 for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; };
const esc = s => String(s).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const secs = s => (now() - Date.parse(s)) / 1000;
const span = d => d < 60 ? Math.max(0, Math.round(d)) + " s" : d < 3600 ? Math.round(d / 60) + " min"
 : d < 86400 ? Math.round(d / 3600) + " h" : Math.round(d / 86400) + " d";
const ago = s => s ? span(secs(s)) + " ago" : "no activity yet";
const hm = s => new Date(s).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
const metric = (k, name) => { const x = DATA && DATA.blocks[k]; const m = x && x.metrics.find(([n]) => n === name); return m ? m[1] : null; };

// hub: lines from each part into the sphere, and the part cards
const hub = $("hub"), LG = $("lg"), PK = $("pk"), CX = 500, CY = 320;
const lines = {}, cards = {};
CORE.forEach(([k, x, y, icon, c, short], i) => {
 const mx = (x + CX) / 2, my = (y + CY) / 2, dx = CX - x, dy = CY - y, L = Math.hypot(dx, dy) || 1;
 const d = `M${x},${y} Q${mx - dy / L * 50},${my + dx / L * 50} ${CX},${CY}`;
 lines[k] = {d, c, path: el("path", {class: "ln", d, stroke: c}, LG), pkts: [], n: 0};
 const a = document.createElement("div");
 a.className = "ag st-off"; a.tabIndex = 0; a.setAttribute("role", "button");
 a.style.cssText = `left:${x / 10}%;top:${y / 6.4}%;--ac:${c};animation-delay:${120 + i * 60}ms`;
 a.innerHTML = `${ico(icon, c)}<div style="min-width:0"><b>${short}</b><small class="s">…</small><small class="m"></small></div><i class="dot"></i>`;
 const pick = () => select(k);
 a.addEventListener("click", pick);
 a.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
 hub.appendChild(a); cards[k] = a;
});
function select(k) { SEL = k; render(); const d = $("detail"); d.classList.remove("open"); void d.offsetWidth; d.classList.add("open"); }
function packets(k, n) {  // steady lights on a part's line, both ways; more of them when it is busier
 const L = lines[k]; if (reduce) n = 0; if (L.n === n) return;
 for (const p of L.pkts) p.remove(); L.pkts = []; L.n = n;
 const dur = 2.6 - 0.35 * n;
 for (let i = 0; i < n * 2; i++) {
  const c = el("circle", {r: 3, fill: L.c, filter: "url(#glow)", class: "pkt"}, PK);
  el("animateMotion", {dur: dur + "s", begin: (-i * dur / (n * 2)) + "s", repeatCount: "indefinite", path: L.d,
   keyPoints: i % 2 ? "1;0" : "0;1", keyTimes: "0;1", calcMode: "linear"}, c);
  L.pkts.push(c);
 }
}
function flash(node, color) {
 if (!node || reduce) return;
 node.style.setProperty("--c", color); node.classList.remove("hit"); void node.offsetWidth; node.classList.add("hit");
 setTimeout(() => node.classList.remove("hit"), 1150);
}
function burst(block, delay) {  // a real event: a bright light runs from its part into the core
 setTimeout(() => {
  const L = lines[block], col = (LOOK[block] || [0, "#c4b5fd"])[1];
  if (L && !reduce) {
   const c = el("circle", {r: 6, fill: "#fff", stroke: L.c, "stroke-width": 3, filter: "url(#glow)", class: "pkt"}, PK);
   const m = el("animateMotion", {dur: ".85s", begin: "indefinite", fill: "freeze", path: L.d, keyPoints: "0;1",
    keyTimes: "0;1", calcMode: "spline", keySplines: ".3 0 .2 1"}, c);
   m.beginElement(); setTimeout(() => c.remove(), 900);
  }
  flash(cards[block] || document.querySelector(`[data-k="${block}"]`), col);
  setTimeout(() => { SPHERE.flash = 1; SPHERE.flashCol = col; }, L ? 800 : 0);
 }, delay);
}

function rowHtml(k) {
 const x = DATA.blocks[k]; if (!x) return "";
 const [icon, c] = LOOK[k] || ["grid", "#c4b5fd"], m = x.metrics[0];
 return `<div class="row st-${x.status}" data-k="${k}" tabindex="0" role="button">${ico(icon, c)}<div class="n"><b>${esc(x.title)}</b>
  <small>${WORD[x.status]}${m ? " · " + esc(m[0]) + ": " + esc(m[1]) : ""}</small></div><i class="d"></i></div>`;
}
for (const id of ["access", "work", "world"]) {
 $(id).addEventListener("click", e => { const r = e.target.closest("[data-k]"); if (r) select(r.dataset.k); });
 $(id).addEventListener("keydown", e => { const r = e.target.closest("[data-k]");
  if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(r.dataset.k); } });
}

function headline(b) {
 const m = Object.fromEntries((b.A || {metrics: []}).metrics), waiting = +(m["Approvals waiting"] || 0);
 if (m["Control"] === "stopped") return "Dyson is stopped. Nothing new runs until you resume it.";
 if (b.founder && b.founder.status === "attention") return "Survival Mode is on. Risky work waits for you.";
 const down = Object.values(b).filter(x => x.status === "stopped").map(x => x.title);
 if (down.length) return `${down.join(" and ")} ${down.length > 1 ? "are" : "is"} down. Everything else keeps working.`;
 if (waiting) return `Everything is running. ${waiting} approval${waiting > 1 ? "s wait" : " waits"} for you.`;
 return "Everything is running. Nothing needs you right now.";
}

function render() {
 if (!DATA) return;
 const b = DATA.blocks, all = Object.values(b);
 const recent = {};
 for (const f of DATA.feed) if (secs(f.at) < 300) recent[f.block] = (recent[f.block] || 0) + 1;
 // status changes flash the part
 for (const [k, x] of Object.entries(b)) { if (PREV[k] && PREV[k] !== x.status) burst(k, 0); PREV[k] = x.status; }
 // hub
 for (const [k, a] of Object.entries(cards)) {
  const x = b[k]; if (!x) continue;
  a.className = `ag st-${x.status}${SEL === k ? " sel" : ""}${a.classList.contains("hit") ? " hit" : ""}`;
  a.setAttribute("aria-label", `${x.title}: ${WORD[x.status]}, ${ago(x.last)}`);
  a.querySelector(".s").textContent = x.last ? `${WORD[x.status]} · ${ago(x.last)}` : WORD[x.status];
  const m = x.metrics[0]; a.querySelector(".m").textContent = m ? `${m[0]}: ${m[1]}` : "";
  const on = x.status === "live";
  lines[k].path.classList.toggle("on", on);
  packets(k, on ? Math.min(3, 1 + Math.floor((recent[k] || 0) / 3)) : 0);
 }
 // top bar
 const h = headline(b), hl = $("headline");
 if (hl.textContent !== h) { if (FIRST || reduce) hl.textContent = h;
  else { hl.classList.add("swap"); setTimeout(() => { hl.textContent = h; hl.classList.remove("swap"); }, 250); } }
 const hr = new Date(now()).getHours();
 $("hello").textContent = `Good ${hr < 12 ? "morning" : hr < 17 ? "afternoon" : "evening"}, Founder.`;
 const ctl = metric("A", "Control") || "unknown", surv = metric("A", "Survival Mode"), waiting = +(metric("A", "Approvals waiting") || 0);
 $("ctltext").textContent = `Control: ${ctl}`;
 $("ctl").className = "pill" + (ctl === "stopped" ? " bad" : ctl !== "running" ? " warn" : "");
 $("bellnum").textContent = waiting ? waiting : "";
 // health ring: healthy parts out of the parts that are connected
 const conn = all.filter(x => x.status !== "off"), good = conn.filter(x => x.status !== "stopped");
 $("hnum").textContent = good.length; $("hsub").textContent = `of ${conn.length} connected parts healthy`;
 const bad = all.some(x => x.status === "stopped"), warn = all.some(x => x.status === "attention");
 $("hword").textContent = bad ? "Something is down" : warn ? "Needs you" : "All clear";
 $("hword").style.color = bad ? SC.stopped : warn ? SC.attention : SC.live;
 const arc = 528 * (conn.length ? good.length / conn.length : 0);
 for (const id of ["arc", "arcglow"]) $(id).setAttribute("stroke-dasharray", `${arc} 528`);
 $("groups").innerHTML = GROUPS.map(([name, ks, icon]) => {
  const xs = ks.map(k => b[k]).filter(Boolean), c = xs.filter(x => x.status !== "off");
  const up = c.filter(x => x.status === "live" || x.status === "ok" || x.status === "attention").length;
  const st = c.some(x => x.status === "stopped") ? "stopped" : c.some(x => x.status === "attention") ? "attention" : c.length ? "live" : "off";
  return `<div class="grp">${ico(icon, "#c4b5fd")}<span class="n">${name}</span><span class="v" style="color:${SC[st]}">${c.length ? up + "/" + c.length + " up" : "not connected"}</span></div>`;
 }).join("");
 // queue
 const held = +(metric("D", "Held") || 0), kills = metric("G", "Kill switches on");
 const Q = [["hold", "#fbbf24", "Approvals waiting", "Approve or reject on Founder Controls", waiting, waiting > 0],
  ["hold", "#a78bfa", "Tasks held for review", "Orchestrator", held, held > 0],
  ["sos", "#f87171", "Survival Mode", "Starts after 72 h without you", surv || "–", surv && surv !== "off"],
  ["stop", "#f472b6", "Kill switches on", "Tool Hub", kills || "–", kills && kills !== "none"]];
 $("queue").innerHTML = Q.map(([i, c, n, s, v, hot]) =>
  `<div class="q${hot ? " hot" : ""}">${ico(i, c)}<div class="n"><b>${n}</b><small>${s}</small></div><span class="v">${esc(v)}</span></div>`).join("");
 $("pending").textContent = waiting ? `${waiting} pending` : "Nothing pending";
 // bottom cards
 $("access").innerHTML = ["founder", "app", "gateway", "dfc", "vault"].map(rowHtml).join("");
 $("work").innerHTML = ["D", "F", "G", "C"].map(rowHtml).join("");
 $("world").innerHTML = ["T0", "R11", "external"].map(rowHtml).join("");
 if (SEL) document.querySelectorAll(`[data-k="${SEL}"]`).forEach(r => r.style.background = "rgba(139,92,246,.14)");
 // detail
 const x = SEL && b[SEL], d = $("detail");
 d.innerHTML = x ? `<h3>${esc(x.title)}</h3><span class="s" style="color:${SC[x.status]}">${WORD[x.status]}, last activity ${ago(x.last)}</span>`
  + x.metrics.map(([k, v]) => `<span class="chip"><span>${esc(k)}</span>${esc(v)}</span>`).join("")
  + (x.note ? `<p class="note">${esc(x.note)}</p>` : "")
  : `<h3>Select any part</h3><span class="s">Its live numbers appear here.</span>`;
 // sphere
 SPHERE.speed = 0.25 + 1.75 * all.filter(x => x.status === "live").length / Math.max(1, all.length);
 SPHERE.mood = bad ? [248, 113, 113] : warn ? [251, 191, 36] : [139, 92, 246];
 feed();
}

const ITEMS = new Map();
function feed() {
 const ul = $("feed"), fresh = [];
 if (!DATA.feed.length) { ul.innerHTML = "<li>Nothing has happened in the last 24 hours.</li>"; ITEMS.clear(); $("feedn").textContent = ""; return; }
 const keep = new Map();
 const lis = DATA.feed.map(f => {
  const k = f.at + "|" + f.block + "|" + f.text; let li = ITEMS.get(k);
  if (!li) {
   const [icon, c] = LOOK[f.block] || ["grid", "#c4b5fd"], t = DATA.blocks[f.block];
   li = document.createElement("li"); li.dataset.at = f.at; li.style.setProperty("--c", c);
   li.innerHTML = `<span class="t">${hm(f.at)}</span>${ico(icon, c)}<div class="x"><b>${esc(t ? t.title : f.block)}</b>
    <small>${esc(f.text)}</small></div><span class="ok"><svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2.4"
    stroke-linecap="round" stroke-linejoin="round"><path d="${IC.tick}"/></svg></span>`;
   if (!SEEN.has(k)) { SEEN.add(k); if (!FIRST) { li.classList.add("new"); fresh.push(f); } }
  }
  keep.set(k, li); return li;
 });
 ITEMS.clear(); for (const [k, v] of keep) ITEMS.set(k, v);
 ul.replaceChildren(...lis);
 $("feedn").textContent = `Latest ${DATA.feed.length} events`;
 fresh.reverse().forEach((f, i) => burst(f.block, i * 280));  // oldest new event first
 tick();
}

function wave() {  // events per 2 minutes over the last hour, as a glowing line
 const w = $("wave"), bins = new Array(30).fill(0);
 for (const f of DATA.feed) { const a = secs(f.at); if (a >= 0 && a < 3600) bins[29 - Math.floor(a / 120)]++; }
 const mx = Math.max(2, ...bins), pts = bins.map((v, i) => [i * 300 / 29, 108 - v / mx * 88]);
 let d = `M${pts[0][0]},${pts[0][1]}`;
 for (let i = 1; i < pts.length; i++) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], cx = (x0 + x1) / 2;
  d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`; }
 w.innerHTML = `<defs><linearGradient id="wf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".55"/>
  <stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient><linearGradient id="ws" x1="0" x2="1">
  <stop offset="0" stop-color="#22d3ee"/><stop offset=".6" stop-color="#8b5cf6"/><stop offset="1" stop-color="#f472b6"/></linearGradient>
  <filter id="wg"><feGaussianBlur stdDeviation="2.5"/></filter></defs>
  ${[30, 60, 90].map(y => `<line x1="0" x2="300" y1="${y}" y2="${y}" stroke="rgba(150,130,255,.08)"/>`).join("")}
  <path d="${d} L300,120 L0,120Z" fill="url(#wf)"/><path d="${d}" fill="none" stroke="url(#ws)" stroke-width="4" filter="url(#wg)" opacity=".8"/>
  <path d="${d}" fill="none" stroke="url(#ws)" stroke-width="1.8"/>
  <circle cx="${pts[29][0] - 2}" cy="${pts[29][1]}" r="3.5" fill="#f472b6" filter="url(#glow)"><animate attributeName="r" values="3;5.5;3" dur="1.6s" repeatCount="indefinite"/></circle>`;
}

function tick() {  // once a second: every "ago" stays true without waiting for the next poll
 if (!DATA) return;
 for (const [k, a] of Object.entries(cards)) { const x = DATA.blocks[k];
  if (x && x.last) a.querySelector(".s").textContent = `${WORD[x.status]} · ${ago(x.last)}`; }
 $("lastev").textContent = DATA.feed[0] ? span(secs(DATA.feed[0].at)) : "–";
 $("hhmm").textContent = new Date(now()).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
 const age = Math.round((performance.now() - AT) / 1000);
 if (!$("clock").classList.contains("err")) $("clocktext").textContent = age < 2 ? "Live, just updated" : `Live, updated ${age} s ago`;
 wave();
}

// The core: a lattice sphere that glows in the system's mood and turns faster the more parts are live.
const SPHERE = {speed: 0.6, mood: [139, 92, 246], flash: 0, flashCol: "#fff"};
(function core() {
 const cv = $("core"), g = cv.getContext("2d"), N = 150, P = [];
 for (let i = 0; i < N; i++) { const y = 1 - 2 * (i + .5) / N, r = Math.sqrt(1 - y * y), t = i * 2.39996;
  P.push([Math.cos(t) * r, y, Math.sin(t) * r]); }
 const E = [];
 for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
  const d = Math.hypot(P[i][0] - P[j][0], P[i][1] - P[j][1], P[i][2] - P[j][2]); if (d < 0.3) E.push([i, j]); }
 let a = 0, last = performance.now();
 function frame(t) {
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  if (!w) { requestAnimationFrame(frame); return; }
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const dt = Math.min(0.05, (t - last) / 1000); last = t; a += dt * 0.45 * SPHERE.speed;
  SPHERE.flash = Math.max(0, SPHERE.flash - dt * 1.4);
  const [mr, mg, mb] = SPHERE.mood, ox = w / 2, oy = h / 2, R = w * 0.36;
  const halo = g.createRadialGradient(ox, oy, R * 0.2, ox, oy, R * 1.45);
  halo.addColorStop(0, `rgba(${mr},${mg},${mb},${0.55 + SPHERE.flash * 0.4})`); halo.addColorStop(0.55, `rgba(${mr},${mg},${mb},.18)`);
  halo.addColorStop(1, `rgba(${mr},${mg},${mb},0)`);
  g.fillStyle = halo; g.beginPath(); g.arc(ox, oy, R * 1.45, 0, 7); g.fill();
  const body = g.createRadialGradient(ox - R * .3, oy - R * .35, R * .05, ox, oy, R);
  body.addColorStop(0, "rgba(255,255,255,.9)"); body.addColorStop(.25, `rgba(${mr + 40},${mg + 60},255,.55)`);
  body.addColorStop(1, `rgba(${mr * .3 | 0},${mg * .2 | 0},${mb * .5 | 0},.35)`);
  g.fillStyle = body; g.beginPath(); g.arc(ox, oy, R, 0, 7); g.fill();
  const ca = Math.cos(a), sa = Math.sin(a), tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
  const Q = P.map(([x, y, z]) => { const X = x * ca + z * sa, Z = -x * sa + z * ca, Y = y * ct - Z * st, Z2 = y * st + Z * ct;
   return [ox + X * R, oy + Y * R, Z2]; });
  g.lineWidth = 0.8;
  for (const [i, j] of E) { const z = (Q[i][2] + Q[j][2]) / 2;
   g.strokeStyle = `rgba(220,210,255,${z < 0 ? 0.42 : 0.1})`; g.beginPath(); g.moveTo(Q[i][0], Q[i][1]); g.lineTo(Q[j][0], Q[j][1]); g.stroke(); }
  for (const [x, y, z] of Q) { g.fillStyle = z < 0 ? "rgba(255,255,255,.95)" : "rgba(200,190,255,.35)";
   g.beginPath(); g.arc(x, y, z < 0 ? 1.7 : 1.1, 0, 7); g.fill(); }
  g.strokeStyle = `rgba(196,181,253,.28)`; g.lineWidth = 1;  // orbit rings
  for (const [k, s] of [[1.22, 0.32], [1.36, -0.22]]) { g.beginPath(); g.ellipse(ox, oy, R * k, R * k * 0.3, s + a * 0.2, 0, 7); g.stroke(); }
  if (SPHERE.flash > 0) { g.strokeStyle = SPHERE.flashCol; g.globalAlpha = SPHERE.flash; g.lineWidth = 2;
   g.beginPath(); g.arc(ox, oy, R * (1.05 + (1 - SPHERE.flash) * 0.35), 0, 7); g.stroke(); g.globalAlpha = 1; }
  if (!reduce && !document.hidden) requestAnimationFrame(frame);
 }
 document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduce) { last = performance.now(); requestAnimationFrame(frame); } });
 requestAnimationFrame(frame);
})();

async function refresh() {
 try {
  const r = await fetch("/dashboard/data", {cache: "no-store"});
  if (r.status === 401) { location.href = "/"; return; }
  if (!r.ok) throw new Error(r.status);
  DATA = await r.json(); SERVER = Date.parse(DATA.as_of); AT = performance.now();
  $("clock").classList.remove("err");
  render();
  if (FIRST) {  // opening moment: replay the latest events into the core, oldest first
   FIRST = false;
   DATA.feed.slice(0, 10).reverse().forEach((f, i) => burst(f.block, 1000 + i * 320));
  }
 } catch (e) { $("clock").classList.add("err"); $("clocktext").textContent = "Can't reach Dyson, retrying…"; }
}
refresh(); setInterval(refresh, 5000); setInterval(tick, 1000);
</script></body></html>"""
