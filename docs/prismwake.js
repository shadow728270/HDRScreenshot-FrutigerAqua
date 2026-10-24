/* Prismwake website interactions. Event-driven, no perpetual canvas redraw or scroll polling. */
(()=>{"use strict";
 const $=id=>document.getElementById(id);
 const repo="shadow728270/HDRScreenshot-FrutigerAqua";
 const compare=$("compare"),range=$("compareRange"),left=$("compareLeft"),right=$("compareRight");
 const lblLeft=$("compareLabelLeft"),lblRight=$("compareLabelRight"),fileA=$("realConventional"),fileB=$("realPrismwake"),feedback=$("compareFeedback");
 let urlA=null,urlB=null,hasA=false,hasB=false;
 function positionSplit(percent){const val=Math.max(0,Math.min(100,percent));compare.style.setProperty("--split",val+"%");range.value=String(Math.round(val));range.setAttribute("aria-valuenow",String(Math.round(val)))}
 positionSplit(50);
 range.addEventListener("input",()=>positionSplit(+range.value));
 function importFile(input,image,side){
   const file=input.files?.[0];if(!file)return;
   if(!file.type.startsWith("image/")||file.size>25*1024*1024){feedback.textContent="Choose a PNG, JPEG or WebP image under 25 MB.";input.value="";return}
   const url=URL.createObjectURL(file);image.onload=()=>{if(side==="A"&&urlA)URL.revokeObjectURL(urlA);if(side==="B"&&urlB)URL.revokeObjectURL(urlB);if(side==="A"){urlA=url;hasA=true}else{urlB=url;hasB=true}
     if(hasA&&hasB){compare.dataset.real="true";lblLeft.textContent="Your conventional capture";lblRight.textContent="Your Prismwake capture";feedback.textContent="Comparing your two real files locally. Nothing was uploaded."}
     else{feedback.textContent="One image added. Choose the second file for an actual side-by-side comparison."}
   };
   image.onerror=()=>{URL.revokeObjectURL(url);feedback.textContent="Could not open that image."};
   image.src=url;
 }
 fileA.addEventListener("change",()=>importFile(fileA,left,"A"));
 fileB.addEventListener("change",()=>importFile(fileB,right,"B"));
 $("compareReset").addEventListener("click",()=>{
   if(urlA)URL.revokeObjectURL(urlA);if(urlB)URL.revokeObjectURL(urlB);
   urlA=urlB=null;hasA=hasB=false;fileA.value="";fileB.value="";
   left.src=right.src="assets/hdrsnip-capture-overlay.webp";compare.dataset.real="false";
   lblLeft.textContent="Simulated blown-out capture";lblRight.textContent="Original Prismwake-era capture";
   feedback.textContent="Illustrative simulation shown. Upload both genuine files to compare actual outputs.";positionSplit(50);
 });
 let draggingSplit=false;
 compare.addEventListener("pointerdown",event=>{if(event.button!==0&&event.pointerType==="mouse")return;event.preventDefault();draggingSplit=true;compare.setPointerCapture(event.pointerId);setSplitFromPointer(event)});
 compare.addEventListener("dragstart",event=>event.preventDefault());
 compare.addEventListener("pointermove",event=>{if(draggingSplit)setSplitFromPointer(event)});
 function setSplitFromPointer(e){const rect=compare.getBoundingClientRect();positionSplit((e.clientX-rect.left)/rect.width*100)}
 ["pointerup","pointercancel","lostpointercapture"].forEach(t=>compare.addEventListener(t,()=>draggingSplit=false));
 compare.addEventListener("keydown",event=>{if(event.key==="ArrowLeft"||event.key==="ArrowRight"){event.preventDefault();positionSplit(+range.value+(event.key==="ArrowLeft"?-3:3))}});

 const stage=$("demoStage"),svg=$("demoSvg"),hint=$("demoHint"),tools=[...document.querySelectorAll("[data-tool]")],undo=$("demoUndo"),reset=$("demoReset");
 const NS="http://www.w3.org/2000/svg";let currentTool="select",isDrawing=false,start=null,temp=null,history=[];
 function coord(e){const r=stage.getBoundingClientRect();return{x:Math.max(0,Math.min(1000,(e.clientX-r.left)/r.width*1000)),y:Math.max(0,Math.min(615,(e.clientY-r.top)/r.height*615))}}
 function make(tag,props){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(props))el.setAttribute(k,String(v));return el}
 const selection=make("rect",{x:155,y:112,width:670,height:372,rx:10,fill:"#baffff","fill-opacity":".07",stroke:"#aefff6","stroke-width":"4","stroke-dasharray":"15 8"});
 svg.appendChild(selection);
 function selectTool(t){currentTool=t;tools.forEach(el=>el.setAttribute("aria-pressed",String(el.dataset.tool===t)));hint.textContent=({
  select:"Drag to choose a capture region",pen:"Drag to draw a line",rect:"Drag to draw a rectangle",
  arrow:"Drag to draw an arrow",fill:"Tap a point to add a translucent fill",text:"Tap to add a label"
 })[t]}
 tools.forEach(btn=>btn.addEventListener("click",()=>selectTool(btn.dataset.tool)));
 function keep(el){history.push(el);undo.disabled=false}
 function outline(color="#5affd7"){return{fill:"none",stroke:color,"stroke-width":5,"stroke-linecap":"round","stroke-linejoin":"round"}}
 function redrawShape(el,a,b,t){const dx=b.x-a.x,dy=b.y-a.y;
   if(t==="select"||t==="rect"){el.setAttribute("x",Math.min(a.x,b.x));el.setAttribute("y",Math.min(a.y,b.y));el.setAttribute("width",Math.abs(dx));el.setAttribute("height",Math.abs(dy))}
   if(t==="arrow"){el.setAttribute("x1",a.x);el.setAttribute("y1",a.y);el.setAttribute("x2",b.x);el.setAttribute("y2",b.y)}
 }
 stage.addEventListener("pointerdown",e=>{
   if(e.pointerType==="mouse"&&e.button!==0)return;
   e.preventDefault();isDrawing=true;start=coord(e);stage.setPointerCapture(e.pointerId);
   const p=start;
   if(currentTool==="select"){temp=selection;redrawShape(selection,p,p,"select");return}
   if(currentTool==="pen"){temp=make("polyline",{...outline(),"points":p.x+","+p.y});svg.appendChild(temp);return}
   if(currentTool==="rect"){temp=make("rect",{...outline(),x:p.x,y:p.y,width:1,height:1,rx:4});svg.appendChild(temp);return}
   if(currentTool==="arrow"){if(!$("demoArrowHead")){const defs=make("defs",{});const marker=make("marker",{id:"demoArrowHead",markerWidth:10,markerHeight:10,refX:8,refY:3,orient:"auto",markerUnits:"strokeWidth"});marker.appendChild(make("path",{d:"M0,0 L0,6 L9,3 z",fill:"#5affd7"}));defs.appendChild(marker);svg.appendChild(defs)}
     temp=make("line",{...outline(),x1:p.x,y1:p.y,x2:p.x,y2:p.y,"marker-end":"url(#demoArrowHead)"});svg.appendChild(temp);return}
   if(currentTool==="fill"){const circle=make("ellipse",{cx:p.x,cy:p.y,rx:115,ry:75,fill:"#67ffe0","fill-opacity":".27",stroke:"#abfff0","stroke-width":3});svg.appendChild(circle);keep(circle);temp=null;return}
   if(currentTool==="text"){const el=make("text",{x:p.x,y:p.y,fill:"#fbfff7","font-size":33,"font-weight":800,stroke:"#04476d","stroke-width":1,"paint-order":"stroke"});el.textContent="LOOK HERE ↗";svg.appendChild(el);keep(el);temp=null}
 });
 stage.addEventListener("pointermove",e=>{if(!isDrawing||!temp)return;const p=coord(e);
   if(currentTool==="pen"){const s=temp.getAttribute("points")||"";temp.setAttribute("points",s+" "+p.x.toFixed(1)+","+p.y.toFixed(1))}
   else redrawShape(temp,start,p,currentTool)
 });
 function finish(e){if(!isDrawing)return;isDrawing=false;if(temp&&currentTool!=="select"){keep(temp)}temp=null}
 stage.addEventListener("pointerup",finish);stage.addEventListener("pointercancel",finish);
 undo.addEventListener("click",()=>{const x=history.pop();if(x)x.remove();undo.disabled=history.length===0});
 reset.addEventListener("click",()=>{history.forEach(x=>x.remove());history=[];undo.disabled=true;selection.setAttribute("x","155");selection.setAttribute("y","112");selection.setAttribute("width","670");selection.setAttribute("height","372");selectTool("select")});
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
       addRow(row.tag_name+" · "+(row.tag_name==="v0.1.2"?"Stroke & Paint Bucket":"Published release"),row.name||"Official stable build","Shipped",row.html_url,date)}
     releaseState.textContent="Fetched from GitHub · "+new Date().toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"});didLoad=true;
   }catch(e){releases.replaceChildren();addRow("v0.1.2 · Stroke & Paint Bucket","Verified stable release","Shipped",repoLink+"/tag/v0.1.2","Oct 24, 2026");
     addRow("v0.1.1 · Saving & updater","Official stable release","Shipped",repoLink+"/tag/v0.1.1","");
     releaseState.textContent="Live GitHub data unavailable; showing verified release information."}
   finally{refresh.disabled=false}
 }
 refresh.addEventListener("click",loadReleases);
 if("IntersectionObserver" in window){const obs=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&!didLoad){obs.disconnect();loadReleases()}},{rootMargin:"180px"});obs.observe(releases)}else loadReleases();
})();
