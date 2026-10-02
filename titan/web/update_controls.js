'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 function deployment(item,title,description){return `<article class="deployment-card"><span class="eyebrow">${esc(title)}</span><strong>${item?.version?'v'+esc(item.version):item?'Versionskennung fehlt':'Keine Version'}</strong><p>${esc(description)}</p>${item?`<code title="${esc(item.digest)}">${esc(item.digest)}</code><small>${esc(item.image)}</small>`:''}</article>`;}
 function rollbackChoices(data){
  const values=Array.isArray(data.rollback_options)?data.rollback_options:(data.rollback?[data.rollback]:[]);
  return values.filter(item=>item&&typeof item.digest==='string'&&/^sha256:[a-f0-9]{64}$/.test(item.digest));
 }
 function panel(data,error=''){
  if(error)return `<section class="panel"><h2>Systemversionen</h2><div class="notice warning">${esc(error)}</div><button class="button small" data-action="refresh">Status erneut laden</button></section>`;
  const choices=rollbackChoices(data);
  const next=data.next_boot||data.staged||(data.rollback_queued?data.rollback:data.booted),pending=data.reboot_required;
  return `<section class="panel system-deployments"><div class="panel-heading"><h2>Systemversionen</h2><span class="pill ${pending?'purple':'gray'}">${data.reboot_scheduled?'Neustart geplant':pending?'Neustart erforderlich':'Aktuell aktiv'}</span></div><div class="deployment-grid">${deployment(data.booted,'Jetzt gestartet','Diese Systemversion läuft gerade.')}${deployment(data.staged||(data.rollback_queued?data.rollback:null),'Beim nächsten Start',data.rollback_queued?'Die vorherige Version ist für den nächsten Start ausgewählt.':data.staged?'Das geprüfte Update ist vorbereitet.':'Aktuell kein Wechsel vorbereitet.')}${deployment(data.rollback,'Vorherige Version','Dateien und App-/VM-Daten werden beim Rollback nicht zurückgesetzt.')}</div>${pending?'<div class="notice warning">Der Versionswechsel erfolgt erst beim Neustart. Speichere offene Arbeiten und fahre laufende virtuelle Maschinen vorher herunter.</div>':''}<label class="field rollback-choice">Systemstand für Rollback<select id="rollback-version" ${!data.rollback_available||!choices.length||data.reboot_scheduled?'disabled':''}>${choices.length?choices.map(item=>`<option value="${esc(item.digest)}">${esc(item.version?'v'+item.version:'Vorheriger Stand')}${item.installed_at?' · '+esc(new Date(item.installed_at*1000).toLocaleString('de-DE')):''}${item.slot?' · Slot '+esc(item.slot):''}</option>`).join(''):'<option>Kein vorheriger Systemstand verfügbar</option>'}</select></label><div class="form-actions wrap"><button class="button" data-action="update-rollback" ${!data.rollback_available||data.reboot_scheduled?'disabled':''}>Ausgewählten Rollback vorbereiten</button><button class="button ${pending?'primary':''}" data-action="system-reboot" ${!next||data.reboot_scheduled?'disabled':''}>${pending?'Neu starten und aktivieren':'NAS neu starten'}</button><button class="button small" data-action="refresh">↻ Status aktualisieren</button></div>${data.rollback_reason?`<p class="hint">${esc(data.rollback_reason)}</p>`:''}<p class="hint">Rollback wechselt den Betriebssystemstand. Freigaben sowie App- und VM-Daten bleiben erhalten. Die aktuelle NAS-Konfiguration wird übernommen; Rollback ersetzt keine Datensicherung.</p><p class="hint" data-system-live-status role="status">Aktueller Systemstatus · wird bei geöffneter Seite regelmäßig aktualisiert.</p></section>`;
 }
 let timer=null,disposed=true,pending=false,revision=0;
 function dispose(){disposed=true;revision++;if(timer!==null)clearInterval(timer);timer=null;}
 function mount(root,ctx){
  dispose();if(!root.querySelector('.system-deployments'))return;disposed=false;const mine=revision;
  const refresh=async()=>{
   if(disposed||pending||document.hidden||document.querySelector('dialog[open]'))return;
   pending=true;
   try{const data=await ctx.api('/api/updates/system');if(disposed||mine!==revision)return;const node=root.querySelector('.system-deployments');if(!node)return;
    // Preserve the keyboard focus when the same controls remain available.
    const selected=node.querySelector?.('#rollback-version')?.value;
    const active=document.activeElement,selectFocused=active?.id==='rollback-version',action=node.contains(active)?active.dataset?.action:null;
    const holder=document.createElement('div');holder.innerHTML=panel(data);node.replaceWith(holder.firstElementChild);
    const select=root.querySelector('#rollback-version');if(select&&Array.from(select.options).some(option=>option.value===selected))select.value=selected;if(selectFocused&&select&&!select.disabled)select.focus({preventScroll:true});
    if(action){const replacement=root.querySelector(`[data-action="${action}"]`);if(replacement&&!replacement.disabled)replacement.focus({preventScroll:true});}
   }catch(error){if(!disposed&&mine===revision){const status=root.querySelector('[data-system-live-status]');if(status)status.textContent='Status konnte nicht aktualisiert werden: '+error.message;}}
   finally{pending=false;}
  };
  timer=setInterval(refresh,5000);
 }
 window.TitanUpdates={panel,mount,dispose,rollbackChoices};
})();
