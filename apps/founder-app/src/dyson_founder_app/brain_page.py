"""The Founder's second brain as a galaxy — a JARVIS-style operating console (Dyson OS).

Full-screen WebGL: every note is a star, coloured by its project, placed by a server-side layout
(cluster per project) and linked to its nearest neighbours with the reason spelled out. Around it:
a control rail (search, inspector, top hubs, display), a DYSON HUD, and a lower dock that embeds the
real live map (the wiring observatory) and the real sandbox screen. three.js is served from this
app (no outside CDN); the graph data comes from GET /brain/data (read only).
"""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Dyson OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Rajdhani:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --void:#04060c;--void2:#070b16;--glass:rgba(10,16,30,.72);--glass2:rgba(8,13,26,.92);
  --ink:#dfe8ff;--soft:#8793b5;--dim:#515d80;--line:rgba(90,150,210,.16);
  --cyan:#2fe0e0;--cyan-d:#13343f;--teal:#3ddc97;--amber:#ffb84d;--red:#ff5468;
  --mono:"IBM Plex Mono",ui-monospace,monospace;--ui:"Rajdhani",system-ui,sans-serif;--dis:"Orbitron",var(--ui);
  color-scheme:dark;
}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font-family:var(--ui);background:radial-gradient(1200px 820px at 60% -8%,#0b1430 0%,var(--void) 62%),var(--void);color:var(--ink);overflow:hidden}
#gl{position:fixed;inset:0;display:block;cursor:grab}#gl:active{cursor:grabbing}
.fx{position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(60,120,160,.03) 0 1px,transparent 1px 3px);mix-blend-mode:overlay;opacity:.5;z-index:1}
button{font:inherit;color:inherit;cursor:pointer}:focus-visible{outline:1.5px solid var(--cyan);outline-offset:2px}
a{color:var(--cyan)}
.tip{position:fixed;z-index:30;pointer-events:none;padding:6px 9px;border-radius:8px;background:rgba(7,12,25,.94);border:1px solid var(--line);font:500 11px var(--mono);color:var(--ink);opacity:0;transition:opacity .12s;white-space:nowrap}
.top{position:fixed;left:50%;top:calc(10px + env(safe-area-inset-top,0px));transform:translateX(-50%);z-index:20;display:flex;gap:6px;align-items:center;background:var(--glass);border:1px solid var(--line);border-radius:999px;padding:5px 7px;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
.top button,.top a{font:600 12px var(--mono);letter-spacing:.05em;color:var(--soft);background:transparent;border:0;border-radius:999px;padding:7px 13px;text-decoration:none}
.top a.here{color:var(--cyan);background:var(--cyan-d)}
.top button:hover,.top a:hover{color:var(--ink)}.top .sep{width:1px;height:16px;background:var(--line)}
.rail{position:fixed;z-index:18;width:248px;background:var(--glass);border:1px solid var(--line);border-radius:16px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 24px 60px rgba(0,0,0,.5)}
.rail.left{left:max(12px,env(safe-area-inset-left,0px));top:calc(12px + env(safe-area-inset-top,0px));bottom:calc(12px + env(safe-area-inset-bottom,0px));display:flex;flex-direction:column;overflow:hidden}
.rail.right{right:max(12px,env(safe-area-inset-right,0px));top:calc(12px + env(safe-area-inset-top,0px));width:230px;max-height:calc(100% - 24px);display:flex;flex-direction:column}
.rail .scroll{overflow-y:auto;padding:14px 15px;display:flex;flex-direction:column;gap:16px}
.sec>h2{font:700 10px var(--mono);letter-spacing:.22em;color:var(--dim);margin:0 0 9px;text-transform:uppercase}
.brand{padding:15px 15px 12px;border-bottom:1px solid var(--line)}
.brand .name{font:700 17px/1 var(--dis);letter-spacing:.14em;color:#eef4ff}.brand .name b{color:var(--cyan)}
.brand .meta{font:500 11px var(--mono);color:var(--soft);margin-top:7px}
.brand .sub{font:600 11px var(--mono);color:var(--dim);margin-top:3px}
.search{width:100%;background:var(--void2);border:1px solid var(--line);border-radius:10px;color:var(--ink);font:500 13px var(--ui);padding:9px 11px}
.search::placeholder{color:var(--dim)}
.inspect{font:400 12.5px/1.5 var(--ui);color:var(--soft)}
.inspect .file{font:500 13px var(--mono);color:var(--ink);word-break:break-word;margin:0 0 3px}
.inspect .chip{display:inline-flex;align-items:center;gap:6px;font:500 11px var(--mono);color:var(--soft);margin-bottom:6px}
.inspect .dot{width:9px;height:9px;border-radius:50%;box-shadow:0 0 7px currentColor}
.inspect ul{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:7px}
.inspect li{border-left:2px solid var(--line);padding-left:9px;font-size:12px}
.inspect li .to{color:var(--ink);font-family:var(--mono);font-size:11.5px;word-break:break-word}
.inspect li .why{color:var(--dim)}
.hubs,.filter{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.hubs li,.filter li{display:flex;align-items:center;gap:9px;font-size:12.5px;cursor:pointer;padding:3px 5px;border-radius:7px}
.hubs li:hover,.filter li:hover{background:rgba(47,224,224,.08)}
.filter li.off{opacity:.34}
.hubs .dot,.filter .dot{width:8px;height:8px;border-radius:50%;flex:none;box-shadow:0 0 7px currentColor}
.hubs .nm,.filter .nm{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hubs .ct,.filter .ct{margin-left:auto;font:500 11px var(--mono);color:var(--dim)}
.slider{display:grid;gap:5px;margin-bottom:11px}
.slider label{display:flex;justify-content:space-between;font:500 12px var(--ui);color:var(--soft)}
.slider label span{font-family:var(--mono);color:var(--dim);font-size:11px}
input[type=range]{-webkit-appearance:none;appearance:none;height:3px;border-radius:3px;background:var(--line)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:13px;height:13px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan);cursor:pointer}
input[type=range]::-moz-range-thumb{width:13px;height:13px;border:0;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan)}
.toggle{display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--soft);padding:3px 0}
.sw{width:34px;height:18px;border-radius:999px;background:var(--void2);border:1px solid var(--line);position:relative;transition:.2s}
.sw::after{content:"";position:absolute;top:1px;left:1px;width:14px;height:14px;border-radius:50%;background:var(--dim);transition:.2s}
.toggle[aria-pressed="true"] .sw{background:var(--cyan-d);border-color:var(--cyan)}
.toggle[aria-pressed="true"] .sw::after{left:17px;background:var(--cyan);box-shadow:0 0 7px var(--cyan)}
.hud{padding:14px 15px;border-top:1px solid var(--line);display:flex;flex-direction:column;align-items:center;gap:9px}
.ring{position:relative;width:140px;height:140px}.ring svg{position:absolute;inset:0}
.ring .core{position:absolute;inset:0;display:grid;place-items:center;text-align:center}
.ring .core b{font:700 15px var(--dis);letter-spacing:.2em;color:var(--cyan);text-shadow:0 0 14px rgba(47,224,224,.6)}
.ring .core small{display:block;font:500 9px var(--mono);letter-spacing:.24em;color:var(--soft);margin-top:4px}
@keyframes spin{to{transform:rotate(360deg)}}@keyframes spinr{to{transform:rotate(-360deg)}}@keyframes pulse{50%{opacity:.35}}
.ring .r1{transform-origin:center;animation:spin 18s linear infinite}.ring .r2{transform-origin:center;animation:spinr 26s linear infinite}
.status{font:600 12px var(--mono);letter-spacing:.14em;color:var(--teal);display:flex;align-items:center;gap:8px}
.status i{width:7px;height:7px;border-radius:50%;background:var(--teal);box-shadow:0 0 9px var(--teal);animation:pulse 1.4s ease-in-out infinite}
.model{font:500 11px var(--mono);color:var(--soft);background:var(--void2);border:1px solid var(--line);border-radius:999px;padding:4px 11px}.model b{color:var(--teal)}
.senses{display:grid;grid-template-columns:1fr 1fr;gap:6px;width:100%;margin-top:3px}
.senses .sns{display:flex;justify-content:space-between;font:600 10px var(--mono);letter-spacing:.12em;color:var(--dim);background:var(--void2);border:1px solid var(--line);border-radius:8px;padding:6px 9px}
.live{position:fixed;left:max(12px,env(safe-area-inset-left,0px));bottom:calc(12px + env(safe-area-inset-bottom,0px));z-index:19;width:248px;height:170px;background:var(--glass2);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.live .hd{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid var(--line);font:600 11px var(--mono);letter-spacing:.14em;color:var(--soft)}
.live .hd .rec{width:7px;height:7px;border-radius:50%;background:var(--red);box-shadow:0 0 9px var(--red);animation:pulse 1.3s infinite}
.live .hd .tag{margin-left:auto;font-size:9px;color:var(--dim);border:1px solid var(--line);border-radius:5px;padding:2px 5px}
.live .term{flex:1;overflow:hidden;padding:9px 11px;font:500 11px/1.55 var(--mono);color:var(--teal);white-space:pre-wrap}
.live .term .cmd{color:var(--cyan)}.live .term .cur{color:var(--ink);animation:blink 1s step-end infinite}@keyframes blink{50%{opacity:0}}
.dock{position:fixed;left:calc(268px + env(safe-area-inset-left,0px));right:calc(250px + env(safe-area-inset-right,0px));bottom:calc(12px + env(safe-area-inset-bottom,0px));top:56%;z-index:17;background:var(--glass);border:1px solid var(--line);border-radius:16px;overflow:hidden;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);display:flex;flex-direction:column;box-shadow:0 24px 60px rgba(0,0,0,.5)}
.dock .tabs{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line)}
.dock .tabs button{font:700 11px var(--mono);letter-spacing:.12em;color:var(--soft);background:transparent;border:1px solid transparent;border-radius:999px;padding:6px 13px}
.dock .tabs button[aria-pressed="true"]{color:var(--cyan);border-color:var(--line);background:var(--cyan-d)}
.dock .tabs .stop{margin-left:auto;font:700 10px var(--mono);letter-spacing:.1em;color:var(--red);border:1px solid rgba(255,84,104,.4);border-radius:999px;padding:5px 12px;text-decoration:none}
.dock .body{flex:1;min-height:0;position:relative;background:#060a12}
.pane{display:none;position:absolute;inset:0}.pane.on{display:block}
.pane iframe{width:100%;height:100%;border:0;display:block}
.loading{position:fixed;inset:0;display:grid;place-items:center;color:var(--soft);font:500 13px var(--mono);z-index:5}
.mobtab{display:none}
@media (max-width:860px){
  .rail,.live,.dock{display:none}
  .rail.show,.live.show,.dock.show{display:flex}
  .rail.left,.rail.right{width:min(86vw,300px);bottom:auto;max-height:66vh}
  .live.show{width:min(86vw,300px)}
  .dock.show{left:max(12px,env(safe-area-inset-left,0px));right:max(12px,env(safe-area-inset-right,0px));top:auto;height:54vh}
  .mobtab{display:inline-flex}
}
</style>
</head><body>
<canvas id="gl"></canvas>
<div class="fx"></div>
<div class="loading" id="loading">booting dyson os…</div>
<div class="tip" id="tip"></div>

<div class="top">
  <button id="fit">◎ Fit</button><span class="sep"></span>
  <a href="/">Conversation</a><a href="/dashboard">Live map</a><a href="/brain" class="here">Brain</a>
  <button id="t-left" class="mobtab">☰</button><button id="t-right" class="mobtab">◔</button>
</div>

<aside class="rail left" id="rail-left">
  <div class="brand"><div class="name">DYSON <b>OS</b></div><div class="meta" id="count">loading…</div><div class="sub">second brain · live map</div></div>
  <div class="scroll">
    <div class="sec"><input class="search" id="search" placeholder="Search the brain…" autocomplete="off"></div>
    <div class="sec"><h2>Inspector</h2><div class="inspect" id="inspect">Click a star to focus it — that note and its links light up, and you can read why they connect. Click empty space to release.</div></div>
    <div class="sec"><h2>Top hubs</h2><ul class="hubs" id="hubs"></ul></div>
    <div class="sec"><h2>Display</h2>
      <div class="slider"><label>Spread <span id="spread-v"></span></label><input type="range" id="spread" min="60" max="180" value="100"></div>
      <div class="slider"><label>Link glow <span id="glow-v"></span></label><input type="range" id="glow" min="0" max="100" value="80"></div>
      <div class="toggle" id="t-rotate" aria-pressed="true">Auto-rotate <span class="sw"></span></div>
    </div>
  </div>
</aside>

<aside class="rail right" id="rail-right">
  <div class="scroll" style="padding-bottom:4px"><div class="sec"><h2>Filter · projects</h2><ul class="filter" id="filter" style="max-height:40vh;overflow-y:auto"></ul></div></div>
  <div class="hud">
    <div class="ring"><svg viewBox="0 0 140 140" aria-hidden="true">
      <circle cx="70" cy="70" r="66" fill="none" stroke="rgba(47,224,224,.14)" stroke-width="1"/>
      <g class="r1"><circle cx="70" cy="70" r="58" fill="none" stroke="var(--cyan)" stroke-width="1.5" stroke-dasharray="6 10" opacity=".8"/></g>
      <g class="r2"><circle cx="70" cy="70" r="48" fill="none" stroke="var(--teal)" stroke-width="1" stroke-dasharray="2 8" opacity=".7"/></g>
      <circle cx="70" cy="70" r="37" fill="none" stroke="rgba(47,224,224,.25)" stroke-width="1"/></svg>
      <div class="core"><div><b>DYSON</b><small>ONLINE</small></div></div></div>
    <div class="status" id="status"><i></i><span>LISTENING</span></div>
    <div class="model">model · <b id="model">gemini-3-flash</b></div>
    <div class="senses"><div class="sns">EYES <em>off</em></div><div class="sns">HOLO <em>off</em></div><div class="sns">FOCUS <em>off</em></div><div class="sns">VOICE <em>ready</em></div></div>
  </div>
</aside>

<section class="live" id="live"><div class="hd"><span class="rec"></span> DYSON · LIVE <span class="tag">demo</span></div><div class="term" id="term"></div></section>

<section class="dock" id="dock">
  <div class="tabs">
    <button id="tab-wire" aria-pressed="true">◇ LIVE MAP</button>
    <button id="tab-box" aria-pressed="false">▣ SANDBOX</button>
    <a class="stop" href="__CONTROLS_URL__" target="_blank" rel="noopener">STOP</a>
  </div>
  <div class="body">
    <div class="pane on" id="pane-wire"><iframe id="if-wire" title="Live map"></iframe></div>
    <div class="pane" id="pane-box"><iframe id="if-box" title="Dyson sandbox" allow="fullscreen;clipboard-read;clipboard-write"></iframe></div>
  </div>
</section>

<script type="module">
import * as THREE from '/static/three.module.min.js';
const $=id=>document.getElementById(id);
const shortP=s=>String(s).replace(/^repo:/,'');

// lower dock: the real live map + the real sandbox, loaded on first open
const ifWire=$('if-wire'), ifBox=$('if-box');
ifWire.src='/dashboard';
let boxLoaded=false;
function dock(which){const w=which==='wire';$('tab-wire').setAttribute('aria-pressed',String(w));$('tab-box').setAttribute('aria-pressed',String(!w));
  $('pane-wire').classList.toggle('on',w);$('pane-box').classList.toggle('on',!w);
  if(!w&&!boxLoaded){boxLoaded=true;ifBox.src='/sandbox-screen/vnc.html?autoconnect=1&resize=scale&path=/sandbox-ws';}}
$('tab-wire').onclick=()=>dock('wire');$('tab-box').onclick=()=>dock('box');
$('t-left').onclick=()=>{$('rail-left').classList.toggle('show');$('live').classList.toggle('show');$('dock').classList.toggle('show');};
$('t-right').onclick=()=>$('rail-right').classList.toggle('show');

// DYSON LIVE feed (presentational for now)
(function(){const feed=[['cmd','$ dyson → pull up: GST invoice'],['','  grounding repo:rio/finance ✓'],['cmd','$ ruff check services/knowledge'],['','  All checks passed!'],['cmd','$ pytest -q'],['','  30 passed'],['cmd','$ sandbox → open browser'],['','  streaming ▸ 1280×800']];
  const term=$('term');let i=0;function step(){if(i>=feed.length){i=0;term.textContent='';}const d=document.createElement('div');if(feed[i][0])d.className=feed[i][0];term.appendChild(d);const cur=document.createElement('span');cur.className='cur';cur.textContent='▌';term.appendChild(cur);const txt=feed[i][1];let n=0;(function ch(){if(n<txt.length){d.textContent+=txt[n++];setTimeout(ch,20+Math.random()*26);}else{cur.remove();i++;if(term.childElementCount>6)term.removeChild(term.firstChild);setTimeout(step,560);}})();}step();})();
(function(){const st=['LISTENING','THINKING','SPEAKING','REACHING FOR TOOLS'];let i=0,el=$('status').querySelector('span');setInterval(()=>{i=(i+1)%st.length;el.textContent=st[i];},2600);})();

let data;
try{ const r=await fetch('/brain/data',{headers:{Accept:'application/json'}}); data=await r.json(); }
catch(e){ $('loading').textContent='could not load the brain'; throw e; }
const nodes=data.nodes||[], links=data.links||[];
if(!nodes.length){ $('loading').textContent='the brain is empty — ingest some notes first'; }
else boot();

function boot(){
  const byId={};nodes.forEach(n=>byId[n.id]=n);
  const srcs=Array.from(new Set(nodes.map(n=>n.source))).sort();
  const col={};srcs.forEach((s,i)=>{const c=new THREE.Color();c.setHSL(i/srcs.length,.68,.62);col[s]=c;});
  const counts={},deg={};nodes.forEach(n=>counts[n.source]=(counts[n.source]||0)+1);
  links.forEach(l=>{deg[l.source]=(deg[l.source]||0)+1;deg[l.target]=(deg[l.target]||0)+1;});
  $('count').textContent=nodes.length+' notes · '+links.length+' links · '+srcs.length+' projects';
  $('loading').style.display='none';

  const hubs=nodes.slice().sort((a,b)=>(deg[b.id]||0)-(deg[a.id]||0)).slice(0,8);
  $('hubs').innerHTML=hubs.map(n=>'<li data-id="'+n.id.replace(/"/g,'&quot;')+'"><span class="dot" style="color:#fff;background:hsl('+Math.round(srcs.indexOf(n.source)/srcs.length*360)+',68%,62%)"></span><span class="nm">'+n.label+'</span><span class="ct">'+(deg[n.id]||0)+'</span></li>').join('');
  const hidden={};
  $('filter').innerHTML=srcs.map(s=>'<li data-src="'+s.replace(/"/g,'&quot;')+'"><span class="dot" style="color:#fff;background:hsl('+Math.round(srcs.indexOf(s)/srcs.length*360)+',68%,62%)"></span><span class="nm">'+shortP(s)+'</span><span class="ct">'+counts[s]+'</span></li>').join('');

  // scene
  const host=$('gl');
  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(55,innerWidth/innerHeight,1,8000);
  const renderer=new THREE.WebGLRenderer({canvas:host,antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(2,devicePixelRatio));renderer.setSize(innerWidth,innerHeight);

  const base=nodes.map(n=>new THREE.Vector3(n.x||0,n.y||0,n.z||0));
  const geo=new THREE.SphereGeometry(1,10,10);
  const mesh=new THREE.InstancedMesh(geo,new THREE.MeshBasicMaterial(),nodes.length);
  const d3=new THREE.Object3D();
  const baseCol=nodes.map(n=>col[n.source]);
  let spread=1;
  function sizeOf(i){return 2.2+Math.sqrt(nodes[i].size||1)*1.4;}
  function placeNode(i){const p=base[i];const hid=hidden[nodes[i].source];d3.position.set(p.x*spread,p.y*spread,p.z*spread);d3.scale.setScalar(hid?0.0001:sizeOf(i));d3.updateMatrix();mesh.setMatrixAt(i,d3.matrix);}
  for(let i=0;i<nodes.length;i++){placeNode(i);mesh.setColorAt(i,baseCol[i]);}
  mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor.needsUpdate=true;scene.add(mesh);

  // links
  const idx={};nodes.forEach((n,i)=>idx[n.id]=i);
  const lpos=new Float32Array(links.length*6),lcol=new Float32Array(links.length*6);
  function buildLinks(){for(let i=0;i<links.length;i++){const a=byId[links[i].source],b=byId[links[i].target];
    const ia=idx[links[i].source],ib=idx[links[i].target];
    const hid=ia==null||ib==null||hidden[a.source]||hidden[b.source];
    if(hid){lpos.set([0,0,0,0,0,0],i*6);}else{lpos.set([base[ia].x*spread,base[ia].y*spread,base[ia].z*spread,base[ib].x*spread,base[ib].y*spread,base[ib].z*spread],i*6);}
    const al=(0.12+0.5*(links[i].similarity||0))*glowK;lcol.set([0.35*al,0.6*al,0.86*al,0.35*al,0.6*al,0.86*al],i*6);}
    lgeo.attributes.position.needsUpdate=true;lgeo.attributes.color.needsUpdate=true;}
  let glowK=0.8;
  const lgeo=new THREE.BufferGeometry();
  lgeo.setAttribute('position',new THREE.BufferAttribute(lpos,3));
  lgeo.setAttribute('color',new THREE.BufferAttribute(lcol,3));
  const lines=new THREE.LineSegments(lgeo,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:.9}));
  scene.add(lines);buildLinks();

  // camera orbit
  let theta=0.6,phi=1.15,radius=1350,auto=true;
  function place(){cam.position.set(radius*Math.sin(phi)*Math.sin(theta),radius*Math.cos(phi),radius*Math.sin(phi)*Math.cos(theta));cam.lookAt(0,0,0);}
  place();
  let drag=false,moved=false,px=0,py=0;
  host.addEventListener('pointerdown',e=>{drag=true;moved=false;px=e.clientX;py=e.clientY;});
  addEventListener('pointerup',e=>{if(drag&&!moved)pick(e);drag=false;});
  addEventListener('pointermove',e=>{if(drag){if(Math.abs(e.clientX-px)+Math.abs(e.clientY-py)>3){moved=true;auto=false;}theta-=(e.clientX-px)*0.005;phi=Math.max(0.2,Math.min(2.94,phi-(e.clientY-py)*0.005));px=e.clientX;py=e.clientY;place();}else hover(e);});
  host.addEventListener('wheel',e=>{radius=Math.max(300,Math.min(4200,radius+e.deltaY*1.3));place();e.preventDefault();},{passive:false});
  addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});

  // picking
  const ray=new THREE.Raycaster();const ndc=new THREE.Vector2();
  function hit(e){ndc.x=(e.clientX/innerWidth)*2-1;ndc.y=-(e.clientY/innerHeight)*2+1;ray.setFromCamera(ndc,cam);const r=ray.intersectObject(mesh);for(const x of r){if(x.instanceId!=null&&!hidden[nodes[x.instanceId].source])return x.instanceId;}return -1;}
  const tip=$('tip');
  function hover(e){const i=hit(e);if(i<0){tip.style.opacity=0;host.style.cursor='grab';return;}const n=nodes[i];tip.innerHTML=n.label+' · <span style="color:#8793b5">'+shortP(n.source)+'</span>';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-10)+'px';tip.style.opacity=1;host.style.cursor='pointer';}
  function pick(e){const i=hit(e);if(i<0){clearSel();return;}select(i);}

  let selId=null;
  function select(i){const n=nodes[i];selId=n.id;
    const near={};near[n.id]=true;links.forEach(l=>{if(l.source===n.id)near[l.target]=true;if(l.target===n.id)near[l.source]=true;});
    for(let k=0;k<nodes.length;k++){const c=near[nodes[k].id]?baseCol[k]:new THREE.Color(0x222a40);mesh.setColorAt(k,c);}mesh.instanceColor.needsUpdate=true;
    const mine=links.filter(l=>l.source===n.id||l.target===n.id).sort((a,b)=>(b.similarity||0)-(a.similarity||0));
    const rows=mine.slice(0,12).map(l=>{const o=byId[l.source===n.id?l.target:l.source];return '<li><div class="to">'+(o?o.label:'?')+'</div><div class="why">'+(l.reason||'')+'</div></li>';}).join('');
    $('inspect').innerHTML='<p class="file">'+n.label+'</p><span class="chip"><span class="dot" style="color:#fff;background:hsl('+Math.round(srcs.indexOf(n.source)/srcs.length*360)+',68%,62%)"></span>'+shortP(n.source)+' · '+(n.folder||'root')+'</span><div style="font:500 11px var(--mono);color:var(--dim);margin-bottom:6px">'+n.size+' chunks · '+mine.length+' links</div><ul>'+rows+'</ul>';
    // focus camera
    const p=base[i];radius=320;theta=Math.atan2(p.x,p.z);phi=1.1;auto=false;place();}
  function clearSel(){selId=null;for(let k=0;k<nodes.length;k++)mesh.setColorAt(k,baseCol[k]);mesh.instanceColor.needsUpdate=true;$('inspect').textContent='Click a star to focus it — that note and its links light up, and you can read why they connect.';}

  $('hubs').addEventListener('click',e=>{const li=e.target.closest('li');if(!li)return;const i=idx[li.dataset.id];if(i!=null)select(i);});
  $('filter').addEventListener('click',e=>{const li=e.target.closest('li');if(!li)return;const s=li.dataset.src;hidden[s]=!hidden[s];li.classList.toggle('off',!!hidden[s]);for(let i=0;i<nodes.length;i++)placeNode(i);mesh.instanceMatrix.needsUpdate=true;buildLinks();});
  $('search').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();if(!q){clearSel();return;}let first=-1;for(let k=0;k<nodes.length;k++){const m=(nodes[k].label+' '+nodes[k].source).toLowerCase().includes(q);mesh.setColorAt(k,m?baseCol[k]:new THREE.Color(0x222a40));if(m&&first<0)first=k;}mesh.instanceColor.needsUpdate=true;if(first>=0&&q.length>2){const p=base[first];radius=420;theta=Math.atan2(p.x,p.z);auto=false;place();}});

  $('spread').addEventListener('input',e=>{spread=(+e.target.value)/100;$('spread-v').textContent=e.target.value+'%';for(let i=0;i<nodes.length;i++)placeNode(i);mesh.instanceMatrix.needsUpdate=true;buildLinks();});
  $('glow').addEventListener('input',e=>{glowK=(+e.target.value)/100;$('glow-v').textContent=e.target.value;buildLinks();});
  $('spread-v').textContent='100%';$('glow-v').textContent='80';
  $('t-rotate').addEventListener('click',function(){auto=this.getAttribute('aria-pressed')!=='true';this.setAttribute('aria-pressed',String(auto));});
  $('fit').onclick=()=>{radius=1350;theta=0.6;phi=1.15;auto=true;place();clearSel();$('search').value='';};

  (function loop(){requestAnimationFrame(loop);if(auto){theta+=0.0011;place();}renderer.render(scene,cam);})();
  window.__brainReady=true;
}
</script>
</body></html>
"""
