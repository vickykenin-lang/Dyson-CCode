const assert=require('node:assert/strict');
  // Band-limited resampling: avoid folding high-frequency microphone noise into speech.
  function to16k(x,rate){
    if(!Number.isFinite(rate)||rate<=0)throw new Error('Invalid microphone sample rate');
    if(rate===16000)return x;
    const out=new Float32Array(Math.floor(x.length*16000/rate));
    const radius=32,cutoff=0.45*Math.min(1,16000/rate),kernels=new Map();
    for(let i=0;i<out.length;i++){
      const pos=i*rate/16000,center=Math.floor(pos),phase=Math.round((pos-center)*256);
      let weights=kernels.get(phase);
      if(!weights){weights=new Float64Array(radius*2+1);
        const frac=phase/256;
        for(let j=-radius;j<=radius;j++){const d=j-frac;
          if(Math.abs(d)>radius)continue;
          const sinc=Math.abs(d)<1e-12?2*cutoff:Math.sin(2*Math.PI*cutoff*d)/(Math.PI*d);
          const window=0.42+0.5*Math.cos(Math.PI*d/radius)+0.08*Math.cos(2*Math.PI*d/radius);
          weights[j+radius]=sinc*window;
        }
        kernels.set(phase,weights);
      }
      let sum=0,norm=0;
      for(let j=-radius;j<=radius;j++){const index=center+j;
        if(index<0||index>=x.length)continue;
        const w=weights[j+radius];sum+=x[index]*w;norm+=w;
      }
      out[i]=Math.abs(norm)>1e-12?sum/norm:0;
    }
    return out;
  }
  // Idle time is not utterance time. Retain only a short leading buffer while waiting.
  function voiceCapture(rate){
    return {rate,started:false,lead:[],leadMs:0,parts:[],speechMs:0,voicedMs:0,silenceMs:0};
  }
  function voiceFrame(cap,pcm,rms){
    const ms=pcm.length/cap.rate*1000,active=rms>0.025;
    if(!cap.started){
      cap.lead.push(pcm);cap.leadMs+=ms;
      while(cap.lead.length>1&&cap.leadMs>500){
        cap.leadMs-=cap.lead.shift().length/cap.rate*1000;
      }
      if(!active)return false;
      cap.started=true;cap.parts=cap.lead;cap.lead=[];
    }else cap.parts.push(pcm);
    cap.speechMs+=ms;
    if(active){cap.voicedMs+=ms;cap.silenceMs=0;}else cap.silenceMs+=ms;
    // Leave headroom for leading audio and trailing silence under the server's 30s limit.
    return (cap.voicedMs>=350&&cap.silenceMs>=1500)||cap.speechMs>=24000;
  }

let passed=0;
function test(name,fn){fn();passed++;console.log('PASS '+name);}
const tone=(rate,hz,seconds=0.25)=>Float32Array.from({length:Math.floor(rate*seconds)},(_,i)=>Math.sin(2*Math.PI*hz*i/rate));
const rms=x=>Math.sqrt(x.reduce((s,v)=>s+v*v,0)/x.length);
test('16k audio is preserved',()=>{const x=tone(16000,1000);assert.equal(to16k(x,16000),x);});
test('48k and 44.1k lengths and DC amplitude',()=>{for(const rate of [48000,44100]){
 const out=to16k(new Float32Array(rate/10).fill(.25),rate);assert.equal(out.length,1600);
 assert.ok(out.every(v=>Math.abs(v-.25)<1e-6));}});
test('speech-band tone survives resampling',()=>{for(const rate of [48000,44100]){
 const x=to16k(tone(rate,1000),rate);assert.ok(rms(x.slice(100,-100))>.65);}});
test('above-Nyquist tone does not alias into speech band',()=>{for(const rate of [48000,44100]){
 const x=to16k(tone(rate,12000),rate);assert.ok(rms(x.slice(100,-100))<.02);}});
test('invalid sample rate is rejected',()=>assert.throws(()=>to16k(new Float32Array(5),0)));
const frame=(cap,level,ms=100)=>voiceFrame(cap,new Float32Array(cap.rate*ms/1000).fill(level),level);
test('60 seconds waiting does not end first spoken word',()=>{
 const c=voiceCapture(16000);for(let i=0;i<600;i++)assert.equal(frame(c,0),false);
 assert.ok(c.leadMs<=500);assert.equal(c.parts.length,0);
 for(let i=0;i<10;i++)assert.equal(frame(c,.1),false);
 assert.equal(c.speechMs,1000);
});
test('turn ends on trailing silence after enough speech',()=>{
 const c=voiceCapture(16000);for(let i=0;i<5;i++)assert.equal(frame(c,.1),false);
 for(let i=0;i<14;i++)assert.equal(frame(c,0),false);
 assert.equal(frame(c,0),true);
});
test('long utterance is capped below backend audio limit',()=>{
 const c=voiceCapture(48000);let ended=false;
 for(let i=0;i<260&&!ended;i++)ended=frame(c,.1);
 assert.equal(ended,true);assert.ok(c.parts.reduce((n,p)=>n+p.length,0)/c.rate<30);
});
console.log(passed+' tests passed');
