'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object')module.exports=ui;if(root)root.TitanStorageRecovery=ui;})(typeof window==='undefined'?null:window,function(){
 let current=null;
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const bytes=value=>Number.isFinite(value)&&value>=0?new Intl.NumberFormat('de-DE',{maximumFractionDigits:1}).format(value/1024**3)+' GiB':'Größe unbekannt';
 const stateNames={ONLINE:'Online',DEGRADED:'Eingeschränkt',FAULTED:'Defekt',UNAVAIL:'Nicht verfügbar',OFFLINE:'Offline',REMOVED:'Entfernt'};
 function argumentsFor(data,fields){
  if(!data?.supported||data.scan?.active)throw Error(data?.reason||'Ein Laufwerkstausch ist derzeit nicht möglich.');
  const member=(data.members||[]).find(row=>row.guid===fields.member_guid&&row.replaceable===true);
  const disk=(data.candidates||[]).find(row=>row.disk===fields.disk&&row.eligible===true);
  if(!member)throw Error('Wähle ein ausgefallenes Mitglied aus.');
  if(!disk)throw Error('Wähle eine geeignete leere Ersatzplatte aus.');
  if(fields.confirmation_pool!==data.pool||fields.confirmation_disk!==disk.disk)throw Error('Bestätige Pool und Ersatzplatte durch die genaue Eingabe ihrer Namen.');
  if(!data.revision)throw Error('Der Speicherzustand ist nicht bestätigt. Lade ihn erneut.');
  return {pool:data.pool,member_guid:member.guid,disk:disk.disk,expected_revision:data.revision,confirmation_pool:fields.confirmation_pool,confirmation_disk:fields.confirmation_disk};
 }
 function render(data={}){
  const members=data.members||[],candidates=data.candidates||[],eligible=candidates.filter(row=>row.eligible===true),failed=members.filter(row=>row.replaceable===true),active=data.scan?.active===true;
  const percent=Number.isFinite(data.scan?.progress_percent)?Math.min(100,Math.max(0,data.scan.progress_percent)):null;
  const possible=data.supported===true&&!active&&eligible.length>0&&failed.length>0;
  return `<section class="storage-recovery" data-storage-recovery><header class="storage-recovery-heading"><div><span class="eyebrow">ZFS · ${esc(data.layout||'Aufbau nicht bestätigt')}</span><h3>${esc(data.pool)}</h3></div><span class="pill ${data.health==='ONLINE'?'':'red'}">${esc(stateNames[data.health]||data.health||'Unbekannt')}</span></header>${data.demo?'<p class="notice">Demo · Beispiel eines RAID-Zustands. Es werden keine echten Laufwerke geändert.</p>':''}<p class="hint">Ein Laufwerkstausch baut die fehlende Redundanz des bestehenden Pools wieder auf. RAID ersetzt keine Datensicherung.</p><div class="storage-recovery-scan" role="status" aria-live="polite" tabindex="-1"><strong>${active?(data.scan.kind==='resilver'?'Daten werden wieder aufgebaut':'Datenprüfung läuft'):'Kein Wiederaufbau aktiv'}</strong>${active?`<progress max="100" ${percent===null?'':`value="${percent}"`} aria-label="Wiederaufbaufortschritt"></progress><span>${percent===null?'Fortschritt noch nicht gemeldet':percent.toFixed(1).replace('.',',')+' %'}</span>`:''}<p>${esc(data.scan?.detail||'')}</p></div><h4>Pool-Laufwerke</h4><div class="storage-recovery-members">${members.map(row=>`<div><span><strong>${esc(row.path||row.guid)}</strong><small>GUID ${esc(row.guid)}</small></span><span>${esc(stateNames[row.state]||row.state)}<small>Lesen ${esc(row.read_errors??'—')} · Schreiben ${esc(row.write_errors??'—')} · Prüfsumme ${esc(row.checksum_errors??'—')}</small></span></div>`).join('')||'<p class="hint">Keine bestätigten Laufwerksdaten verfügbar.</p>'}</div>${data.reason||!data.supported||active?`<p class="notice ${data.health==='ONLINE'?'':'warning'}">${esc(data.reason||(active?'Warte, bis der laufende Wiederaufbau oder Prüflauf abgeschlossen ist.':'Für diesen Pool ist kein geführter Laufwerkstausch verfügbar.'))}</p>`:''}${!active&&data.supported&&!eligible.length?'<p class="notice warning">Keine geeignete leere Ersatzplatte verfügbar. Schließe eine ausreichend große, unbenutzte Platte an und aktualisiere den Zustand.</p>':''}${candidates.length?`<details class="storage-recovery-candidates"><summary>Ersatzplatten prüfen · ${eligible.length} geeignet</summary>${candidates.map(row=>`<div><span><strong>${esc(row.model||row.disk)}</strong><small>${esc(row.disk)} · ${bytes(row.size)}${row.serial?' · SN '+esc(row.serial):''}</small></span><span class="${row.eligible?'':'error-text'}">${esc(row.eligible?'Geeignet':row.reason||'Nicht geeignet')}</span></div>`).join('')}</details>`:''}${possible?`<form data-storage-replacement><label>Ausgefallenes Laufwerk<select name="member_guid" required><option value="">Laufwerk auswählen</option>${failed.map(row=>`<option value="${esc(row.guid)}">${esc(row.path||row.guid)} · ${esc(stateNames[row.state]||row.state)}</option>`).join('')}</select></label><label>Leere Ersatzplatte<select name="disk" required><option value="">Ersatzplatte auswählen</option>${eligible.map(row=>`<option value="${esc(row.disk)}">${esc(row.model||row.disk)} · ${esc(row.disk)} · ${bytes(row.size)}${row.serial?' · SN '+esc(row.serial):''}</option>`).join('')}</select></label><p class="notice warning">Die gewählte Ersatzplatte wird dem Pool hinzugefügt und beschrieben. Titan prüft den aktuellen Zustand vor dem Start erneut. Bestehende Pool-Laufwerke werden nicht formatiert.</p><div class="form-grid"><label>Poolname zur Bestätigung<input name="confirmation_pool" autocomplete="off" spellcheck="false" placeholder="${esc(data.pool)}" required></label><label>Gerätepfad der Ersatzplatte<input name="confirmation_disk" autocomplete="off" spellcheck="false" placeholder="Zum Beispiel /dev/sdc" required></label></div><div class="form-actions"><button type="submit" class="button primary" data-recovery-submit disabled>Ja, Wiederaufbau starten</button><button type="button" class="button" data-action="close">Nein</button></div></form>`:''}<p class="error-text" data-recovery-error role="alert" hidden></p><footer class="form-actions"><button type="button" class="button small" data-recovery-refresh>Zustand aktualisieren</button>${possible?'':'<button type="button" class="button small" data-action="close">Schließen</button>'}</footer><details><summary>Technischer Poolstatus</summary><pre class="code">${esc(data.raw_status||'Kein Poolstatus gemeldet.')}</pre></details></section>`;
 }
 function mount(container,initial,ctx){
  let data=initial,alive=true,busy=false,request=0,timer=null,controller=null;
  const win=container.ownerDocument?.defaultView||globalThis,modal=container.closest?.('dialog');
  const fields=()=>Object.fromEntries(['member_guid','disk','confirmation_pool','confirmation_disk'].map(name=>[name,container.querySelector(`[name="${name}"]`)?.value||'']));
  const setError=error=>{const node=container.querySelector('[data-recovery-error]');if(node){node.textContent=error?.message||String(error||'');node.hidden=!error;}};
  function synchronize(){const submit=container.querySelector('[data-recovery-submit]');if(submit){try{argumentsFor(data,fields());submit.disabled=busy;}catch{submit.disabled=true;}}}
  function paint(){const restoreFocus=container.ownerDocument?.activeElement?.matches?.('[data-recovery-refresh]');container.innerHTML=render(data);synchronize();if(restoreFocus)container.querySelector('[data-recovery-refresh]')?.focus?.({preventScroll:true});if(timer!==null){win.clearInterval(timer);timer=null;}if(data.scan?.active)timer=win.setInterval(()=>{void refresh();},5000);}
  async function refresh(){
   if(!alive||busy)return;busy=true;const token=++request;controller=new AbortController();synchronize();
   try{const next=await ctx.api('/api/storage/recovery?pool='+encodeURIComponent(data.pool),undefined,{signal:controller.signal});if(!alive||token!==request)return;data=next;paint();}
   catch(error){if(alive&&token===request&&error.name!=='AbortError'){data={...data,supported:false,reason:'Der aktuelle Poolzustand konnte nicht bestätigt werden. Aktualisiere ihn vor einem Laufwerkstausch.'};setError(error);}}
   finally{if(alive&&token===request){busy=false;controller=null;synchronize();}}
  }
  async function submit(event){
   if(!event.target.matches?.('[data-storage-replacement]'))return;event.preventDefault();if(busy||!alive)return;
   let args;try{args=argumentsFor(data,fields());}catch(error){setError(error);return;}
   busy=true;synchronize();setError(null);container.querySelectorAll('input,select,[data-recovery-refresh]').forEach(node=>node.disabled=true);
   try{await ctx.action('pool_replace',args,{wait:true});if(!alive)return;ctx.toast?.('Laufwerkstausch gestartet. Der Poolstatus zeigt den tatsächlichen Wiederaufbau.');busy=false;await refresh();if(alive){if(modal)modal.scrollTop=0;container.querySelector('.storage-recovery-scan')?.focus?.({preventScroll:true});}}
   catch(error){if(alive){setError(error);data={...data,supported:false};}}
   finally{if(alive){busy=false;container.querySelector('[data-recovery-refresh]')?.removeAttribute('disabled');const refreshButton=container.querySelector('[data-recovery-refresh]');if(refreshButton)refreshButton.disabled=false;synchronize();}}
  }
  const click=event=>{if(event.target.closest?.('[data-recovery-refresh]'))void refresh();};
  const change=()=>synchronize();
  function destroy(){alive=false;request++;controller?.abort();if(timer!==null)win.clearInterval(timer);container.removeEventListener('submit',submit);container.removeEventListener('input',change);container.removeEventListener('change',change);container.removeEventListener('click',click);modal?.removeEventListener('close',destroy);if(current?.destroy===destroy)current=null;}
  container.addEventListener('submit',submit);container.addEventListener('input',change);container.addEventListener('change',change);container.addEventListener('click',click);modal?.addEventListener('close',destroy);paint();return {refresh,destroy};
 }
 async function open(pool,ctx){
  disposeDialog();if(ctx.dialog('RAID-Zustand und Reparatur','<div data-recovery-container><p role="status">Poolzustand und Ersatzplatten werden geprüft …</p></div>')===false)return;
  const body=typeof ctx.dialogRoot==='function'?ctx.dialogRoot():ctx.dialogRoot,container=body?.querySelector('[data-recovery-container]');if(!container)return;
  // A close or another dialog invalidates the pending read before it can render.
  const modal=container.closest?.('dialog'),controller=new AbortController();let alive=true;
  const cancel=()=>{alive=false;controller.abort();modal?.removeEventListener('close',cancel);};current={destroy:cancel};modal?.addEventListener('close',cancel);
  try{const data=await ctx.api('/api/storage/recovery?pool='+encodeURIComponent(pool),undefined,{signal:controller.signal});if(!alive)return;modal?.removeEventListener('close',cancel);current=mount(container,data,ctx);}
  catch(error){if(alive&&error.name!=='AbortError')container.innerHTML=`<p class="notice warning" role="alert">${esc(error.message)}</p><div class="form-actions"><button type="button" class="button" data-action="close">Schließen</button></div>`;}
 }
 function disposeDialog(){current?.destroy();current=null;}
 return {render,argumentsFor,mount,open,disposeDialog};
});
