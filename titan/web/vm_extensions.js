'use strict';
(function(root){
 let pending=null;
 let current=null,currentInline=false,currentManager=null,currentSelection=null;
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const tabs=[['overview','Übersicht'],['console','Konsole'],['hardware','Hardware'],['network','Netzwerk'],['backups','Sicherungen']];
 const button=(name,command,attributes='',variant='')=>`<button type="button" class="button${variant?' '+variant:''}" data-vmx-command="${command}" ${attributes}>${name}</button>`;
 const field=(name,key,type='text',value='',extra='')=>`<label class="field">${name}<input name="${key}" type="${type}" value="${esc(value)}" ${extra}></label>`;
 function render(vm,data,tab,{bytes}){
  tab=tabs.some(([id])=>id===tab)?tab:'overview';
  const offline=data.state==='shut off',disabled=offline?'':'disabled',agent=data.guest_agent||{},snapshotDisabled=offline||data.state==='running'||data.state==='in shutdown'?'':'disabled';
  const navigation=`<nav class="manager-tabs" role="tablist" aria-label="VM-Bereiche">${tabs.map(([id,label])=>`<button type="button" role="tab" id="vmx-tab-${id}" class="button ${tab===id?'primary':''}" data-vmx-tab="${id}" aria-selected="${tab===id}" aria-controls="vmx-panel-${id}" tabindex="${tab===id?'0':'-1'}">${label}</button>`).join('')}</nav>`;
  let content='';
  if(tab==='overview')content=`<p class="vm-live-caption">Live-Werte · Aktualisierung alle 5 Sekunden</p><div data-vmx-live>${root?.TitanVMLive?.render({...vm,state:data.state},{bytes,esc})||''}</div><dl class="vm-overview-facts"><div><dt>Bootmodus</dt><dd>${vm.firmware==='uefi'?'UEFI':'BIOS'}</dd></div><div><dt>CPU-Zuweisung</dt><dd>${vm.cpu_ids?.length?vm.cpu_ids.map(id=>'CPU '+Number(id)).join(', '):'Automatisch'}</dd></div><div><dt>Autostart</dt><dd>${vm.autostart?'Aktiviert':'Deaktiviert'}</dd></div></dl><section><h3>Gast und Verbindungen</h3><p>${esc(agent.message||'Gastagent nicht verbunden.')}</p>${agent.interfaces?.filter(item=>item.addresses?.length).map(item=>`<p>${esc(item.name)} · ${item.addresses.map(esc).join(', ')}</p>`).join('')||''}</section><p class="hint">RAM auf NAS (RSS) ist der residente Speicher des VM-Prozesses einschließlich Verwaltungsaufwand. Die Belegung im Gast kann davon abweichen.</p>`;
  if(tab==='console')content=data.state==='running'?`<iframe class="vm-console-frame" title="Konsole ${esc(vm.display_name||vm.name)}" src="/console.html?vm=${encodeURIComponent(vm.id)}&embedded=1&name=${encodeURIComponent(vm.display_name||vm.name)}" allow="fullscreen"></iframe>`:'<div class="notice">Die Konsole ist verfügbar, sobald die VM läuft. Über die schnellen VM-Aktionen starten.</div>';
  if(tab==='hardware')content=`<div class="app-details"><div><small>Prozessoren</small><p>${Number(vm.cpus)||0} vCPU · ${vm.cpu_ids?.length?vm.cpu_ids.map(id=>'CPU '+Number(id)).join(', '):'Automatische Zuweisung'}</p></div><div><small>Bootmodus</small><p>${vm.firmware==='uefi'?'UEFI':'BIOS'}</p></div></div><div class="vm-extension-list">${(data.disks||[]).map(disk=>`<div class="vm-extension-row"><div><strong>${esc(disk.target)} · ${disk.boot?'Systemlaufwerk':'Zusätzliches Laufwerk'}</strong><small>${bytes(disk.virtual_size)} Kapazität · ${bytes(disk.allocated_bytes)} belegt</small><small>${esc(disk.disk)}</small></div>${disk.boot?'':button('Trennen','disk-remove',`data-target="${esc(disk.target)}" ${disabled}`)}</div>`).join('')}</div><div class="vm-extension-actions">${button('CPU, RAM & Bootmodus','edit',disabled)}${button('Festplatte hinzufügen','disk-add',disabled)}${button('USB-Geräte','usb',disabled)}${button('Klon erstellen','clone',disabled)}</div><section class="package-login"><h3>Gastagent</h3><p>${esc(agent.message)}</p>${agent.interfaces?.filter(item=>item.addresses?.length).map(item=>`<p>${esc(item.name)} · ${item.addresses.map(esc).join(', ')}</p>`).join('')||''}<div class="vm-extension-actions">${button(agent.configured?'Gastagent-Kanal deaktivieren':'Gastagent-Kanal aktivieren','guest-agent',`${disabled} data-enabled="${agent.configured?'false':'true'}"`)}${button('Über Gastagent herunterfahren','guest-shutdown',agent.connected?'':'disabled')}</div></section>`;
  if(tab==='network')content=`<div class="vm-extension-list">${(data.networks||[]).map(nic=>`<div class="vm-extension-row"><div><strong>Netzwerkkarte ${nic.index+1} · ${esc(nic.model)}</strong><small>${esc(nic.source)} · ${nic.mode==='network'?'Virtuelles Netzwerk':nic.mode==='bridge'?'LAN-Bridge':'Direkt / macvtap'}</small><small>${esc(nic.mac||'Automatische MAC-Adresse')} · ${nic.connected?'Kabel verbunden':'Kabel getrennt'}</small></div>${button('Entfernen','nic-remove',`data-index="${Number(nic.index)}" ${disabled}`)}</div>`).join('')||'<p class="notice">Diese VM besitzt keine Netzwerkkarte.</p>'}</div><div class="vm-extension-actions">${button('Netzwerkkarte hinzufügen','nic-add',disabled)}${button('Primäre Karte bearbeiten','edit',disabled)}</div><p class="hint">NAT für einen eigenen VM-Adressbereich, bestehende LAN-Bridge für direkten LAN-Zugriff oder macvtap über einen vorhandenen Anschluss. Die NAS-Verbindung wird nicht verändert.</p>`;
  if(tab==='backups')content=`<p class="notice">${esc(data.snapshot_note)}</p><div class="vm-extension-actions">${button('Snapshot erstellen','snapshot-create',snapshotDisabled)}${button('Extern sichern','backup',snapshotDisabled)}${button('Klon erstellen','clone',disabled)}</div>${!offline?'<p class="hint">Für Snapshot und externe Sicherung kannst du das geordnete Herunterfahren im nächsten Schritt bestätigen. Die VM wird niemals zwangsweise ausgeschaltet. Eine pausierte VM zuerst fortsetzen.</p>':''}<p class="hint">Die externe Sicherung enthält alle verwalteten Laufwerke, VM-Konfiguration und UEFI-Variablen. Snapshots werden als neue ausgeschaltete VM wiederhergestellt; die ursprüngliche VM bleibt erhalten.</p><div class="vm-extension-list">${(data.snapshots||[]).map(snapshot=>`<div class="vm-extension-row"><div><strong>${esc(snapshot.name)}</strong><small>${new Date(snapshot.created*1000).toLocaleString('de-DE')} · ${snapshot.disk_count} Laufwerk${snapshot.disk_count===1?'':'e'}</small></div><div class="form-actions wrap">${button('Als neue VM wiederherstellen','snapshot-restore',`data-snapshot="${esc(snapshot.id)}" ${snapshotDisabled}`)}${button('Entfernen','snapshot-remove',`data-snapshot="${esc(snapshot.id)}" ${disabled}`)}</div></div>`).join('')||'<p class="hint">Noch keine Snapshots vorhanden.</p>'}</div>`;
  const stateNames={'running':'Läuft','shut off':'Gestoppt','paused':'Pausiert','blocked':'Wartet','in shutdown':'Wird heruntergefahren'};
  const actions=`${data.state==='running'?button('Herunterfahren','shutdown'):button(data.state==='paused'?'Fortsetzen':'Starten',data.state==='paused'?'resume':'start',offline||data.state==='paused'?'':'disabled')}<details class="vm-header-more"><summary class="button" aria-label="Weitere VM-Aktionen">⋯</summary><div>${data.state==='running'?button('Neustarten','reboot'):''}${button('VM-Einstellungen','edit',disabled)}${data.state==='running'?button('Pausieren','suspend'):''}${button(vm.autostart?'Autostart ausschalten':'Autostart einschalten',vm.autostart?'disable-autostart':'autostart')}${button('USB-Geräte','usb',disabled)}${button('Installationsmedium','media',disabled)}${button('Laufwerk erweitern','grow',disabled)}${button('VM entfernen','remove',disabled)}${!offline?button('Ausschalten erzwingen','force-off'):''}</div></details>`;
  return `<section class="vm-extension-detail" data-vmx-vm="${esc(vm.id)}"><header class="vm-detail-header">${button(tab==='console'?'←':'← Maschinen','back',tab==='console'?'aria-label="Zurück zu Maschinen" title="Zurück zu Maschinen"':'')}<div class="vm-detail-title"><h2>${esc(vm.display_name||vm.name)}</h2><span class="pill ${offline?'gray':''}">${esc(stateNames[data.state]||data.state)}</span></div>${tab!=='console'?button('Konsole öffnen','console','','primary'):''}${button('↻','refresh','aria-label="VM aktualisieren"')}${button(tab==='console'?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4M12 7v7m-3-3 3 3 3-3"/></svg>':'Konsole auf Desktop','desktop','aria-label="Konsole auf Desktop" title="Konsole auf Desktop"')}<div class="vm-detail-quick-actions">${actions}</div></header>${navigation}<div class="vm-operation-status" role="status" data-vmx-status hidden></div><div class="vm-detail-content ${tab==='console'?'is-console':''}" data-vmx-content role="tabpanel" id="vmx-panel-${tab}" aria-labelledby="vmx-tab-${tab}">${!offline&&['hardware','network'].includes(tab)?'<p class="hint">Hardwareänderungen und Klonen sind nach vollständigem Herunterfahren verfügbar.</p>':''}${content}<div class="form-error" role="alert" data-vmx-error hidden></div></div>${tabs.filter(([id])=>id!==tab).map(([id])=>`<div role="tabpanel" id="vmx-panel-${id}" aria-labelledby="vmx-tab-${id}" hidden></div>`).join('')}</section>`;
 }
 function storageField(options){const choices=options.storage||options.storage_options||[],selected=options.default_storage?choices.find(item=>item.id===options.default_storage):choices.find(item=>item.available!==false&&item.status!=='full'),missing=Boolean(options.default_storage&&!selected);return `<label class="field">Speicherbereich<select name="storage" required>${missing?`<option value="${esc(options.default_storage)}" selected disabled>Standardspeicher · Nicht verfügbar</option>`:!choices.length?'<option value="">Kein Speicher verfügbar</option>':''}${choices.map(item=>`<option value="${esc(item.id)}" ${item===selected?'selected':''} ${item.available===false||item.status==='full'?'disabled':''}>${esc(item.id==='system'?'Interner Speicher':item.label||item.name||item.id)}${item.status==='full'?' · Voll':item.available===false?' · Nicht verfügbar':Number.isFinite(item.free_bytes)?' · '+new Intl.NumberFormat('de-DE',{maximumFractionDigits:1}).format(item.free_bytes/1024**3)+' GiB frei':''}</option>`).join('')}</select></label>`;}
 function dispose(){pending?.abort();pending=null;current?.abort();current=null;currentInline=false;currentManager=null;currentSelection=null;}
 function closeSelection(manager){
  if(currentManager===manager)dispose();
  const host=manager?.querySelector?.('[data-vm-detail-host]');if(!host)return;
  host.innerHTML='';host.hidden=true;manager.classList.remove('has-vm-detail');delete manager.dataset.vmDetailTab;delete manager.dataset.vmSelected;
  const master=manager.querySelector('.vm-master-pane');if(master){master.hidden=false;reveal(master,true);}
  for(const row of manager.querySelectorAll('[data-vm-row]')){row.classList.remove('is-selected');row.querySelector('.vm-row-select')?.removeAttribute('aria-current');}
 }
 function reveal(node,back=false){if(!node?.animate||root.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)return;node.animate([{opacity:0,transform:back?'translateY(-6px)':'translateY(12px) scale(.99)'},{opacity:1,transform:'none'}],{duration:back?220:320,easing:'cubic-bezier(.2,.8,.2,1)'});}
 function disposeDialog(){if(!currentInline)dispose();}
 async function open(vm,context,tab='overview'){
  const alreadySelected=context.container?.dataset.vmSelected===String(vm.id);
  pending?.abort();const controller=new AbortController();pending=controller;const signal=controller.signal,{api,dialog,action,askYesNo,bytes,legacy,onBack}=context;
  const manager=context.container,selection=manager?.querySelector?.('[data-vm-detail-host]'),container=selection||manager;
  tab=tabs.some(([id])=>id===tab)?tab:'overview';
  let data,options,freshList;
  try{[data,options,freshList]=await Promise.all([api('/api/vm-extensions?'+new URLSearchParams({vm:vm.id})),api('/api/vm-options'),api('/api/vms').catch(()=>null)]);}catch(error){if(signal.aborted)return;if(pending===controller)pending=null;controller.abort();throw error;}
  if(signal.aborted)return;
  // Keep the previous view and its handlers alive until the next view is ready.
  pending=null;dispose();current=controller;currentInline=Boolean(context.container);currentManager=selection?manager:null;
  vm={...vm,...(freshList?.vms||[]).find(item=>item.id===vm.id),state:data.state};
  let body,modal;
  if(container){
   body=container;
   const sameView=alreadySelected&&manager?.dataset.vmDetailTab===tab,scroll=sameView?body.querySelector('[data-vmx-content]')?.scrollTop||0:0;
   const active=root.document.activeElement,focus=sameView&&body.contains(active)?active?.dataset?.vmxCommand:null;
   const consoleFrame=sameView&&tab==='console'&&data.state==='running'?body.querySelector('.vm-console-frame'):null;
   const markup=render(vm,data,tab,{bytes});
   if(consoleFrame){
    // Moving an iframe preserves its Node but destroys its browsing context.
    // Keep its entire content subtree connected and update only its siblings.
    const header=body.querySelector('.vm-detail-header'),navigation=body.querySelector('.manager-tabs');
    if(header)header.outerHTML=markup.match(/<header class="vm-detail-header"[^]*?<\/header>/)[0];
    if(navigation)navigation.outerHTML=markup.match(/<nav class="manager-tabs"[^]*?<\/nav>/)[0];
    for(const selector of ['[data-vmx-status]','[data-vmx-error]']){const node=body.querySelector(selector);if(node){node.hidden=true;node.textContent='';}}
   }else body.innerHTML=markup;
   const content=body.querySelector('[data-vmx-content]');if(content)content.scrollTop=scroll;if(!sameView)reveal(alreadySelected?content:body);
   if(focus)body.querySelector(`[data-vmx-command="${focus}"]`)?.focus({preventScroll:true});
   if(selection){selection.hidden=false;manager.classList.add('has-vm-detail');manager.dataset.vmDetailTab=tab;manager.dataset.vmSelected=String(vm.id);currentSelection={id:String(vm.id),tab};
    const master=manager.querySelector('.vm-master-pane');if(master)master.hidden=true;
    for(const row of manager.querySelectorAll('[data-vm-row]')){const selected=row.dataset.vmRow===String(vm.id);row.classList.toggle('is-selected',selected);const link=row.querySelector('.vm-row-select');if(selected)link?.setAttribute('aria-current','true');else link?.removeAttribute('aria-current');}
    if(!alreadySelected)body.querySelector('[data-vmx-command="back"]')?.focus({preventScroll:true});
   }else body.classList.add('has-vm-detail');
  }
  else{current=null;currentInline=false;if(dialog((vm.display_name||vm.name)+' · Virtuelle Maschine',render(vm,data,tab,{bytes}))===false){controller.abort();return;}current=controller;body=root.document.getElementById('dialog-body');modal=root.document.getElementById('dialog');}
  root.addEventListener?.('message',event=>{if(event.origin!==root.location?.origin||event.source!==body.querySelector('.vm-console-frame')?.contentWindow||event.data?.type!=='titan-console-back')return;body.querySelector('[data-vmx-command=back]')?.click();},{signal});
  const error=message=>{if(signal.aborted)return;const node=body.querySelector('[data-vmx-error]');if(node){node.hidden=false;node.textContent=message;}};
  const progress=job=>{if(signal.aborted)return;const node=body.querySelector('[data-vmx-status]');if(node){node.hidden=false;node.textContent=job.result?.error||job.result?.message||(job.status==='queued'?'Aktion wartet …':job.status==='running'?'Aktion wird ausgeführt …':'Aktion abgeschlossen.');}};
  let operationBusy=false;
  const reopen=async()=>open(vm,context,tab);
  const shutdownField=()=>data.state==='shut off'?'':'<label class="check-label"><input type="checkbox" name="shutdown" required> VM geordnet herunterfahren und anschließend fortfahren</label><p class="hint">Titan wartet höchstens 120 Sekunden. Bei ausbleibendem Herunterfahren wird die Aktion ohne erzwungenes Ausschalten abgebrochen. Die VM bleibt danach ausgeschaltet.</p>';
  const run=async(operation,args)=>{if(operationBusy)return;operationBusy=true;const controls=[...body.querySelectorAll('[data-vmx-command],[data-vmx-tab]')].map(node=>({node,disabled:node.disabled}));controls.forEach(({node})=>node.disabled=true);try{const result=await action(operation,{vm:vm.id,...args},{wait:true,onProgress:progress});if(signal.aborted)return;await reopen();const node=(container||root.document.getElementById('dialog-body')).querySelector('[data-vmx-status]');if(node){node.hidden=false;node.textContent=result?.message||'Aktion erfolgreich abgeschlossen.';}return result;}finally{operationBusy=false;if(!signal.aborted)controls.forEach(({node,disabled})=>node.disabled=disabled);}};
  function form(title,html,operation,args){
   const submitLabel={vm_clone:'Klon erstellen',vm_disk_add:'Festplatte hinzufügen',vm_nic_add:'Netzwerkkarte hinzufügen',vm_snapshot_create:'Snapshot erstellen',vm_snapshot_restore_new:'Neue VM wiederherstellen'}[operation]||'Speichern';
   const content=body.querySelector('[data-vmx-content]');if(!content)return;
   content.classList.remove('is-console');content.innerHTML=`<form data-vmx-form><h3>${esc(title)}</h3>${html}<p class="form-error" data-vmx-error role="alert" hidden></p><div class="form-actions"><button class="button primary" type="submit">${esc(submitLabel)}</button><button class="button" type="button" data-vmx-command="cancel-form">Abbrechen</button></div></form>`;content.scrollTop=0;
   const formNode=content.querySelector('form');formNode.addEventListener('submit',async event=>{event.preventDefault();const submit=formNode.querySelector('[type=submit]');submit.disabled=true;try{await run(operation,args(new FormData(formNode)));}catch(exc){error(exc.message);}finally{submit.disabled=false;}},{signal});
  }
  body.addEventListener('click',async event=>{
   const target=event.target.closest?.('[data-vmx-command],[data-vmx-tab]');if(!target||!body.contains(target)||target.disabled||operationBusy)return;event.preventDefault();
   target.disabled=true;try{
    if(target.dataset.vmxTab){await open(vm,context,target.dataset.vmxTab);(container||root.document.getElementById('dialog-body')).querySelector(`[data-vmx-tab="${target.dataset.vmxTab}"]`)?.focus({preventScroll:true});return;}
    const command=target.dataset.vmxCommand;
    if(command==='back'){
     if(root.location?.hash?.includes('?vm='))root.history?.replaceState(null,'','#vms');
     const selectedId=String(vm.id);dispose();
     if(selection){closeSelection(manager);[...manager.querySelectorAll('[data-vm-row]')].find(row=>row.dataset.vmRow===selectedId)?.querySelector('.vm-row-select')?.focus({preventScroll:true});}
     else if(container){container.classList.remove('has-vm-detail');await onBack?.();}else modal.close();return;
    }
    if(command==='refresh'||command==='cancel-form'){await reopen();return;}
    if(command==='desktop'){await context.pin?.(vm);return;}
    if(command==='console'){await open(vm,context,'console');return;}
    if(['start','shutdown','reboot','resume','suspend','autostart','disable-autostart'].includes(command)){if(['shutdown','reboot'].includes(command)&&!await askYesNo(command==='shutdown'?'Diese VM herunterfahren?':'Diese VM neu starten?'))return;await run('vm_action',{action:command});return;}
    if(['edit','usb','backup','media','grow','remove','force-off'].includes(command)){
     if(!container){dispose();await legacy?.(command,vm);return;}
     const modal=root.document.getElementById('dialog');modal.addEventListener('close',()=>{if(!signal.aborted)reopen().catch(exc=>error(exc.message));},{signal,once:true});await legacy?.(command,vm);return;
    }
    if(command==='clone'){form('VM klonen',`${field('Name des Klons','name','text',(vm.display_name||vm.name).slice(0,88)+' Kopie','required maxlength="96"')}${storageField(options)}<p class="hint">Alle Festplatten werden unabhängig kopiert. USB-Geräte und MAC-Adressen werden nicht übernommen. Gast-IP und Rechnernamen vor dem ersten Start prüfen.</p>`,'vm_clone',values=>({name:values.get('name'),storage:values.get('storage')}));return;}
    if(command==='disk-add'){form('Festplatte hinzufügen',`${field('Kapazität (GiB)','disk_gb','number',32,'required min="1" max="16384"')}${storageField(options)}<p class="hint">Das neue Laufwerk anschließend im Gastsystem partitionieren und formatieren.</p>`,'vm_disk_add',values=>({disk_gb:Number(values.get('disk_gb')),storage:values.get('storage')}));return;}
    if(command==='nic-add'){form('Netzwerkkarte hinzufügen',root.TitanVMNetwork.fields(options,null,esc),'vm_nic_add',values=>({network:root.TitanVMNetwork.args(values)}));return;}
    if(command==='snapshot-create'){form('Snapshot erstellen',`${field('Name','name','text','Vor Änderung','required maxlength="80"')}<p class="notice">${esc(data.snapshot_note)}</p>${shutdownField()}`,'vm_snapshot_create',values=>({name:values.get('name'),shutdown:values.has('shutdown')}));return;}
    if(command==='guest-agent'){await run('vm_guest_agent',{enabled:target.dataset.enabled==='true'});return;}
    if(command==='guest-shutdown'){if(await askYesNo('Diese VM über den Gastagenten herunterfahren?'))await run('vm_guest_action',{action:'shutdown'});return;}
    if(command==='disk-remove'){if(await askYesNo('Dieses zusätzliche Laufwerk von der VM trennen? Die Image-Datei bleibt erhalten.'))await run('vm_disk_remove',{target:target.dataset.target});return;}
    if(command==='nic-remove'){if(await askYesNo('Diese Netzwerkkarte entfernen?'))await run('vm_nic_remove',{index:Number(target.dataset.index)});return;}
    if(command==='snapshot-restore'){form('Snapshot als neue VM wiederherstellen',`${field('Name der neuen VM','name','text',(vm.display_name||vm.name).slice(0,86)+' Snapshot','required maxlength="96"')}${storageField(options)}<p class="notice">Die ursprüngliche VM und ihre aktuellen Dateien bleiben erhalten. Der Snapshot wird in eigene Laufwerke kopiert. Die neue VM erhält eine eigene Kennung und neue MAC-Adressen und bleibt ausgeschaltet. Gast-IP und Rechnernamen vor dem ersten Start prüfen.</p>${shutdownField()}`,'vm_snapshot_restore_new',values=>({snapshot:target.dataset.snapshot,name:values.get('name'),storage:values.get('storage'),shutdown:values.has('shutdown')}));return;}
    if(command==='snapshot-remove'){if(await askYesNo('Diesen Snapshot entfernen? Die aktuellen VM-Daten bleiben erhalten.'))await run('vm_snapshot_remove',{snapshot:target.dataset.snapshot});return;}
   }catch(exc){error(exc.message);}finally{target.disabled=false;}
  },{signal});
  body.addEventListener('keydown',async event=>{
   const target=event.target.closest?.('[data-vmx-tab]');if(!target||!body.contains(target)||operationBusy||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
   const position=tabs.findIndex(([id])=>id===target.dataset.vmxTab),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(position+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
   event.preventDefault();try{await open(vm,context,tabs[next][0]);(container||root.document.getElementById('dialog-body')).querySelector(`[data-vmx-tab="${tabs[next][0]}"]`)?.focus();}catch(exc){error(exc.message);}
  },{signal});
  modal?.addEventListener('close',()=>controller.abort(),{signal,once:true});
  if(tab==='overview'){
   let busy=false;
   const refresh=async()=>{if(signal.aborted||busy||operationBusy||root.document.hidden)return;busy=true;try{const result=await api('/api/vms');if(signal.aborted)return;const fresh=(result.vms||[]).find(item=>item.id===vm.id),node=body.querySelector('[data-vmx-live]');if(fresh&&fresh.state!==data.state){await open(fresh,context,tab);return;}if(fresh&&node){root.TitanVMLive?.record?.(fresh);node.innerHTML=root.TitanVMLive?.render(fresh,{bytes,esc})||'';}else if(node)node.innerHTML='<p class="vm-live-unavailable">Messwerte momentan nicht erreichbar.</p>';}catch{if(!signal.aborted){const node=body.querySelector('[data-vmx-live]');if(node)node.innerHTML='<p class="vm-live-unavailable">Messwerte momentan nicht erreichbar.</p>';}}finally{busy=false;}};
   const timer=setInterval(refresh,5000),visibility=()=>{if(!root.document.hidden)refresh();};root.document.addEventListener?.('visibilitychange',visibility,{signal});signal.addEventListener('abort',()=>clearInterval(timer),{once:true});
  }
 }
 const api={open,render,storageField,dispose,disposeDialog,closeSelection,selectionState:()=>currentSelection?{...currentSelection}:null};if(root)root.TitanVMExtensions=api;if(typeof module==='object')module.exports=api;
})(typeof window==='undefined'?null:window);
