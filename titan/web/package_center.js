'use strict';
(function(root){
 let controller=null;
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const states={running:'Läuft',created:'Vorbereitet',exited:'Gestoppt',missing:'Fehlt',paused:'Pausiert',restarting:'Startet neu',healthy:'Bereit',unhealthy:'Fehler',starting:'Startet',ready:'Alle Dienste bereit',stopped:'Paket gestoppt',degraded:'Anwendung läuft · Zusatzdienst prüfen',attention:'Prüfung erforderlich',blocked:'Aktion erforderlich'};
 function serviceRows(services){return `<div class="package-services">${services.map(service=>`<div class="package-service ${service.ready?'is-ready':'needs-attention'}"><span class="package-service-dot" aria-hidden="true"></span><div><strong>${esc(service.name)}</strong><small>${esc(service.one_shot?'Einmalige Einrichtung':service.image)}</small>${service.warning?`<small class="error-text">${esc(service.warning)}</small>`:''}${service.depends_on?.length?`<small>Benötigt ${service.depends_on.map(key=>esc(services.find(row=>row.id===key)?.name||key)).join(', ')}</small>`:''}</div><span class="package-state">${esc(service.one_shot&&service.ready?'Abgeschlossen':states[service.health||service.state]||service.state)}</span></div>`).join('')}</div>`;}
 function render(data,details,tab='overview'){
  const app=data.app||{},running=data.running_services>0,services=data.services||[],editable=(data.settings||[]).filter(row=>row.editable),connection=root?.TitanNetworks?.connection(details?.container||app);
  const navigation=`<nav class="manager-tabs" aria-label="Paketbereiche">${[['overview','Übersicht'],['settings','Einstellungen'],['logs','Protokolle']].map(([id,name])=>`<button type="button" class="button ${tab===id?'primary':''}" data-package-tab="${id}" aria-pressed="${tab===id}">${name}</button>`).join('')}</nav>`;
  let content='';
  if(tab==='overview')content=`<section class="package-summary"><strong>${esc(states[data.phase]||data.phase)}</strong><span>${services.filter(row=>row.ready).length} / ${services.length} Dienste bereit</span></section>${(data.warnings||[]).map(message=>`<div class="notice warning">${esc(message)}</div>`).join('')}${serviceRows(services)}<div class="form-actions wrap">${connection&&(data.primary_state?data.primary_state==='running':(app.state==='running'||details?.container?.state==='running'||running))?`<a class="button primary" href="${esc(connection)}" target="_blank" rel="noopener">App öffnen ↗</a>`:''}<button class="button" type="button" data-package-command="start" ${running&&data.ready?'disabled':''}>Starten</button><button class="button" type="button" data-package-command="stop" ${running?'':'disabled'}>Stoppen</button><button class="button" type="button" data-package-command="restart" ${running?'':'disabled'}>Neustarten</button><button class="button" type="button" data-package-command="repair">Reparieren</button><button class="button" type="button" data-package-command="diagnose">Diagnose</button></div><section class="package-login"><h3>Zugang zur Anwendung</h3>${data.login?.username?`<p>Benutzername: <strong>${esc(data.login.username)}</strong></p>`:''}<p>${esc(data.login?.instructions||'')}</p>${data.login?.password_selected?'<p class="hint">Verwende das bei der Installation gewählte Passwort. Spätere Änderungen erfolgen in der Anwendung.</p>':''}</section><section class="package-update"><h3>Paketaktualisierung</h3><p>${data.update?.policy==='installed-store-recipe'?'Die bei der Installation gespeicherte BigBear-Vorlage bleibt unverändert.':data.update?.available?'Eine neuere, mit Titan freigegebene Paketvorlage ist verfügbar.':'Die mit dieser Titan-Version freigegebene Paketvorlage ist eingerichtet.'}</p><p class="hint">${esc(data.update?.message||'')}</p><div class="form-actions wrap"><button class="button" data-package-command="backup">Konfiguration & Datenbank sichern</button><button class="button ${data.update?.available?'primary':''}" data-package-command="update">${data.update?.policy==='installed-store-recipe'?'Images erneut laden':'Paket aktualisieren'}</button><button class="button danger" data-package-command="remove">Deinstallieren</button></div></section><div class="package-diagnosis" role="status"></div>`;
  if(tab==='settings')content=`<p class="notice">Zum Ändern das gesamte Paket stoppen. Konten und Passwörter werden direkt in der Anwendung verwaltet. Gespeicherte Daten bleiben erhalten.</p><form data-package-settings><div class="form-grid"><label class="field">Port der Weboberfläche<input name="port" type="number" min="1024" max="65535" required value="${Number(data.port)||8080}"></label>${editable.map(row=>row.choices?.length?`<label class="field">${esc(row.label)}<select name="${esc(row.key)}" required>${row.choices.map(([value,label])=>`<option value="${esc(value)}" ${value===row.value?'selected':''}>${esc(label)}</option>`).join('')}</select></label>`:`<label class="field">${esc(row.label)}<input name="${esc(row.key)}" type="${row.type==='number'?'number':'text'}" value="${esc(row.value)}" ${row.type==='number'?`min="${Number(row.min)||1}" max="${Number(row.max)||65535}"`:'maxlength="253"'} required></label>`).join('')}</div><p class="hint">Speicherbereich: <strong>${esc(data.storage_label||data.storage?.label||(data.storage_id==='system'?'Interner Speicher':data.storage_id?.replace(/^(volume|pool):/,''))||'Bisheriger Speicher')}</strong></p><details><summary>Technischer Datenpfad</summary><p class="hint"><code>${esc(data.data_path)}</code></p></details><button class="button primary" type="submit" ${running?'disabled':''}>Einstellungen speichern</button></form>`;
  if(tab==='logs')content=`<label class="field">Dienst<select data-package-log-service>${services.map(service=>`<option value="${esc(service.id)}">${esc(service.name)}</option>`).join('')}</select></label><button class="button" data-package-command="logs">Protokoll laden</button><pre class="code package-log" data-package-log tabindex="0">Dienst auswählen und Protokoll laden.</pre>`;
  return `<section class="package-center" data-package-id="${esc(app.id)}">${navigation}<div class="package-operation" role="status" data-package-progress hidden></div>${content}<p class="form-error" data-package-error role="alert" hidden></p><button class="button small" data-package-command="refresh">↻ Status aktualisieren</button></section>`;
 }
 async function open(app,context,tab='overview'){
  const {api,action,dialog,askYesNo}=context;
  controller?.abort();controller=new AbortController();const requestController=controller,signal=controller.signal;
  const [data,details]=await Promise.all([api('/api/package-details?'+new URLSearchParams({app})),api('/api/app-details?'+new URLSearchParams({app,tail:'1'})).catch(()=>null)]);
  if(signal.aborted)return;
  if(!data.installed)throw Error('Das Paket ist noch nicht installiert.');
  controller=null;
  if(dialog((data.app.name||app)+' · Paketzentrum',render(data,details,tab))===false){requestController.abort();return;}
  controller=requestController;
  const body=root.document.getElementById('dialog-body'),modal=root.document.getElementById('dialog');
  const error=message=>{if(signal.aborted)return;const node=body.querySelector('[data-package-error]');if(node){node.textContent=message;node.hidden=false;}};
  let busy=false;
  const progress=job=>{if(signal.aborted)return;const node=body.querySelector('[data-package-progress]');if(node){node.hidden=false;node.classList.toggle('is-error',job.status==='failed');node.textContent=job.result?.error||job.result?.message||(job.status==='queued'?'Aktion wartet …':job.status==='running'?'Aktion wird ausgeführt …':'Aktion abgeschlossen.');}};
  const execute=async(command,args)=>{
   if(busy)return;busy=true;const controls=[...body.querySelectorAll('[data-package-command],[data-package-tab],[type=submit]')].map(node=>({node,disabled:node.disabled}));controls.forEach(({node})=>node.disabled=true);progress({status:'queued'});
   try{
    const operation=command==='repair'?'package_repair':command==='update'?'package_update':command==='settings'?'package_settings':'app_action';
    const result=await action(operation,command==='settings'?{app,...args}:['repair','update'].includes(command)?{app}:{app,action:command},{wait:true,onProgress:progress});
    if(signal.aborted)return result;
    if(command==='remove'){modal.close();return result;}
    const pane=await open(app,context,tab);pane?.progress({status:'completed',result:{message:result?.message||'Aktion erfolgreich abgeschlossen.'}});return result;
   }catch(exc){error(exc.message);progress({status:'failed',result:{error:exc.message}});throw exc;}
   finally{busy=false;if(!signal.aborted)controls.forEach(({node,disabled})=>node.disabled=disabled);}
  };
  const confirmation={remove:'Dieses App-Paket stoppen und deinstallieren? Konfiguration, Datenbank und Nutzdaten bleiben erhalten.',update:'Das gesamte Paket aktualisieren? Titan sichert vorher Konfiguration und interne Datenbanken. Die Anwendung wird kurz unterbrochen. Fotos und Dokumente im Nutzdatenordner separat sichern.',stop:'Das gesamte App-Paket und seine Dienste stoppen?',restart:'Das gesamte App-Paket neu starten?'};
  body.addEventListener('click',async event=>{
   const target=event.target.closest?.('[data-package-command],[data-package-tab]');if(!target||!body.contains(target)||target.disabled||busy)return;event.preventDefault();
   target.disabled=true;try{
    if(target.dataset.packageTab){await open(app,context,target.dataset.packageTab);return;}
    const command=target.dataset.packageCommand;
    if(command==='refresh'){await open(app,context,tab);return;}
    if(command==='diagnose'){const diagnosis=await api('/api/package-diagnose?'+new URLSearchParams({app}));if(signal.aborted)return;const node=body.querySelector('.package-diagnosis');if(node)node.innerHTML=`<h3>Diagnose</h3>${diagnosis.checks.map(check=>`<p class="${check.ok?'':'error-text'}">${check.ok?'✓':'!'} ${esc(check.name)} · ${esc(states[check.message]||check.message)}</p>`).join('')}<p class="hint">${esc(diagnosis.message)}</p>`;return;}
    if(command==='logs'){const service=body.querySelector('[data-package-log-service]')?.value;if(!service)throw Error('Kein Paketdienst verfügbar.');const result=await api('/api/package-logs?'+new URLSearchParams({app,service,tail:'150'}));if(!signal.aborted)body.querySelector('[data-package-log]').textContent=result.logs;return;}
    if(confirmation[command]){
     // askYesNo replaces the shared dialog and disposes this listener. Restore
     // a live pane first; an accepted action runs only on that new controller.
     const confirmed=await askYesNo(confirmation[command]);const pane=await open(app,context,tab);
     if(confirmed)await pane?.execute(command);return;
    }
    await execute(command);
   }catch(exc){if(!signal.aborted)error(exc.message);}
   finally{target.disabled=false;}
  },{signal});
  body.querySelector('[data-package-settings]')?.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;const form=event.target;try{const values=new FormData(form),options={};for(const row of data.settings||[])if(row.editable)options[row.key]=row.type==='number'?Number(values.get(row.key)):values.get(row.key);await execute('settings',{port:Number(values.get('port')),options});}catch(exc){error(exc.message);}},{signal});
  modal.addEventListener('close',()=>requestController.abort(),{signal,once:true});
  return {execute,progress,signal};
 }
 function dispose(){controller?.abort();controller=null;}
 const api={open,render,serviceRows,dispose};if(root)root.TitanPackageCenter=api;if(typeof module==='object')module.exports=api;
})(typeof window==='undefined'?null:window);
