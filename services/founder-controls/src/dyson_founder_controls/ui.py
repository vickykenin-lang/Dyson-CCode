"""The Founder's page on Direct Founder Controls. Every action asks the phone's passkey for a
confirmation of exactly that action; nothing here works without it. Purposes are built exactly as
in `app.py` (`purpose_for_*`)."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dyson Controls</title>
<style>
:root{--bg:#0f1220;--card:#1a1d30;--fg:#f2f3f7;--muted:#a6abc2;--acc:#f2b84b;--red:#e5484d;
--green:#3fb37f;--line:#2b2f48}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);font-weight:700;color:var(--acc);
letter-spacing:.08em}
main{max-width:640px;margin:0 auto;padding:16px}
section{background:var(--card);border-radius:10px;padding:16px;margin:0 0 16px}
h2{margin:0 0 8px;font-size:1.15rem}p{margin:6px 0;color:var(--muted)}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:12px 16px;margin:6px 6px 0 0;
cursor:pointer;background:var(--acc);color:#141414;min-height:44px}
button.red{background:var(--red);color:#fff}button.green{background:var(--green);color:#fff}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
input{font:inherit;width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);
background:#0b0d18;color:var(--fg);margin:6px 0}
.item{border-top:1px solid var(--line);padding:12px 0}.item:first-child{border-top:0}
.small{font-size:.85rem;color:var(--muted);word-break:break-all}
#status{min-height:1.5em;color:var(--acc)}.hidden{display:none}
</style></head><body>
<header>DYSON · DIRECT FOUNDER CONTROLS</header>
<main>
<p id="status" role="status" aria-live="polite"></p>

<section id="enroll" class="hidden">
<h2>Register your passkey</h2>
<p>Paste the device key from AWS Parameter Store (<b>/dyson/founder_device_key</b>) once.
Your phone then creates a passkey; after that the device key is no longer accepted.</p>
<input id="devkey" type="password" autocomplete="off" placeholder="Device key">
<input id="label1" value="Founder phone" aria-label="Passkey name">
<button onclick="enrollFirst()">Register passkey</button>
</section>

<section id="controls" class="hidden">
<h2>STOP and PAUSE</h2>
<p>STOP blocks every new tool call at once. Resuming always needs your approval.</p>
<button class="red" onclick="control('stop')">STOP everything</button>
<button class="ghost" onclick="control('pause')">PAUSE everything</button>
<button class="ghost" onclick="resumeRequest()">Ask to resume</button>
</section>

<section id="approvals" class="hidden">
<h2>Waiting for you</h2>
<button onclick="loadApprovals()">Show pending approvals</button>
<div id="list"></div>
</section>

<section id="backup" class="hidden">
<h2>Backup passkey</h2>
<p>Add a second passkey (another phone or a security key) in case this one is lost.</p>
<input id="label2" value="Backup passkey" aria-label="Backup passkey name">
<button class="ghost" onclick="enrollMore()">Add backup passkey</button>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
const say=t=>{$("status").textContent=t};
const b64u={
 dec:s=>{s=s.replace(/-/g,"+").replace(/_/g,"/");while(s.length%4)s+="=";
  return Uint8Array.from(atob(s),c=>c.charCodeAt(0)).buffer},
 enc:b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\\+/g,"-")
  .replace(/\\//g,"_").replace(/=+$/,"")};
async function post(path,body,headers){
 const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json",...headers},
  body:JSON.stringify(body)});
 const j=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(j.detail||("refused ("+r.status+")"));return j}
async function confirmWithPasskey(purpose){
 const c=await post("/passkeys/challenges",{purpose});
 const o=JSON.parse(c.options);
 o.challenge=b64u.dec(o.challenge);
 (o.allowCredentials||[]).forEach(x=>x.id=b64u.dec(x.id));
 const cred=await navigator.credentials.get({publicKey:o});
 const r=cred.response;
 const assertion=JSON.stringify({id:cred.id,rawId:b64u.enc(cred.rawId),type:cred.type,
  response:{clientDataJSON:b64u.enc(r.clientDataJSON),authenticatorData:b64u.enc(r.authenticatorData),
  signature:b64u.enc(r.signature),userHandle:r.userHandle?b64u.enc(r.userHandle):null},
  clientExtensionResults:{}});
 return {challenge_id:c.challenge_id,assertion}}
async function createPasskey(opts){
 const o=JSON.parse(opts.options);
 o.challenge=b64u.dec(o.challenge);o.user.id=b64u.dec(o.user.id);
 (o.excludeCredentials||[]).forEach(x=>x.id=b64u.dec(x.id));
 const cred=await navigator.credentials.create({publicKey:o});
 const r=cred.response;
 const credential=JSON.stringify({id:cred.id,rawId:b64u.enc(cred.rawId),type:cred.type,
  response:{clientDataJSON:b64u.enc(r.clientDataJSON),attestationObject:b64u.enc(r.attestationObject),
  transports:r.getTransports?r.getTransports():[]},clientExtensionResults:{}});
 return post("/passkeys/register",{registration_id:opts.registration_id,credential})}
async function run(label,fn){
 try{say(label+"…");say(await fn())}catch(e){say("Not done: "+e.message)}}
function enrollFirst(){run("Registering",async()=>{
 const opts=await post("/passkeys/registration-options",
  {label:$("label1").value,device_key:$("devkey").value.trim()});
 $("devkey").value="";const r=await createPasskey(opts);await refresh();
 return "Passkey registered ("+r.label+"). The device key no longer works."})}
function enrollMore(){run("Adding backup passkey",async()=>{
 const label=$("label2").value;const c=await confirmWithPasskey("add-passkey|"+label);
 const r=await createPasskey(await post("/passkeys/registration-options",{label,...c}));
 return "Backup passkey added ("+r.label+"). Passkeys: "+r.enrolled})}
function control(cmd){
 if(!confirm(cmd.toUpperCase()+" everything now?"))return;
 run(cmd.toUpperCase(),async()=>{const c=await confirmWithPasskey("control|"+cmd+"|master|-");
 const s=await post("/control",
  {command:cmd,scope:"master",receptor_id:null,reason:"Founder page",...c});
 return cmd.toUpperCase()+" done. State now: "+s.mode})}
function resumeRequest(){run("Asking to resume",async()=>{
 const c=await confirmWithPasskey("resume-request|master|-");
 const a=await post("/resume-requests",{scope:"master",receptor_id:null,...c});
 return "Resume request created; approve it below to resume. ("+a.approval_id+")"})}
function loadApprovals(){run("Loading",async()=>{
 const c=await confirmWithPasskey("list-approvals");
 const r=await fetch("/approvals",
  {headers:{"X-Challenge":c.challenge_id,"X-Assertion":c.assertion}});
 const list=await r.json();if(!r.ok)throw new Error(list.detail||r.status);
 $("list").innerHTML="";
 list.forEach(a=>{const d=document.createElement("div");d.className="item";
  d.innerHTML="<b></b><p class=small></p><p class=small></p>";
  d.querySelector("b").textContent=a.action_summary;
  d.querySelectorAll("p")[0].textContent=
   a.category+" · requested by "+a.requested_by+" · "+a.created_at;
  d.querySelectorAll("p")[1].textContent="Action digest: "+a.action_digest;
  for(const k of ["approve","reject"]){const b=document.createElement("button");
   b.textContent=k==="approve"?"Approve":"Reject";b.className=k==="approve"?"green":"red";
   b.onclick=()=>decide(a,k);d.appendChild(b)}
  $("list").appendChild(d)});
 return list.length?list.length+" waiting":"Nothing is waiting."})}
function decide(a,k){run(k==="approve"?"Approving":"Rejecting",async()=>{
 const c=await confirmWithPasskey("decide|"+a.approval_id+"|"+a.action_digest+"|"+k);
 const r=await post("/decisions",
  {approval_id:a.approval_id,action_digest:a.action_digest,decision:k,...c});
 return "Decision recorded: "+r.status})}
async function refresh(){const n=(await (await fetch("/passkeys")).json()).enrolled;
 $("enroll").classList.toggle("hidden",n>0);
 for(const id of ["controls","approvals","backup"])$(id).classList.toggle("hidden",n===0);
 if(!window.PublicKeyCredential)say("This browser cannot use passkeys.")}
refresh();
</script></body></html>
"""
