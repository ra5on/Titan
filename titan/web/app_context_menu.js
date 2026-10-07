'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root){root.TitanAppContextMenu=ui;root.document.addEventListener('DOMContentLoaded',()=>ui.mount(root.document),{once:true});}})(typeof window==='undefined'?null:window,function(){
 const rows='[data-engine-row],.engine-group-toolbar,[data-vm-row],[data-service-row],.cp-tile,.ac-app-card,.ac-native-card,.ac-installed-app,.package-service,.storage-area-card,.storage-disk-card';
 const controls='button[data-engine-action],button[data-action],button[data-service-action],button[data-cp-pin],button[data-apps-package],button[data-apps-open],button[data-native-toggle],button[data-native-manage],button[data-native-resume],button[data-native-refresh],button[data-storage-action],a[href^="#"]';
 const excluded='input,textarea,select,[contenteditable]:not([contenteditable="false"]),.xterm,.fb-browser,.console-panel,[role="menu"],.app-context-menu';
 function commands(row){
  const seen=new Set(),result=[];
  for(const node of row?.querySelectorAll(controls)||[]){
   if(node.closest?.('[hidden]'))continue;
   const d=node.dataset||{},key=[d.engineAction,d.engineId,d.action,d.id,d.serviceAction,d.service,d.command,d.cpPin,d.appsPackage,d.storageAction,node.hasAttribute?.('data-native-toggle')?'native-toggle':node.hasAttribute?.('data-native-manage')?'native-manage':node.hasAttribute?.('data-native-resume')?'native-resume':node.hasAttribute?.('data-native-refresh')?'native-refresh':'',node.getAttribute('href')].join('|');
   if(seen.has(key))continue;seen.add(key);
   let label=(node.getAttribute('aria-label')||node.textContent||'').replace(/\s+/g,' ').trim();
   if(d.engineAction==='select'||d.serviceAction==='details'||d.action==='vm-extensions')label='Details öffnen';
   if(d.action==='vm-console')label='Konsole öffnen';
   if(!label)continue;
   result.push({label,node,disabled:node.disabled===true||node.getAttribute('aria-disabled')==='true',danger:node.classList.contains('danger')||/(entfernen|deinstallieren|erzwingen)/i.test(label)});
  }
  return result.slice(0,14);
 }
 function mount(doc){
  const win=doc.defaultView;if(!win||doc.querySelector('.app-context-menu'))return null;
  const menu=doc.createElement('div');menu.className='app-context-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','Schnellaktionen');menu.hidden=true;doc.body.append(menu);
  let items=[],origin=null,hold=null,suppressUntil=0,disposed=false;
  const listeners=[],listen=(node,type,handler,options)=>{node.addEventListener(type,handler,options);listeners.push([node,type,handler,options]);};
  const available=item=>!item.disabled&&(!item.node||item.node.isConnected!==false);
  function close(restore=true){if(menu.hidden)return;menu.hidden=true;items=[];if(restore&&origin?.isConnected!==false)origin?.focus?.({preventScroll:true});}
  function cancelHold(){if(hold){win.clearTimeout(hold.timer);hold=null;}}
  function open(target,x,y){
   if(disposed||target.closest?.(excluded))return false;
   const scope=target.closest?.('.nas-window-content');if(!scope)return false;
   const row=target.closest(rows),page=doc.querySelector('#shell')?.dataset.page;
   items=commands(row);
   if(!row){const refresh=scope.querySelector('[data-action="refresh"],[data-engine-action="refresh"],[data-service-action="refresh"],[data-apps-refresh]');if(refresh)items.push({label:'Aktualisieren',node:refresh,disabled:refresh.disabled});}
   if(page&&/^[a-z][a-z0-9_-]*$/.test(page)&&win.parent!==win)items.push({label:'Zum Desktop hinzufügen',run:()=>win.parent.postMessage({type:'titan-pin-shortcut',key:'tool:'+page},win.location.origin)});
   if(!items.length)return false;
   origin=target.closest('button,a,[tabindex]')||null;menu.replaceChildren();
   const title=doc.createElement('div');title.className='app-context-title';title.textContent=row?.querySelector('h3,strong')?.textContent?.trim().slice(0,90)||'Schnellaktionen';menu.append(title);
   items.forEach((item,index)=>{const button=doc.createElement('button');button.type='button';button.setAttribute('role','menuitem');button.dataset.contextIndex=String(index);button.disabled=!available(item);button.textContent=item.label;if(item.danger)button.className='is-danger';menu.append(button);});
   menu.hidden=false;menu.style.left='0px';menu.style.top='0px';
   const rect=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(x,win.innerWidth-rect.width-8))+'px';menu.style.top=Math.max(8,Math.min(y,win.innerHeight-rect.height-8))+'px';
   menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});return true;
  }
  function run(index){const item=items[index];if(!item||!available(item)){close();return;}close(false);if(item.node){item.node.focus?.({preventScroll:true});item.node.click();}else item.run?.();}
  listen(doc,'contextmenu',event=>{if(event.defaultPrevented)return;cancelHold();if(open(event.target,event.clientX,event.clientY))event.preventDefault();});
  listen(doc,'pointerdown',event=>{if(!menu.hidden&&!menu.contains(event.target))close(false);if(event.pointerType!=='touch'||event.target.closest?.(excluded)||event.button!==0)return;cancelHold();const point={x:event.clientX,y:event.clientY,target:event.target,pointer:event.pointerId};point.timer=win.setTimeout(()=>{if(hold!==point)return;hold=null;if(open(point.target,point.x,point.y))suppressUntil=Date.now()+900;},550);hold=point;});
  listen(doc,'pointermove',event=>{if(hold&&event.pointerId===hold.pointer&&Math.hypot(event.clientX-hold.x,event.clientY-hold.y)>10)cancelHold();});
  listen(doc,'pointerup',cancelHold);listen(doc,'pointercancel',cancelHold);
  listen(doc,'click',event=>{if(Date.now()<suppressUntil&&!menu.contains(event.target)){event.preventDefault();event.stopPropagation();}},true);
  listen(menu,'click',event=>{const button=event.target.closest('[data-context-index]');if(button&&!button.disabled)run(Number(button.dataset.contextIndex));});
  listen(doc,'keydown',event=>{
   if(menu.hidden){if((event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')&&!event.defaultPrevented){const box=event.target.getBoundingClientRect();if(open(event.target,box.left+Math.min(40,box.width),box.bottom))event.preventDefault();}return;}
   if(event.key==='Escape'){event.preventDefault();close();return;}
   if(event.key==='Tab'){close(false);return;}
   if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
   event.preventDefault();const buttons=[...menu.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(doc.activeElement);if(!buttons.length)return;buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowUp'?-1:1)+buttons.length)%buttons.length].focus();
  });
  listen(win,'resize',()=>close(false));listen(win,'blur',()=>{cancelHold();close(false);});listen(doc,'scroll',()=>close(false),true);
  return {open,close,destroy(){disposed=true;cancelHold();for(const args of listeners)args[0].removeEventListener(args[1],args[2],args[3]);menu.remove();}};
 }
 return {commands,mount};
});
