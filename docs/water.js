/* HDRSnip Fusion: interactive Aqua lagoon. No dependencies, no tracking. */
(() => {
  'use strict';
  const canvas=document.getElementById('lagoon-canvas');
  if(!canvas)return;
  const shell=canvas.parentElement;
  const ctx=canvas.getContext('2d',{alpha:false});
  if(!ctx)return;
  const rainBtn=document.getElementById('lagoon-rain');
  const calmBtn=document.getElementById('lagoon-calm');
  const pauseBtn=document.getElementById('lagoon-pause');
  const status=document.getElementById('lagoon-status');
  const tip=document.getElementById('lagoon-tip');
  const mq=window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused=mq.matches, rain=!mq.matches, dragging=false, last=0, seconds=0, rainAt=0, frameId=0;
  let width=1,height=1,used=false;
  const rings=[];
  function resize(){
    const r=canvas.getBoundingClientRect();
    const deviceScale=Math.min(window.devicePixelRatio||1,window.innerWidth<700?1.0:1.5);
    const budget=window.innerWidth<700?280000:660000;
    const res=Math.min(deviceScale,Math.sqrt(budget/Math.max(1,r.width*r.height)));
    width=canvas.width=Math.max(1,Math.round(r.width*res));
    height=canvas.height=Math.max(1,Math.round(r.height*res));
    if(paused)paint();
  }
  function updateControls(){
    status.textContent=paused?'Water paused':rain?'Living water · raindrops enabled':'Calm water · touch to ripple';
    pauseBtn.textContent=paused?'▶ Resume water':'❚❚ Pause water';
    pauseBtn.setAttribute('aria-pressed',String(paused));
    rainBtn.textContent=rain?'☁ Rain: ON':'☼ Rain: OFF';
    rainBtn.classList.toggle('is-active',rain);
    rainBtn.setAttribute('aria-pressed',String(rain));
  }
  function paint(){
    if(!width||!height)return;
    const w=width,h=height,t=seconds;
    ctx.globalCompositeOperation='source-over';
    const water=ctx.createLinearGradient(0,0,w,h);
    water.addColorStop(0,'#d4fbff');
    water.addColorStop(.2,'#7fe4f0');
    water.addColorStop(.48,'#2bc6d9');
    water.addColorStop(.73,'#057bac');
    water.addColorStop(1,'#043b78');
    ctx.fillStyle=water;ctx.fillRect(0,0,w,h);
    const glow=ctx.createRadialGradient(w*.19,h*.06,0,w*.19,h*.06,w*.84);
    glow.addColorStop(0,'rgba(255,255,255,.31)');
    glow.addColorStop(1,'rgba(255,255,255,0)');
    ctx.fillStyle=glow;ctx.fillRect(0,0,w,h);
    ctx.globalCompositeOperation='screen';
    const offset=(x,y,i)=>Math.sin(x*.016+t*.75+i*.83)*9+Math.cos(x*.028-t*.36+i*1.71)*5+Math.sin(y*.020+t*.43)*7;
    // Dense, layered optical caustics: luminous curved currents with thin bright cores.
    for(let i=0;i<33;i++){
      let y=h*(i+.38)/33;
      ctx.beginPath();
      for(let x=-15;x<=w+15;x+=10){
        const yy=y+offset(x,y,i)*(.6+.4*i/33);
        if(x===-15)ctx.moveTo(x,yy);else ctx.lineTo(x,yy);
      }
      ctx.strokeStyle='rgba(234,255,255,.16)';
      ctx.lineWidth=3;ctx.stroke();
      ctx.strokeStyle='rgba(248,255,255,.30)';
      ctx.lineWidth=i%4===0?1.4:.65;ctx.stroke();
    }
    // Intersecting light ribbons create a refracted pool-floor lattice.
    for(let i=-20;i<42;i++){
      const base=i*26;
      ctx.beginPath();
      for(let y=-12;y<=h+12;y+=13){
        const x=base+y*.69+Math.sin(y*.027+t*.72+i*.72)*18+Math.sin(y*.052-t*.41)*7;
        if(y===-12)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.strokeStyle=i%4===0?'rgba(241,255,255,.25)':'rgba(231,255,255,.13)';
      ctx.lineWidth=i%4===0?1.9:.85;ctx.stroke();
    }
    // Dancing specular reflections around curved patchwork intersections.
    for(let i=0;i<24;i++){
      let px=w*((i*71%97)/97),py=h*((i*43%83)/83);
      const x=px+Math.sin(t*.2+i)*28,y=py+Math.cos(t*.24+i*.9)*17,r=14+5*(i%5);
      const g=ctx.createRadialGradient(x,y,0,x,y,r*2.4);
      g.addColorStop(0,'rgba(254,255,255,.27)');
      g.addColorStop(.13,'rgba(180,255,255,.1)');
      g.addColorStop(1,'rgba(255,255,255,0)');
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r*2.4,0,Math.PI*2);ctx.fill();
    }
    // Separate expanding wavefronts persist and collide visually.
    for(let i=rings.length-1;i>=0;i--){
      const ring=rings[i];
      if(ring.age>3.5){rings.splice(i,1);continue;}
      const fade=Math.pow(1-ring.age/3.5,1.35);
      for(let j=0;j<4;j++){
        const radius=(ring.age*62-j*20)*Math.min(w,h)/330;
        if(radius<=0)continue;
        ctx.beginPath();
        ctx.ellipse(ring.x*w,ring.y*h,radius*1.34,radius*.79,-.09,0,Math.PI*2);
        ctx.strokeStyle='rgba(252,255,255,'+Math.max(0,fade*(.50-j*.09))+')';
        ctx.lineWidth=Math.max(.8,3-j*.6);ctx.stroke();
      }
    }
    ctx.globalCompositeOperation='source-over';
  }
  function frame(t){
    frameId=0;
    if(paused||document.hidden)return;
    if(t-last<40){frameId=requestAnimationFrame(frame);return;}
    const dt=Math.min((t-last)/1000,.1);last=t;seconds+=dt;
    if(rain&&seconds-rainAt>1.1){
      rainAt=seconds;
      if(rings.length<22)rings.push({x:.05+Math.random()*.9,y:.06+Math.random()*.86,age:0});
    }
    for(const ring of rings)ring.age+=dt;
    paint();
    frameId=requestAnimationFrame(frame);
  }
  function refresh(){
    cancelAnimationFrame(frameId);frameId=0;
    updateControls();
    if(paused||document.hidden){paint();return;}
    last=0;frameId=requestAnimationFrame(frame);
  }
  function ripple(event){
    const r=canvas.getBoundingClientRect();
    const x=Math.max(0,Math.min(1,(event.clientX-r.left)/r.width));
    const y=Math.max(0,Math.min(1,(event.clientY-r.top)/r.height));
    if(rings.length<26)rings.push({x,y,age:0});
    if(!used){used=true;tip.classList.add('is-used');}
    if(paused){paused=false;refresh();}
  }
  shell.addEventListener('pointerdown',event=>{
    if(event.target!==canvas&&event.target!==shell)return;
    if(event.pointerType==='mouse'&&event.button!==0)return;
    dragging=true;
    if(shell.setPointerCapture)try{shell.setPointerCapture(event.pointerId);}catch(_){}
    ripple(event);
  });
  let dragAt=0;
  shell.addEventListener('pointermove',event=>{
    if(!dragging||event.timeStamp-dragAt<55)return;
    dragAt=event.timeStamp;ripple(event);
  },{passive:true});
  for(const e of ['pointerup','pointercancel','pointerleave'])shell.addEventListener(e,()=>{dragging=false;});
  rainBtn.addEventListener('click',()=>{rain=!rain;updateControls();});
  calmBtn.addEventListener('click',()=>{rings.length=0;rain=false;paint();updateControls();});
  pauseBtn.addEventListener('click',()=>{paused=!paused;refresh();});
  document.addEventListener('visibilitychange',refresh);
  if(typeof mq.addEventListener==='function')mq.addEventListener('change',()=>{
    if(mq.matches){paused=true;rain=false;refresh();}
  });
  if('ResizeObserver' in window){const observer=new ResizeObserver(resize);observer.observe(canvas);}
  else window.addEventListener('resize',resize,{passive:true});
  resize();refresh();
})();
