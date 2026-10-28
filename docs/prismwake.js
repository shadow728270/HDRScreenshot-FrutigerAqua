/* Prismwake website interactions. Event-driven, no perpetual canvas redraw or scroll polling. */
(()=>{"use strict";
 const $=id=>document.getElementById(id);
 const repo="shadow728270/HDRScreenshot-FrutigerAqua";
 const compare=$("compare"),range=$("compareRange");
 function positionSplit(percent){const val=Math.max(0,Math.min(100,percent));compare.style.setProperty("--split",val+"%");range.value=String(Math.round(val));range.setAttribute("aria-valuenow",String(Math.round(val)))}
 positionSplit(50);
 range.addEventListener("input",()=>positionSplit(+range.value));
 $("compareReset").addEventListener("click",()=>positionSplit(50));
 let draggingSplit=false;
 compare.addEventListener("pointerdown",event=>{if(event.button!==0&&event.pointerType==="mouse")return;event.preventDefault();draggingSplit=true;compare.setPointerCapture(event.pointerId);setSplitFromPointer(event)});
 compare.addEventListener("dragstart",event=>event.preventDefault());
 compare.addEventListener("pointermove",event=>{if(draggingSplit)setSplitFromPointer(event)});
 function setSplitFromPointer(e){const rect=compare.getBoundingClientRect();positionSplit((e.clientX-rect.left)/rect.width*100)}
 ["pointerup","pointercancel","lostpointercapture"].forEach(t=>compare.addEventListener(t,()=>draggingSplit=false));
 compare.addEventListener("keydown",event=>{if(event.key==="ArrowLeft"||event.key==="ArrowRight"){event.preventDefault();positionSplit(+range.value+(event.key==="ArrowLeft"?-3:3))}});

 const stage=$("demoStage"),svg=$("demoSvg"),hint=$("demoHint"),tools=[...document.querySelectorAll("[data-tool]")],undo=$("demoUndo"),reset=$("demoReset");
 const fillSettings=$("demoFillSettings"),fillColor=$("demoFillColor");
 const NS="http://www.w3.org/2000/svg";let currentTool="select",isDrawing=false,start=null,temp=null,history=[];
 function coord(e){const r=stage.getBoundingClientRect();return{x:Math.max(0,Math.min(1000,(e.clientX-r.left)/r.width*1000)),y:Math.max(0,Math.min(615,(e.clientY-r.top)/r.height*615))}}
 function make(tag,props){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(props))el.setAttribute(k,String(v));return el}
 const selection=make("rect",{x:155,y:112,width:670,height:372,rx:10,fill:"#baffff","fill-opacity":".07",stroke:"#aefff6","stroke-width":"4","stroke-dasharray":"15 8"});
 // The annotation layer is genuinely clipped to the capture selection.
 // Moving or resizing the selection updates the clipping rectangle immediately.
 const clipDefs=make("defs",{});
 const clipPath=make("clipPath",{id:"demoSelectionClip",clipPathUnits:"userSpaceOnUse"});
 const clipRect=make("rect",{x:155,y:112,width:670,height:372,rx:10});
 clipPath.appendChild(clipRect);clipDefs.appendChild(clipPath);svg.appendChild(clipDefs);
 const annotationLayer=make("g",{id:"demoAnnotationLayer","clip-path":"url(#demoSelectionClip)"});
 svg.appendChild(annotationLayer);
 svg.appendChild(selection);
 function selectionBounds(){return{x:+selection.getAttribute("x"),y:+selection.getAttribute("y"),width:+selection.getAttribute("width"),height:+selection.getAttribute("height")}}
 function withinSelection(p){const b=selectionBounds();return b.width>0&&b.height>0&&p.x>=b.x&&p.y>=b.y&&p.x<=b.x+b.width&&p.y<=b.y+b.height}
 function syncSelectionClip(){for(const attr of ["x","y","width","height"])clipRect.setAttribute(attr,selection.getAttribute(attr))}

 function selectTool(t){currentTool=t;tools.forEach(el=>el.setAttribute("aria-pressed",String(el.dataset.tool===t)));fillSettings.hidden=t!=="fill";hint.textContent=({
  select:"Drag to choose a capture region",pen:"Drag to draw a line",rect:"Drag to draw a rectangle",
  arrow:"Drag to draw an arrow",fill:"Click inside a closed shape to fill it. Background colors are ignored.",text:"Tap to add a label"
 })[t]}
 tools.forEach(btn=>btn.addEventListener("click",()=>selectTool(btn.dataset.tool)));
 function keep(el){history.push(el);undo.disabled=false}
 function outline(color="#5affd7"){return{fill:"none",stroke:color,"stroke-width":5,"stroke-linecap":"round","stroke-linejoin":"round"}}
 function redrawShape(el,a,b,t){const dx=b.x-a.x,dy=b.y-a.y;
   if(t==="select"||t==="rect"){el.setAttribute("x",Math.min(a.x,b.x));el.setAttribute("y",Math.min(a.y,b.y));el.setAttribute("width",Math.abs(dx));el.setAttribute("height",Math.abs(dy));if(t==="select")syncSelectionClip()}
   if(t==="arrow"){el.setAttribute("x1",a.x);el.setAttribute("y1",a.y);el.setAttribute("x2",b.x);el.setAttribute("y2",b.y)}
 }
 // The demo is an annotation-only paint bucket, NOT a photo color-replacement tool.
 // Background photo pixels must never enter the flood-fill calculation.
 // We rasterize drawn outline geometry into an opaque boundary mask on demand.
 const FILL_W=640,FILL_H=394,VIEW_W=1000,VIEW_H=615;

 function drawAnnotationBoundary(ctx,el){
   const tag=el.tagName.toLowerCase();
   if(tag==="image")return; // Earlier fills are colored overlays, not walls.
   ctx.save();ctx.lineWidth=7;ctx.lineCap="round";ctx.lineJoin="round";
   ctx.strokeStyle="#fff";ctx.fillStyle="#fff";
   if(tag==="rect"){
     const x=+el.getAttribute("x"),y=+el.getAttribute("y"),
           w=+el.getAttribute("width"),h=+el.getAttribute("height");
     if(w>0&&h>0){ctx.beginPath();ctx.rect(x,y,w,h);ctx.stroke()}
   }else if(tag==="polyline"){
     const pts=(el.getAttribute("points")||"").trim().split(/[,\s]+/).map(Number);
     if(pts.length>=2){ctx.beginPath();ctx.moveTo(pts[0],pts[1]);for(let i=2;i+1<pts.length;i+=2)ctx.lineTo(pts[i],pts[i+1]);ctx.stroke()}
   }else if(tag==="line"){
     const x1=+el.getAttribute("x1"),y1=+el.getAttribute("y1"),x2=+el.getAttribute("x2"),y2=+el.getAttribute("y2");
     ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();
     const theta=Math.atan2(y2-y1,x2-x1),length=19;
     ctx.beginPath();ctx.moveTo(x2,y2);
     ctx.lineTo(x2-length*Math.cos(theta-.43),y2-length*Math.sin(theta-.43));
     ctx.lineTo(x2-length*Math.cos(theta+.43),y2-length*Math.sin(theta+.43));
     ctx.closePath();ctx.fill();
   }else if(tag==="text"){
     ctx.font='800 33px "Segoe UI",sans-serif';ctx.textBaseline="alphabetic";
     ctx.fillText(el.textContent||"",+el.getAttribute("x"),+el.getAttribute("y"));
   }
   ctx.restore();
 }
 function drawingBoundaryMask(){
   const canvas=document.createElement("canvas");canvas.width=FILL_W;canvas.height=FILL_H;
   const ctx=canvas.getContext("2d",{willReadFrequently:true});if(!ctx)return null;
   const b=selectionBounds();
   ctx.scale(FILL_W/VIEW_W,FILL_H/VIEW_H);
   ctx.beginPath();ctx.rect(b.x,b.y,b.width,b.height);ctx.clip();
   for(const el of annotationLayer.children)drawAnnotationBoundary(ctx,el);
   return ctx.getImageData(0,0,FILL_W,FILL_H).data;
 }
 function floodFillAt(point){
   if(!withinSelection(point)){hint.textContent="Draw and fill shapes inside your selected region.";return}
   const barrier=drawingBoundaryMask();
   if(!barrier){hint.textContent="Can't initialize the fill tool.";return}
   const w=FILL_W,h=FILL_H,b=selectionBounds();
   const minX=Math.max(0,Math.floor(b.x/VIEW_W*w));
   const maxX=Math.min(w-1,Math.ceil((b.x+b.width)/VIEW_W*w)-1);
   const minY=Math.max(0,Math.floor(b.y/VIEW_H*h));
   const maxY=Math.min(h-1,Math.ceil((b.y+b.height)/VIEW_H*h)-1);
   const sx=Math.min(w-1,Math.max(0,Math.floor(point.x/VIEW_W*w)));
   const sy=Math.min(h-1,Math.max(0,Math.floor(point.y/VIEW_H*h)));
   const seed=sy*w+sx;
   if(sx<minX||sx>maxX||sy<minY||sy>maxY||barrier[seed*4+3]>30){
     hint.textContent="Click inside an enclosed drawing, not directly on its outline.";return;
   }
   const seen=new Uint8Array(w*h),stack=new Int32Array(w*h);
   const region=new Uint8Array(w*h);
   let top=0,filled=0,escaped=false;
   seen[seed]=1;stack[top++]=seed;
   // Connectivity depends exclusively on the drawn opaque barriers.
   // If the area reaches the selection border, it isn't a closed shape: do NOT paint it.
   while(top>0){
     const index=stack[--top],i=index*4,x=index%w,y=(index/w)|0;
     if(barrier[i+3]>30)continue;
     if(x<=minX||x>=maxX||y<=minY||y>=maxY){escaped=true;break}
     region[index]=1;filled++;
     let next;
     if(x>minX){next=index-1;if(!seen[next]){seen[next]=1;stack[top++]=next}}
     if(x<maxX){next=index+1;if(!seen[next]){seen[next]=1;stack[top++]=next}}
     if(y>minY){next=index-w;if(!seen[next]){seen[next]=1;stack[top++]=next}}
     if(y<maxY){next=index+w;if(!seen[next]){seen[next]=1;stack[top++]=next}}
   }
   if(escaped||!filled){
     hint.textContent="No enclosed drawing here. Draw a closed rectangle or loop first.";return;
   }
   const hex=fillColor.value,fr=parseInt(hex.slice(1,3),16),fg=parseInt(hex.slice(3,5),16),fb=parseInt(hex.slice(5,7),16);
   const overlay=document.createElement("canvas");overlay.width=w;overlay.height=h;
   const ctx=overlay.getContext("2d");if(!ctx)return;
   const data=ctx.createImageData(w,h);
   for(let i=0;i<w*h;i++){if(region[i]){const j=i*4;data.data[j]=fr;data.data[j+1]=fg;data.data[j+2]=fb;data.data[j+3]=174}}
   ctx.putImageData(data,0,0);
   const element=make("image",{x:0,y:0,width:VIEW_W,height:VIEW_H,preserveAspectRatio:"none"});
   element._fillCanvas=overlay;
   element.setAttribute("href",overlay.toDataURL("image/png"));
   // Keep the fill beneath all drawn outlines, while later fills can replace earlier ones.
   const firstOutline=[...annotationLayer.children].find(el=>el.tagName.toLowerCase()!=="image");
   annotationLayer.insertBefore(element,firstOutline||null);
   keep(element);
   hint.textContent="Filled enclosed drawing · "+filled.toLocaleString()+" pixels · ↶ to undo";
 }
 stage.addEventListener("pointerdown",e=>{
   if(e.pointerType==="mouse"&&e.button!==0)return;
   e.preventDefault();const p=coord(e);
   if(currentTool!=="select"&&!withinSelection(p)){hint.textContent="Choose a point inside the selection first.";return}
   isDrawing=true;start=p;stage.setPointerCapture(e.pointerId);
   if(currentTool==="select"){temp=selection;redrawShape(selection,p,p,"select");return}
   if(currentTool==="pen"){temp=make("polyline",{...outline(),"points":p.x+","+p.y});annotationLayer.appendChild(temp);return}
   if(currentTool==="rect"){temp=make("rect",{...outline(),x:p.x,y:p.y,width:1,height:1,rx:4});annotationLayer.appendChild(temp);return}
   if(currentTool==="arrow"){if(!$("demoArrowHead")){const defs=make("defs",{});const marker=make("marker",{id:"demoArrowHead",markerWidth:10,markerHeight:10,refX:8,refY:3,orient:"auto",markerUnits:"strokeWidth"});marker.appendChild(make("path",{d:"M0,0 L0,6 L9,3 z",fill:"#5affd7"}));defs.appendChild(marker);svg.appendChild(defs)}
     temp=make("line",{...outline(),x1:p.x,y1:p.y,x2:p.x,y2:p.y,"marker-end":"url(#demoArrowHead)"});annotationLayer.appendChild(temp);return}
   if(currentTool==="fill"){floodFillAt(p);temp=null;return}
   if(currentTool==="text"){const el=make("text",{x:p.x,y:p.y,fill:"#fbfff7","font-size":33,"font-weight":800,stroke:"#04476d","stroke-width":1,"paint-order":"stroke"});el.textContent="LOOK HERE ↗";annotationLayer.appendChild(el);keep(el);temp=null}
 });
 stage.addEventListener("pointermove",e=>{if(!isDrawing||!temp)return;const p=coord(e);
   if(currentTool==="pen"){const s=temp.getAttribute("points")||"";temp.setAttribute("points",s+" "+p.x.toFixed(1)+","+p.y.toFixed(1))}
   else redrawShape(temp,start,p,currentTool)
 });
 function finish(e){if(!isDrawing)return;isDrawing=false;if(temp&&currentTool!=="select"){keep(temp)}temp=null}
 stage.addEventListener("pointerup",finish);stage.addEventListener("pointercancel",finish);
 undo.addEventListener("click",()=>{const x=history.pop();if(x)x.remove();undo.disabled=history.length===0});
 reset.addEventListener("click",()=>{history.forEach(x=>x.remove());history=[];undo.disabled=true;selection.setAttribute("x","155");selection.setAttribute("y","112");selection.setAttribute("width","670");selection.setAttribute("height","372");syncSelectionClip();selectTool("select")});
 selectTool("select");

 const themes=[...document.querySelectorAll("[data-theme-choice]")],preview=$("themePreview"),opacity=$("themeOpacity"),opacityValue=$("opacityValue"),themeName=$("themeName");
 const names={ocean:"Ocean Current",emerald:"Emerald Glass",coral:"Sunset Coral",vista:"Vista Sapphire"};
 function applyTheme(name){preview.dataset.theme=name;themeName.textContent=names[name]||names.ocean;themes.forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.themeChoice===name)))}
 themes.forEach(b=>b.addEventListener("click",()=>applyTheme(b.dataset.themeChoice)));
 opacity.addEventListener("input",()=>{preview.style.setProperty("--glass-opacity",(+opacity.value/100).toFixed(2));opacityValue.textContent=opacity.value+"%"});
 applyTheme("ocean");

 const releases=$("releaseList"),releaseState=$("releaseState"),refresh=$("refreshReleases"),repoLink="https://github.com/"+repo+"/releases";
 let didLoad=false;
 function addRow(title,detail,tag,href,date){const el=document.createElement("div");el.className="roadmap-entry";const label=document.createElement("span");const strong=document.createElement("strong");strong.textContent=title;const small=document.createElement("small");small.textContent=detail;label.append(strong,small);const tail=document.createElement("span");tail.style.textAlign="right";const pill=document.createElement("span");pill.className="status";pill.textContent=tag;tail.appendChild(pill);if(date){const t=document.createElement("time");t.style.display="block";t.style.marginTop="4px";t.textContent=date;tail.appendChild(t)}el.append(label,tail);if(href){el.style.cursor="pointer";el.tabIndex=0;el.setAttribute("role","link");el.addEventListener("click",()=>window.open(href,"_blank","noopener,noreferrer"));el.addEventListener("keydown",e=>{if(e.key==="Enter")el.click()})}releases.appendChild(el)}
 async function loadReleases(){
   refresh.disabled=true;releaseState.textContent="Checking GitHub releases…";
   try{const ctrl=new AbortController();const timeout=setTimeout(()=>ctrl.abort(),7000);
     let response;try{response=await fetch("https://api.github.com/repos/"+repo+"/releases?per_page=3",{headers:{Accept:"application/vnd.github+json"},signal:ctrl.signal})}finally{clearTimeout(timeout)}
     if(!response.ok)throw Error("GitHub HTTP "+response.status);
     const rows=await response.json();if(!Array.isArray(rows)||!rows.length)throw Error("No releases returned");
     releases.replaceChildren();for(const row of rows){if(row.draft||row.prerelease)continue;const date=row.published_at?new Date(row.published_at).toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"}):"";
       addRow(row.tag_name+" · "+(row.tag_name==="v0.2.0"?"Pins, offline OCR & History":row.tag_name==="v0.1.4"?"Windows polish and reliability":row.tag_name==="v0.1.3"?"Prismwake editor upgrade":row.tag_name==="v0.1.2"?"Stroke & Paint Bucket":"Published release"),row.name||"Official stable build","Shipped",row.html_url,date)}
     releaseState.textContent="Fetched from GitHub · "+new Date().toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"});didLoad=true;
   }catch(e){releases.replaceChildren();addRow("v0.2.0 · Pins, OCR & History","Current official stable release","Shipped",repoLink+"/tag/v0.2.0","Oct 28, 2026");
     addRow("v0.1.4 · Windows settings and icon polish","Previous stable release","Shipped",repoLink+"/tag/v0.1.4","Oct 25, 2026");
     addRow("v0.1.3 · Prismwake editor upgrade","Previous stable release","Shipped",repoLink+"/tag/v0.1.3","Oct 24, 2026");
     addRow("v0.1.2 · Stroke & Paint Bucket","Previous stable release","Shipped",repoLink+"/tag/v0.1.2","Oct 24, 2026");
     addRow("v0.1.1 · Saving & updater","Official stable release","Shipped",repoLink+"/tag/v0.1.1","");
     releaseState.textContent="Live GitHub data unavailable; showing verified release information."}
   finally{refresh.disabled=false}
 }
 refresh.addEventListener("click",loadReleases);
 if("IntersectionObserver" in window){const obs=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!didLoad){obs.disconnect();loadReleases()}},{rootMargin:"180px"});obs.observe(releases)}else loadReleases();
})();
