'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanVMConsole=ui;})(typeof window==='undefined'?null:window,function(){
 const limit=64*1024;
 function mount({doc=document,win=window,client,connected=()=>false,status=()=>{}}){
  const toolbar=doc.querySelector('.topbar'),screen=doc.querySelector('#screen'),menu=doc.querySelector('[data-console-menu]'),dialog=doc.querySelector('#console-clipboard'),field=doc.querySelector('#console-clipboard-text');
  let guestText='',hold=null,heldUntil=0,alive=true,guestPointer=false;const listeners=[];
  const listen=(node,type,fn,options)=>{node?.addEventListener(type,fn,options);listeners.push(()=>node?.removeEventListener(type,fn,options));};
  const usable=()=>{if(!alive||!client()||!connected())throw Error('Bitte zuerst die VM-Konsole verbinden.');return client();};
  function shortcut(name){const rfb=usable();if(name==='cad'){rfb.sendCtrlAltDel();return;}const keys={copy:[0xffe3,'ControlLeft',0x63,'KeyC'],paste:[0xffe3,'ControlLeft',0x76,'KeyV'],tab:[0xffe9,'AltLeft',0xff09,'Tab']},key=keys[name];if(!key)return;rfb.sendKey(key[0],key[1],true);rfb.sendKey(key[2],key[3],true);rfb.sendKey(key[2],key[3],false);rfb.sendKey(key[0],key[1],false);rfb.focus();}
  function transfer(text){if(typeof text!=='string'||new TextEncoder().encode(text).length>limit)throw Error('Bitte höchstens 64 KiB Text übertragen.');usable().clipboardPasteFrom(text);status('Text an Gast-Zwischenablage übertragen. Dort mit Strg+V einfügen.');}
  function clipboardDialog(){field.value=guestText;dialog.showModal();field.focus();field.select();}
  async function copy(){if(!guestText){clipboardDialog();status('Im Gast zuerst Text kopieren. Eine gemeinsame Zwischenablage benötigt Unterstützung im Gastsystem.');return;}try{await win.navigator.clipboard.writeText(guestText);if(alive)status('Gast-Zwischenablage kopiert.');}catch{if(alive)clipboardDialog();}}
  async function paste(){usable();let text;try{text=await win.navigator.clipboard.readText();}catch(error){if(!alive)return;clipboardDialog();field.value='';status('Text im Zwischenablagefenster einfügen und an den Gast senden.');return;}if(alive)transfer(text);}
  async function fullscreen(){if(doc.fullscreenElement)await doc.exitFullscreen();else if(doc.documentElement.requestFullscreen)await doc.documentElement.requestFullscreen();else throw Error('Vollbild wird von diesem Browser nicht unterstützt.');}
  const commands={copy,paste,clipboard:clipboardDialog,fullscreen,menu:()=>{const rect=toolbar.getBoundingClientRect();showMenu(rect.right-250,rect.bottom);},'guest-pointer':()=>{guestPointer=!guestPointer;update();status(guestPointer?'Rechtsklick und langes Drücken gehen an die VM. Titan-Aktionen über das Menü öffnen.':'Rechtsklick öffnet wieder Titan-Schnellaktionen.');},'guest-copy':()=>shortcut('copy'),'guest-paste':()=>shortcut('paste'),'alt-tab':()=>shortcut('tab'),cad:()=>shortcut('cad'),focus:()=>client()?.focus(),scale:()=>{const rfb=usable();rfb.scaleViewport=!rfb.scaleViewport;update();}};
  function closeMenu(){if(menu)menu.hidden=true;}
  function update(){for(const node of doc.querySelectorAll('[data-console-action]')){const action=node.dataset.consoleAction;node.disabled=['guest-copy','guest-paste','alt-tab','cad','paste','scale'].includes(action)&&!connected();if(action==='scale')node.setAttribute('aria-pressed',String(client()?.scaleViewport!==false));if(action==='guest-pointer')node.setAttribute('aria-pressed',String(guestPointer));}}
  async function click(event){const button=event.target.closest?.('[data-console-action]');if(!button||button.disabled)return;closeMenu();try{await commands[button.dataset.consoleAction]?.();}catch(error){status(error.message);}}
  function showMenu(x,y){if(!alive||!menu)return;update();menu.hidden=false;menu.style.left='8px';menu.style.top='8px';const rect=menu.getBoundingClientRect();menu.style.left=8+Math.max(8,Math.min(x,win.innerWidth-rect.width-8))-rect.left+'px';menu.style.top=8+Math.max(8,Math.min(y,win.innerHeight-rect.height-8))-rect.top+'px';menu.querySelector('button:not(:disabled)')?.focus();}
  const cancelHold=()=>{if(hold)win.clearTimeout(hold.timer);hold=null;};
  listen(toolbar,'click',click);listen(menu,'click',click);
  listen(dialog,'submit',event=>{event.preventDefault();try{transfer(field.value);dialog.close();client()?.focus();}catch(error){status(error.message);}});
  listen(dialog,'click',event=>{if(event.target.closest?.('[data-console-close]')){dialog.close();client()?.focus();}if(event.target.closest?.('[data-console-copy-text]')){field.focus();field.select();win.navigator.clipboard?.writeText(field.value).catch(()=>status('Markierten Text mit Strg+C kopieren.'));}});
  listen(screen,'contextmenu',event=>{if(guestPointer)return;event.preventDefault();showMenu(event.clientX,event.clientY);},true);
  // Right-click belongs to Titan's action menu; do not send it to the guest too.
  for(const type of ['mousedown','mouseup'])listen(screen,type,event=>{if(event.button===2&&!guestPointer){event.preventDefault();event.stopImmediatePropagation();}},true);
  listen(doc,'pointerdown',event=>{if(!menu?.contains(event.target))closeMenu();});
  listen(screen,'pointerdown',event=>{cancelHold();if(guestPointer||!['touch','pen'].includes(event.pointerType))return;hold={x:event.clientX,y:event.clientY,timer:win.setTimeout(()=>{if(!hold||!alive)return;const point=hold;hold=null;heldUntil=Date.now()+800;showMenu(point.x,point.y);},550)};},true);
  listen(screen,'pointermove',event=>{if(hold&&Math.hypot(event.clientX-hold.x,event.clientY-hold.y)>10)cancelHold();},true);listen(screen,'pointerup',cancelHold,true);listen(screen,'pointercancel',cancelHold,true);
  listen(screen,'click',event=>{if(Date.now()<heldUntil){event.preventDefault();event.stopImmediatePropagation();}},true);
  listen(doc,'keydown',event=>{
   if(dialog.open)return;
   if(menu&&!menu.hidden){if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();closeMenu();client()?.focus();return;}if(menu.contains(event.target)&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const items=[...menu.querySelectorAll('button:not(:disabled)')],index=items.indexOf(doc.activeElement);items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();return;}if(event.key==='Tab')closeMenu();}
   if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();event.stopImmediatePropagation();const rect=screen.getBoundingClientRect();showMenu(rect.left+16,rect.top+16);return;}
   if((event.ctrlKey||event.metaKey)&&event.shiftKey&&!event.altKey&&['c','v'].includes(event.key.toLowerCase())){event.preventDefault();event.stopImmediatePropagation();void (event.key.toLowerCase()==='c'?copy():paste()).catch(error=>status(error.message));}
  },true);
  listen(win,'resize',closeMenu);listen(win,'blur',()=>{closeMenu();cancelHold();});update();
  return {update,transfer,shortcut,clipboard:text=>{if(typeof text==='string'&&new TextEncoder().encode(text).length<=limit){guestText=text;if(!dialog.open)field.value=text;}},destroy(){alive=false;cancelHold();listeners.forEach(remove=>remove());}};
 }
 return {mount,limit};
});
