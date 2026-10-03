'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 function deployment(item,title,description){return `<article class="deployment-card"><span class="eyebrow">${esc(title)}</span><strong>${item?.version?'v'+esc(item.version):item?'Versionskennung fehlt':'Keine Version'}</strong><p>${esc(description)}</p>${item?`<code title="${esc(item.digest)}">${esc(item.digest)}</code><small>${esc(item.image)}</small>`:''}</article>`;}
 function rollbackChoices(data){
  const values=Array.isArray(data.rollback_options)?data.rollback_options:(data.rollback?[data.rollback]:[]);
  return values.filter(item=>item&&typeof item.digest==='string'&&/^sha256:[a-f0-9]{64}$/.test(item.digest));
 }
 function panel(data,error='',offer={}){
  if(error)return `<section class="panel"><h2>Systemversionen</h2><div class="notice warning">${esc(error)}</div><button class="button small" data-action="refresh">Status erneut laden</button></section>`;
  const choices=rollbackChoices(data);
  const next=data.next_boot||data.staged||(data.rollback_queued?data.rollback:data.booted),pending=data.reboot_required;
  return `<section class="panel system-deployments"><div class="panel-heading"><h2>Systemversionen</h2><span class="pill ${pending?'purple':'gray'}">${data.reboot_scheduled?'Neustart geplant':pending?'Neustart erforderlich':'Aktuell aktiv'}</span></div><div class="update-action-bar"><button class="button" data-action="update-check">1 · Jetzt prüfen</button><button class="button primary" data-action="update-install" data-version="${esc(offer.latest||'')}" data-update-eligible="${Boolean(offer.eligible)}" data-update-available="${Boolean(offer.available)}" ${!offer.eligible||!offer.available||offer.busy||pending||data.reboot_scheduled?'disabled':''}>2 · Update installieren</button><button class="button ${pending?'primary':''}" data-action="system-reboot" ${!pending||data.reboot_scheduled?'disabled':''}>3 · Neu starten & aktivieren</button></div><div class="deployment-grid">${deployment(data.booted,'Jetzt gestartet','Diese Systemversion läuft gerade.')}${deployment(data.staged||(data.rollback_queued?data.rollback:null),'Beim nächsten Start',data.rollback_queued?'Die vorherige Version ist für den nächsten Start ausgewählt.':data.staged?'Das geprüfte Update ist vorbereitet.':'Aktuell kein Wechsel vorbereitet.')}${deployment(data.rollback,'Vorherige Version','Dateien und App-/VM-Daten werden beim Rollback nicht zurückgesetzt.')}</div>${pending?'<div class="notice warning">Der Versionswechsel erfolgt erst beim Neustart. Speichere offene Arbeiten und fahre laufende virtuelle Maschinen vorher herunter.</div>':''}<label class="field rollback-choice">Systemstand für Rollback<select id="rollback-version" ${!data.rollback_available||!choices.length||data.reboot_scheduled?'disabled':''}>${choices.length?choices.map(item=>`<option value="${esc(item.digest)}">${esc(item.version?'v'+item.version:'Vorheriger Stand')}${item.installed_at?' · '+esc(new Date(item.installed_at*1000).toLocaleString('de-DE')):''}${item.slot?' · Slot '+esc(item.slot):''}</option>`).join(''):'<option>Kein vorheriger Systemstand verfügbar</option>'}</select></label><div class="form-actions wrap"><button class="button" data-action="update-rollback" ${!data.rollback_available||!choices.length||data.reboot_scheduled?'disabled':''}>Ausgewählten Rollback vorbereiten</button><button class="button small" data-action="refresh">↻ Status aktualisieren</button></div>${data.rollback_reason?`<p class="hint">${esc(data.rollback_reason)}</p>`:''}<p class="hint">Rollback wechselt den Betriebssystemstand. Freigaben sowie App- und VM-Daten bleiben erhalten. Die aktuelle NAS-Konfiguration wird übernommen; Rollback ersetzt keine Datensicherung.</p><p class="hint" data-system-live-status role="status">Aktueller Systemstatus · wird bei geöffneter Seite regelmäßig aktualisiert.</p></section>`;
 }
 function progress(data){
  if(!data||data.status==='idle')return '';
  const phases={checking:'Update-Angebot und Signatur prüfen',backup:'NAS-Konfiguration sichern',download:'Systemimage herunterladen',verification:'Signatur und Systemimage prüfen',writing:'Inaktiven Systemslot schreiben',confirming:'Systemslot prüfen und Start vorbereiten',ready:'Bereit für den Neustart'};
  const titles={running:'Update läuft',completed:'Update vorbereitet',failed:'Update fehlgeschlagen',interrupted:'Update unterbrochen'};
  const measured=data.status==='running'&&data.phase==='download'&&Number.isFinite(data.received)&&data.total>0;
  const percent=measured?Math.min(100,Math.max(0,100*data.received/data.total)):null;
  return `<h2>${esc(titles[data.status]||'Systemupdate')}</h2><p><strong>${esc(phases[data.phase]||'Status wird ermittelt')}</strong> · ${esc(data.elapsed||0)} s</p>${measured?`<progress max="100" value="${percent}" aria-label="Systemimage herunterladen"></progress><p>${(data.received/1048576).toFixed(1)} / ${(data.total/1048576).toFixed(1)} MiB · ${Math.floor(percent)} %</p>`:''}${data.message?`<p class="notice warning">${esc(data.message)}</p>`:''}`;
 }
 let timer=null,disposed=true,pending=false,revision=0;
 function dispose(){disposed=true;revision++;if(timer!==null)clearInterval(timer);timer=null;}
 function mount(root,ctx){
  dispose();if(!root.querySelector('.system-deployments'))return;disposed=false;const mine=revision;const offerButton=root.querySelector('[data-action=update-install]');const offer={latest:offerButton?.dataset?.version,eligible:offerButton?.dataset?.updateEligible==='true',available:offerButton?.dataset?.updateAvailable==='true'};
  const refresh=async()=>{
   if(disposed||pending||document.hidden||document.querySelector('dialog[open]'))return;
   pending=true;
   try{const activity=await ctx.api('/api/updates/progress');if(disposed||mine!==revision)return;const activityNode=root.querySelector('#update-progress');if(activityNode){activityNode.innerHTML=progress(activity);activityNode.hidden=activity.status==='idle';}const data=await ctx.api('/api/updates/system');if(disposed||mine!==revision)return;const node=root.querySelector('.system-deployments');if(!node)return;const install=root.querySelector('[data-action=update-install]');if(install){install.hidden=false;install.disabled=Boolean(install.dataset?.updateEligible!=='true'||!offer.available||data.reboot_required||data.reboot_scheduled||activity.status==='running');}
    // Preserve the keyboard focus when the same controls remain available.
    const selected=node.querySelector?.('#rollback-version')?.value;
    const active=document.activeElement,selectFocused=active?.id==='rollback-version',action=node.contains(active)?active.dataset?.action:null;
    const holder=document.createElement('div');holder.innerHTML=panel(data,'',{...offer,busy:activity.status==='running'});node.replaceWith(holder.firstElementChild);
    const select=root.querySelector('#rollback-version');if(select&&Array.from(select.options).some(option=>option.value===selected))select.value=selected;if(selectFocused&&select&&!select.disabled)select.focus({preventScroll:true});
    if(action){const replacement=root.querySelector(`[data-action="${action}"]`);if(replacement&&!replacement.disabled)replacement.focus({preventScroll:true});}
   }catch(error){if(!disposed&&mine===revision){const status=root.querySelector('[data-system-live-status]');if(status)status.textContent='Status konnte nicht aktualisiert werden: '+error.message;}}
   finally{pending=false;}
  };
  refresh();timer=setInterval(refresh,3000);
 }
 window.TitanUpdates={panel,mount,dispose,rollbackChoices,progress};
})();
