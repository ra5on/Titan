'use strict';
(function(root,factory){const ui=factory();if(root)root.TitanFileLayout=ui;if(typeof module==='object'&&module.exports)module.exports=ui;})(typeof window==='undefined'?null:window,function(){
 const defaults={side:'left',width:208,collapsed:false};
 const key=owner=>'titan-file-layout:'+encodeURIComponent(owner||'');
 const storage=()=>{try{return globalThis.localStorage;}catch{return null;}};
 function normalize(value={}){return {side:value.side==='right'?'right':'left',width:Math.min(360,Math.max(160,Number.isFinite(value.width)?Math.round(value.width):defaults.width)),collapsed:value.collapsed===true};}
 function load(owner,source=storage()){try{return normalize(JSON.parse(source?.getItem(key(owner))||'{}'));}catch{return {...defaults};}}
 function save(owner,value,target=storage()){const result=normalize(value);try{target?.setItem(key(owner),JSON.stringify(result));}catch{}return result;}
 function widthFor(width,available){return Math.min(normalize({width}).width,Math.max(160,Number(available||0)-320));}
 function mount(browser,ctx={}){
  if(!browser?.querySelector('[data-fb-splitter]'))return ()=>{};
  const doc=browser.ownerDocument,win=doc.defaultView,controller=new AbortController(),grip=browser.querySelector('[data-fb-splitter]');
  let prefs=load(ctx.owner),gesture=null,frame=null,alive=true;
  const listen=(node,type,handler)=>node?.addEventListener(type,handler,{signal:controller.signal});
  const apply=()=>{if(!alive)return;const width=widthFor(prefs.width,browser.clientWidth);browser.dataset.sidebarSide=prefs.side;browser.dataset.sidebarCollapsed=String(prefs.collapsed);browser.style.setProperty('--fb-sidebar-width',width+'px');grip.setAttribute('aria-valuenow',String(width));for(const button of browser.querySelectorAll('[data-fb-sidebar-side]'))button.setAttribute('aria-pressed',String(button.dataset.fbSidebarSide===prefs.side));for(const button of browser.querySelectorAll('[data-fb-sidebar-toggle]'))button.setAttribute('aria-expanded',String(!prefs.collapsed));};
  const persist=()=>{prefs=save(ctx.owner,prefs);};
  function finish(event){if(!gesture||event&&event.pointerId!==gesture.id)return;const id=gesture.id;gesture=null;try{grip.releasePointerCapture?.(id);}catch{}if(frame!==null){win.cancelAnimationFrame?.(frame);frame=null;}browser.classList.remove('fb-resizing');apply();persist();}
  listen(grip,'pointerdown',event=>{if(event.button!==0||win.matchMedia('(max-width:760px)').matches)return;event.preventDefault();gesture={id:event.pointerId,x:event.clientX,width:widthFor(prefs.width,browser.clientWidth),direction:prefs.side==='right'?-1:1};grip.setPointerCapture?.(event.pointerId);browser.classList.add('fb-resizing');});
  listen(grip,'pointermove',event=>{if(!gesture||event.pointerId!==gesture.id)return;prefs.width=normalize({width:gesture.width+(event.clientX-gesture.x)*gesture.direction}).width;if(frame===null&&win.requestAnimationFrame)frame=win.requestAnimationFrame(()=>{frame=null;apply();});else if(!win.requestAnimationFrame)apply();});
  listen(grip,'pointerup',finish);listen(grip,'pointercancel',finish);listen(grip,'lostpointercapture',()=>finish());
  listen(grip,'keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();prefs.width=event.key==='Home'?160:event.key==='End'?360:prefs.width+(event.key==='ArrowRight'?16:-16)*(prefs.side==='right'?-1:1);prefs=normalize(prefs);apply();persist();});
  listen(grip,'dblclick',()=>{prefs.width=defaults.width;apply();persist();});
  listen(browser,'click',event=>{const button=event.target.closest?.('[data-fb-sidebar-side],[data-fb-sidebar-toggle],[data-fb-places-close]');if(!button)return;if(button.dataset.fbSidebarSide){finish();prefs.side=button.dataset.fbSidebarSide;}else if(button.hasAttribute('data-fb-sidebar-toggle'))prefs.collapsed=!prefs.collapsed;else{browser.dataset.places='false';browser.querySelector('[data-fb-places]')?.setAttribute('aria-expanded','false');browser.querySelector('[data-fb-places]')?.focus();}apply();persist();});
  listen(doc,'keydown',event=>{if(event.key==='Escape'&&browser.dataset.places==='true'){browser.dataset.places='false';browser.querySelector('[data-fb-places]')?.setAttribute('aria-expanded','false');browser.querySelector('[data-fb-places]')?.focus();}});
  const observer=typeof win.ResizeObserver==='function'?new win.ResizeObserver(apply):null;observer?.observe(browser);apply();
  return ()=>{finish();alive=false;observer?.disconnect();controller.abort();};
 }
 return {normalize,load,save,widthFor,mount};
});
