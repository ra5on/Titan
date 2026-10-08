'use strict';
(function(root,factory){const ui=factory();if(root)root.TitanSidebarLayout=ui;if(typeof module==='object'&&module.exports)module.exports=ui;})(typeof window==='undefined'?null:window,function(){
 const layouts=[
  {selector:'.cp-layout',sidebar:'.cp-sidebar',id:'settings',label:'Einstellungen',width:240},
  {selector:'.storage-workspace',sidebar:'.storage-navigation',id:'storage',label:'Speicher',width:160},
  {selector:'.engine-workbench',sidebar:'.engine-navigation',id:'docker',label:'Docker',width:160},
  {selector:'.mv-manager[data-manager]',sidebar:'.mv-sidebar',id:'manager',label:'Navigation',width:160},
  {selector:'.um-body',sidebar:'.um-detail',id:'users-details',label:'Benutzerdetails',width:300,rightOnly:true},
 ];
 const defaults={width:160,min:128,max:360,content:320};
 const inspector={width:320,min:240,max:520,content:320};
 const key=(owner,id)=>'titan-sidebar-layout:'+encodeURIComponent(owner||'')+':'+encodeURIComponent(id);
 const storage=()=>{try{return globalThis.localStorage;}catch{return null;}};
 function normalize(value,options=defaults){const width=Number.isFinite(value)?value:options.width;return Math.min(options.max,Math.max(options.min,Math.round(width)));}
 function load(owner,id,options=defaults,source=storage()){try{return normalize(JSON.parse(source?.getItem(key(owner,id))||'null'),options);}catch{return options.width;}}
 function save(owner,id,width,options=defaults,target=storage()){const result=normalize(width,options);try{target?.setItem(key(owner,id),JSON.stringify(result));}catch{}return result;}
 function bounds(available,options=defaults,reserved=0){const max=Math.min(options.max,Math.max(0,Math.floor(Number(available)||0)-options.content-reserved));return {min:Math.min(options.min,max),max};}
 function widthFor(width,available,options=defaults,reserved=0){const range=bounds(available,options,reserved);return Math.min(range.max,Math.max(range.min,normalize(width,options)));}
 let active=null;
 function dispose(){active?.();active=null;}
 function mount(scope,ctx={}){
  dispose();if(!scope?.querySelectorAll)return ()=>{};
  const doc=scope.ownerDocument,win=doc.defaultView,records=new Map(),media=win.matchMedia('(max-width:760px)');let alive=true,pending=null;
  function mobile(){return media.matches;}
  function attach(element,layout){
   const sidebar=element.querySelector(layout.sidebar);if(!sidebar||element.closest('.fb-browser'))return;
   const id=layout.id==='manager'?'manager-'+element.dataset.manager:layout.id,controller=new AbortController(),grips=[];
   element.dataset.sidebarLayout=id;
   const record={element,sidebar,controller,grips,id,layout,observer:null};records.set(element,record);
   function gripFor(right=false){
    const options=right?{...inspector,width:layout.rightOnly?layout.width:inspector.width}:{...defaults,width:layout.width},prefId=right&&!layout.rightOnly?id+'-inspector':id,grip=doc.createElement('div');let pref=load(ctx.owner,prefId,options),gesture=null,frame=null;
    grip.className='titan-sidebar-resizer';grip.dataset.sidebarResize=right?'right':'left';grip.setAttribute('role','separator');grip.setAttribute('aria-orientation','vertical');grip.setAttribute('aria-label','Breite '+(right?'der '+(layout.rightOnly?layout.label:'Docker-Details'):'der Seitenleiste '+layout.label)+' ändern');grip.title='Ziehen oder Pfeiltasten: Breite ändern · Doppelklick: Standard';element.appendChild(grip);
    const listen=(node,type,fn)=>node.addEventListener(type,fn,{signal:controller.signal});
    const reserve=()=>layout.rightOnly?0:right?record.left?.width||layout.width:record.right?.enabled?inspector.min:0;
    const enabled=()=>!mobile()&&!(layout.id==='docker'&&element.clientWidth<=620)&&!element.classList.contains('has-vm-detail')&&(!right||layout.id!=='docker'||element.clientWidth>1050);
    const info={grip,width:0,enabled:false,apply,cleanup};grips.push(info);
    function apply(){
     if(!alive)return;info.enabled=enabled();if(!info.enabled&&gesture)finish(null,false);
     const range=bounds(element.clientWidth,options,reserve());info.width=widthFor(pref,element.clientWidth,options,reserve());
     element.style.setProperty(right?'--titan-inspector-width':'--titan-sidebar-width',info.width+'px');
     grip.tabIndex=info.enabled?0:-1;grip.setAttribute('aria-hidden',String(!info.enabled));grip.setAttribute('aria-valuemin',String(range.min));grip.setAttribute('aria-valuemax',String(range.max));grip.setAttribute('aria-valuenow',String(info.width));
    }
    function persist(){pref=save(ctx.owner,prefId,pref,options);}
    function finish(event,persistWidth=true){if(!gesture||event&&event.pointerId!==gesture.id)return;const id=gesture.id;gesture=null;try{grip.releasePointerCapture?.(id);}catch{}if(frame!==null){win.cancelAnimationFrame?.(frame);frame=null;}element.classList.remove('titan-sidebar-resizing');if(persistWidth)persist();refresh(record);}
    listen(grip,'pointerdown',event=>{if(event.button!==0||!enabled())return;event.preventDefault();gesture={id:event.pointerId,x:event.clientX,width:info.width};try{grip.setPointerCapture?.(event.pointerId);}catch{gesture=null;return;}element.classList.add('titan-sidebar-resizing');});
    listen(grip,'pointermove',event=>{if(!gesture||event.pointerId!==gesture.id)return;pref=widthFor(gesture.width+(event.clientX-gesture.x)*(right?-1:1),element.clientWidth,options,reserve());if(frame===null&&win.requestAnimationFrame)frame=win.requestAnimationFrame(()=>{frame=null;refresh(record);});else if(!win.requestAnimationFrame)refresh(record);});
    listen(grip,'pointerup',finish);listen(grip,'pointercancel',event=>finish(event));listen(grip,'lostpointercapture',()=>finish());
    listen(grip,'keydown',event=>{if(!enabled()||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const range=bounds(element.clientWidth,options,reserve());pref=event.key==='Home'?range.min:event.key==='End'?range.max:info.width+(event.key==='ArrowRight'?1:-1)*(right?-1:1)*(event.shiftKey?32:16);pref=widthFor(pref,element.clientWidth,options,reserve());persist();refresh(record);});
    listen(grip,'dblclick',()=>{if(!enabled())return;pref=options.width;persist();refresh(record);});
    function cleanup(){finish(null,false);grip.remove();}
    return info;
   }
   if(layout.rightOnly)record.right=gripFor(true);else record.left=gripFor();
   const detail=element.querySelector('.engine-inspector');if(layout.id==='docker'&&detail)record.right=gripFor(true);
   record.observer=typeof win.ResizeObserver==='function'?new win.ResizeObserver(()=>refresh(record)):null;record.observer?.observe(element);refresh(record);
  }
  function refresh(record){
   record.right?.apply();record.left?.apply();record.right?.apply();
   const tabs=record.sidebar.querySelector('[role=tablist]');if(tabs)tabs.setAttribute('aria-orientation',mobile()||record.layout.id==='docker'&&record.element.clientWidth<=620?'horizontal':'vertical');
  }
  function remove(record){record.observer?.disconnect();record.controller.abort();for(const item of record.grips)item.cleanup();delete record.element.dataset.sidebarLayout;record.element.style.removeProperty('--titan-sidebar-width');record.element.style.removeProperty('--titan-inspector-width');records.delete(record.element);}
  function reconcile(){
   pending=null;if(!alive)return;
   for(const record of [...records.values()])if(!scope.contains(record.element)||!record.element.contains(record.sidebar))remove(record);
   for(const layout of layouts)for(const element of scope.querySelectorAll(layout.selector))if(!records.has(element))attach(element,layout);
   for(const record of records.values())refresh(record);
  }
  function schedule(){if(pending!==null||!alive)return;if(win.requestAnimationFrame)pending=win.requestAnimationFrame(reconcile);else reconcile();}
  const mutations=typeof win.MutationObserver==='function'?new win.MutationObserver(changes=>{if(changes.some(change=>change.type==='childList'||change.attributeName==='class'&&!change.target.classList.contains('titan-sidebar-resizing')))schedule();}):null;
  reconcile();mutations?.observe(scope,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});media.addEventListener?.('change',schedule);
  function cleanup(){if(!alive)return;alive=false;mutations?.disconnect();media.removeEventListener?.('change',schedule);if(pending!==null)win.cancelAnimationFrame?.(pending);pending=null;for(const record of [...records.values()])remove(record);if(active===cleanup)active=null;}
  active=cleanup;return cleanup;
 }
 return {normalize,load,save,bounds,widthFor,mount,dispose};
});
