/* Titan account management. The shared-folder editor preserves other accounts. */
(function(global){
 'use strict';
 let selectedName='';
 const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const active=user=>user.enabled!==false;
 const roleLabel=user=>user.role==='admin'?'Administrator':'Benutzer';
 const permission=(share,name)=>(share.writers||[]).includes(name)?'write':(share.readers||[]).includes(name)?'read':'none';
 const permissionLabel=value=>({write:'Lesen und Schreiben',read:'Nur Lesen',none:'Kein Zugriff'}[value]||'Kein Zugriff');
 function protectedAccount(user,users,currentName){return user.name===currentName||(user.role==='admin'&&active(user)&&users.filter(item=>item.role==='admin'&&active(item)).length===1);}
 function rowText(user){return [user.name,user.display_name,user.description,user.system_user].filter(Boolean).join(' ').toLocaleLowerCase('de-DE');}
 function matches(user,query='',role='',status=''){
  return (!query||rowText(user).includes(query.trim().toLocaleLowerCase('de-DE')))&&(!role||user.role===role)&&(!status||(status==='active'&&active(user))||(status==='blocked'&&!active(user)));
 }
 function avatar(user){return `<span class="um-avatar" aria-hidden="true">${escape((user.display_name||user.name).slice(0,1).toLocaleUpperCase('de-DE'))}</span>`;}
 function status(user){return `<span class="um-status ${active(user)?'is-active':'is-blocked'}">${active(user)?'Aktiv':'Gesperrt'}</span>`;}
 function detail(user,data,shares,currentName){
  if(!user)return '<div class="um-empty">Wähle einen Benutzer aus.</div>';
  const account=(data.system||[]).find(item=>item.name===user.system_user),legacy=user.system_user===data.service_user;
  const access=shares.filter(share=>permission(share,user.system_user)!=='none');
  return `<div class="um-detail-heading">${avatar(user)}<div><h2>${escape(user.display_name||user.name)}</h2><p>${escape(user.name)}${user.name===currentName?' · Du':''}</p></div></div>${status(user)}<dl class="um-info"><dt>Rolle</dt><dd>${roleLabel(user)}</dd><dt>SMB-Benutzername</dt><dd><code>${escape(user.system_user)}</code></dd><dt>SMB-Zugang</dt><dd>${legacy?'Eigenes SMB-Konto noch einrichten':!active(user)?'Konto gesperrt':account?.smb_ready===true?'Bereit':account?.smb_ready===false?'Nicht bereit':'Status nicht geprüft'}</dd>${user.description?`<dt>Beschreibung</dt><dd>${escape(user.description)}</dd>`:''}</dl><div class="um-detail-section"><h3>Freigaben</h3>${legacy?'<p class="hint">Dieses ältere Webkonto nutzt die App-Dienstidentität. Richte zuerst über Konto → Passwort ändern einen eigenen SMB-Zugang ein.</p>':access.length?`<ul class="um-access-list">${access.map(share=>`<li><strong>${escape(share.name)}</strong><span>${permissionLabel(permission(share,user.system_user))}</span></li>`).join('')}</ul>`:'<p class="hint">Kein Zugriff auf eingerichtete SMB-Freigaben.</p>'}${!active(user)&&access.length?'<p class="hint">Die gespeicherten Rechte greifen erst wieder, wenn das Konto aktiviert ist.</p>':''}</div><button type="button" class="button primary" data-action="user-edit" data-name="${escape(user.name)}">Konto und Freigaben bearbeiten</button>`;
 }
 function render(data,shares,options={}){
  const users=(data.web||[]),currentName=options.currentName||'';
  if(!users.some(user=>user.name===selectedName))selectedName=users[0]?.name||'';
  const selected=users.find(user=>user.name===selectedName),guarded=!selected||protectedAccount(selected,users,currentName);
  const others=(data.system||[]).filter(account=>!account.removed&&!users.some(user=>user.system_user===account.name)&&account.name!==data.service_user);
  return `<section class="um-manager panel" data-user-manager><div class="um-toolbar" aria-label="Benutzeraktionen"><div class="um-actions"><button type="button" class="button primary" data-action="user-create">+ Erstellen</button><button type="button" class="button" data-action="identity-manager">Gruppen und Rechte</button><button type="button" class="button" data-um-toolbar="edit" data-action="user-edit" data-name="${escape(selectedName)}" ${selected?'':'disabled'}>Bearbeiten</button><button type="button" class="button danger" data-um-toolbar="remove" data-action="user-remove" data-name="${escape(selectedName)}" ${guarded?'disabled title="Das eigene Konto und der letzte aktive Administrator sind geschützt."':''}>Löschen</button></div><button type="button" class="button um-refresh" data-action="refresh" aria-label="Benutzer aktualisieren">↻</button></div><div class="um-filters"><label class="um-search"><span class="sr-only">Benutzer suchen</span><input type="search" data-um-search placeholder="Benutzer suchen …" maxlength="200"></label><label><span class="sr-only">Nach Rolle filtern</span><select data-um-role aria-label="Nach Rolle filtern"><option value="">Alle Rollen</option><option value="admin">Administratoren</option><option value="user">Benutzer</option></select></label><label><span class="sr-only">Nach Status filtern</span><select data-um-status aria-label="Nach Status filtern"><option value="">Alle Status</option><option value="active">Aktiv</option><option value="blocked">Gesperrt</option></select></label></div><div class="um-body"><div class="um-list"><div class="um-table-wrap"><table class="um-table" aria-label="Benutzerkonten"><thead><tr><th>Benutzer</th><th>Rolle</th><th>Status</th><th>Beschreibung</th></tr></thead><tbody>${users.map(user=>`<tr data-um-row="${escape(user.name)}" class="${user.name===selectedName?'is-selected':''}"><td><button type="button" class="um-user" data-um-select="${escape(user.name)}" aria-pressed="${user.name===selectedName}">${avatar(user)}<span><strong>${escape(user.display_name||user.name)}</strong><small>${escape(user.name)}${user.name===currentName?' · Du':''}</small></span></button></td><td><span class="um-role">${roleLabel(user)}</span></td><td>${status(user)}</td><td class="um-description">${escape(user.description||'—')}</td></tr>`).join('')}</tbody></table></div><p class="um-empty" data-um-empty ${users.length?'hidden':''}>Keine passenden Benutzer gefunden.</p><div class="um-list-footer"><span data-um-count aria-live="polite">${users.length} Benutzer</span><span>Webanmeldung und SMB</span></div></div><aside class="um-detail" data-um-detail aria-label="Ausgewählter Benutzer">${detail(selected,data,shares,currentName)}</aside></div></section><p class="um-footnote">Mindestens ein aktiver Administrator muss erhalten bleiben. Die Titan-App-Dienstidentität hat keinen SMB-Login.</p>${others.length?`<details class="um-other panel"><summary>Weitere SMB-Konten (${others.length})</summary><p>${others.map(account=>escape(account.name)).join(', ')}</p><p class="hint">Diese Konten haben keinen Zugang zur Titan-Weboberfläche.</p></details>`:''}`;
 }
 function mount(root,data,shares,options={}){
  const manager=root?.querySelector('[data-user-manager]');if(!manager)return;
  const users=data.web||[],search=manager.querySelector('[data-um-search]'),role=manager.querySelector('[data-um-role]'),state=manager.querySelector('[data-um-status]');
  const select=name=>{
   const user=users.find(item=>item.name===name);if(!user)return;selectedName=user.name;
   for(const row of manager.querySelectorAll('[data-um-row]')){const selected=row.dataset.umRow===name;row.classList.toggle('is-selected',selected);row.querySelector('[data-um-select]')?.setAttribute('aria-pressed',String(selected));}
   manager.querySelector('[data-um-detail]').innerHTML=detail(user,data,shares,options.currentName||'');
   for(const control of manager.querySelectorAll('[data-um-toolbar]')){control.dataset.name=name;control.disabled=control.dataset.umToolbar==='remove'&&protectedAccount(user,users,options.currentName||'');}
  };
  const filter=()=>{
   let count=0,firstVisible='',selectedVisible=false;for(const row of manager.querySelectorAll('[data-um-row]')){const user=users.find(item=>item.name===row.dataset.umRow);row.hidden=!matches(user,search.value,role.value,state.value);if(!row.hidden){count++;firstVisible=firstVisible||user.name;if(user.name===selectedName)selectedVisible=true;}}
   manager.querySelector('[data-um-count]').textContent=`${count} von ${users.length} Benutzern`;manager.querySelector('[data-um-empty]').hidden=count>0;
   if(!selectedVisible){if(firstVisible)select(firstVisible);else{selectedName='';manager.querySelector('[data-um-detail]').innerHTML=detail(null,data,shares,options.currentName||'');for(const row of manager.querySelectorAll('[data-um-row]')){row.classList.remove('is-selected');row.querySelector('[data-um-select]')?.setAttribute('aria-pressed','false');}for(const control of manager.querySelectorAll('[data-um-toolbar]')){control.dataset.name='';control.disabled=true;}}}
  };
  search.addEventListener('input',filter);role.addEventListener('change',filter);state.addEventListener('change',filter);
  manager.addEventListener('click',event=>{const target=event.target.closest('[data-um-select]');if(target)select(target.dataset.umSelect);});
  manager.addEventListener('dblclick',event=>{const target=event.target.closest('[data-um-select]');if(target){select(target.dataset.umSelect);options.edit?.(target.dataset.umSelect);}});
 }
 function profileFields(user={},helpers={}){
  const field=helpers.field;
  return field('Anzeigename (optional)','display_name','text',user.display_name||'','maxlength="96" autocomplete="name"','Zum Beispiel Vor- und Nachname. Der Anmeldename bleibt gleich.')+`<div class="field"><label for="f-description">Beschreibung (optional)</label><textarea id="f-description" name="description" maxlength="256" rows="2" placeholder="Zum Beispiel Familie, Büro oder Gastzugang">${escape(user.description||'')}</textarea></div>`;
 }
 function editor(user,data,shares,options={}){
  const {field,selectField,formEnd}=options,own=user.name===options.currentName,legacy=user.system_user===data.service_user;
  const lastAdmin=user.role==='admin'&&active(user)&&(data.web||[]).filter(item=>item.role==='admin'&&active(item)).length===1;
  return `<div class="um-editor" data-um-editor><div class="um-editor-identity">${avatar(user)}<div><strong>${escape(user.display_name||user.name)}</strong><span>Anmeldung: ${escape(user.name)}</span></div></div><div class="um-tabs" role="tablist" aria-label="Benutzereinstellungen"><button type="button" role="tab" id="um-tab-account" aria-controls="um-panel-account" aria-selected="true" data-um-tab="account">Konto</button><button type="button" role="tab" id="um-tab-shares" aria-controls="um-panel-shares" aria-selected="false" tabindex="-1" data-um-tab="shares">Freigaben</button><button type="button" role="tab" id="um-tab-rights" aria-controls="um-panel-rights" aria-selected="false" tabindex="-1" data-um-tab="rights">Rechte und Ordner</button></div><section role="tabpanel" id="um-panel-account" aria-labelledby="um-tab-account" data-um-panel="account"><form>${profileFields(user,options)}<div class="um-account-grid">${selectField('Rolle','role',[['user','Benutzer · eigene Dateien'],['admin','Administrator · Verwaltung']],user.role)}${selectField('Kontostatus','enabled',[['true','Aktiv'],['false','Gesperrt']],String(active(user)))}</div>${field('Neues Passwort (optional)','password','password','','minlength="12" maxlength="256" autocomplete="new-password"','Leer lassen, um das bisherige Passwort zu behalten.')}${own?'<p class="notice">Du kannst dein eigenes Konto nicht sperren. Dein Passwort änderst du unter Konto → Passwort ändern.</p>':''}${lastAdmin?'<p class="notice">Dieses Konto ist der letzte aktive Administrator. Rolle und Aktivierung müssen erhalten bleiben.</p>':''}<p class="hint">${legacy?'Das App-Dienstkonto erhält kein SMB-Passwort. Ein persönliches SMB-Konto richtest du unter Konto → Passwort ändern ein.':'Das Passwort gilt für Webanmeldung und SMB. Eine Sperre beendet Websitzungen und verhindert neue SMB-Anmeldungen.'}</p>${formEnd('Konto speichern')}</section><section role="tabpanel" id="um-panel-shares" aria-labelledby="um-tab-shares" data-um-panel="shares" hidden><p class="hint">Wähle die Rechte dieses Benutzers für jede Freigabe. Lesen und Schreiben enthält beide Zugriffe. Andere Konten behalten ihre Rechte.</p>${legacy?'<p class="notice warning">Dieses ältere Konto besitzt noch keinen eigenen SMB-Benutzernamen. Richte zuerst unter Konto → Passwort ändern einen persönlichen SMB-Zugang ein. Die Rechte der App-Dienstidentität werden hier nicht verändert.</p>':shares.length?`<form data-um-shares-form><div class="um-permissions">${shares.map(share=>`<label class="um-permission"><span><strong>${escape(share.name)}</strong><small>${escape(share.path||'')}</small></span><select name="share-${escape(share.name)}" data-um-permission="${escape(share.name)}" aria-label="Zugriff auf ${escape(share.name)}"><option value="none" ${permission(share,user.system_user)==='none'?'selected':''}>Kein Zugriff</option><option value="read" ${permission(share,user.system_user)==='read'?'selected':''}>Nur Lesen</option><option value="write" ${permission(share,user.system_user)==='write'?'selected':''}>Lesen und Schreiben</option></select></label>`).join('')}</div>${!active(user)?'<p class="notice">Das Konto ist gesperrt. Vorhandene Rechte bleiben gespeichert; neue oder höhere Rechte benötigen ein aktives Konto.</p>':''}<p class="form-error" data-um-shares-error role="alert" hidden></p><p class="hint" data-um-shares-status role="status" aria-live="polite"></p>${formEnd('Freigaben speichern')}`:'<p class="um-empty">Es sind noch keine SMB-Freigaben eingerichtet. Du kannst sie in der Systemsteuerung unter Freigaben anlegen.</p>'}</section><section role="tabpanel" id="um-panel-rights" aria-labelledby="um-tab-rights" data-um-panel="rights" hidden><p data-um-identity-loading>Gruppenrechte werden geladen …</p></section></div>`;
 }
 function accountChanges(user,users,currentName,form){
  const changes={name:user.name,display_name:String(form.get('display_name')||''),description:String(form.get('description')||'')};
  const desiredRole=form.get('role'),desiredEnabled=form.get('enabled')==='true';
  if(user.name===currentName&&!desiredEnabled)throw new Error('Du kannst dein eigenes Konto nicht sperren.');
  if(user.role==='admin'&&active(user)&&users.filter(item=>item.role==='admin'&&active(item)).length===1&&(!desiredEnabled||desiredRole!=='admin'))throw new Error('Lege zuerst einen weiteren aktiven Administrator an.');
  if(desiredRole!==user.role)changes.role=desiredRole;
  if(desiredEnabled!==active(user))changes.enabled=desiredEnabled;
  if(changes.display_name.length>96||changes.description.length>256)throw new Error('Anzeigename oder Beschreibung ist zu lang.');
  if(form.get('password'))changes.password=form.get('password');return changes;
 }
 function permissionUpdate(share,name,value){
  if(!['none','read','write'].includes(value))throw new Error('Ungültige Freigabenberechtigung.');
  return {name:share.name,readers:[...new Set((share.readers||[]).filter(item=>item!==name).concat(value==='read'?[name]:[]))],writers:[...new Set((share.writers||[]).filter(item=>item!==name).concat(value==='write'?[name]:[]))]};
 }
 async function waitJob(api,id,options={}){
  if(typeof id!=='string'||!id)throw new Error('Die Änderung wurde nicht als Auftrag bestätigt.');
  const pause=options.pause||(ms=>new Promise(resolve=>setTimeout(resolve,ms))),attempts=options.attempts||90;
  for(let i=0;i<attempts;i++){
   const jobs=await api('/api/jobs'),job=jobs.find(item=>item.id===id);
   if(job?.status==='completed')return job;
   if(job?.status==='failed')throw new Error(job.result?.error||'Die Freigabenrechte konnten nicht gespeichert werden.');
   await pause(1000);
  }
  throw new Error('Die Änderung läuft länger als erwartet. Den Status findest du unter Aktivität; bitte vor einem erneuten Speichern prüfen.');
 }
 async function savePermissions(user,initial,values,context){
  if(user.system_user===context.serviceUser)throw new Error('Dieses Konto benötigt zuerst einen persönlichen SMB-Zugang.');
  const changes=initial.filter(share=>values.has(share.name)&&values.get(share.name)!==permission(share,user.system_user));let done=0;
  for(const previous of changes){
   const latest=await context.api('/api/managed-shares'),share=latest.find(item=>item.name===previous.name);
   if(!share)throw new Error(`Die Freigabe ${previous.name} ist nicht mehr verfügbar.`);
   const value=values.get(share.name);if(!['none','read','write'].includes(value))throw new Error('Ungültige Freigabenberechtigung.');
   if(permission(share,user.system_user)===value){previous.readers=[...(share.readers||[])];previous.writers=[...(share.writers||[])];done++;continue;}
   context.progress?.(`${done+1} von ${changes.length} Freigaben wird gespeichert: ${share.name}`);
   const result=await context.api('/api/actions',{operation:'share_user_permission',arguments:{name:share.name,user:user.system_user,permission:value}});
   context.onJob?.(result.job);await waitJob(context.api,result.job,context.waitOptions);done++;
   previous.readers=permissionUpdate(share,user.system_user,value).readers;previous.writers=permissionUpdate(share,user.system_user,value).writers;
  }
  return done;
 }
 function mountEditor(root,user,data,shares,options={}){
  const editor=root?.querySelector('[data-um-editor]');if(!editor)return;
  const tabs=[...editor.querySelectorAll('[data-um-tab]')];
  const openTab=tab=>{for(const item of tabs){const selected=item===tab;item.setAttribute('aria-selected',String(selected));item.tabIndex=selected?0:-1;}for(const panel of editor.querySelectorAll('[data-um-panel]'))panel.hidden=panel.dataset.umPanel!==tab.dataset.umTab;};
  for(const tab of tabs){tab.addEventListener('click',()=>openTab(tab));tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const index=tabs.indexOf(tab),next=event.key==='Home'?tabs[0]:event.key==='End'?tabs.at(-1):tabs[(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];openTab(next);next.focus();});}
  const identityPanel=editor.querySelector('[data-um-panel="rights"]');
  if(identityPanel&&global.TitanIdentity&&options.api){options.api('/api/identity').then(identity=>{identityPanel.innerHTML=global.TitanIdentity.userPanel(user,identity);global.TitanIdentity.mountUser(identityPanel,user,identity,options);}).catch(failure=>{identityPanel.textContent=failure.message;});}
  const form=editor.querySelector('[data-um-shares-form]');if(!form)return;
  form.addEventListener('submit',async event=>{
   event.preventDefault();const submit=form.querySelector('[type=submit]'),error=form.querySelector('[data-um-shares-error]'),status=form.querySelector('[data-um-shares-status]');error.hidden=true;submit.disabled=true;
   const controls=[...form.querySelectorAll('select')],values=new Map(controls.map(control=>[control.dataset.umPermission,control.value]));controls.forEach(control=>control.disabled=true);
   try{const count=await savePermissions(user,shares,values,{...options,serviceUser:data.service_user,progress:message=>status.textContent=message});status.textContent=count?'Freigabenrechte gespeichert.':'Keine Änderungen an den Freigabenrechten.';options.toast?.(status.textContent);options.refresh?.();}
   catch(failure){error.textContent=failure.message;error.hidden=false;status.textContent='Erfolgreich gespeicherte Änderungen bleiben erhalten. Prüfe den Fehler, bevor du die offenen Änderungen erneut speicherst.';}
   finally{submit.disabled=false;controls.forEach(control=>control.disabled=false);}
  });
 }
 global.TitanUsers={render,mount,profileFields,editor,mountEditor,accountChanges,permission,permissionUpdate,savePermissions,matches,protectedAccount};
})(window);
