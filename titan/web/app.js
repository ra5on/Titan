'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const bytes = value => { const n = Number(value); if (!n) return '0 B'; const units = ['B','KB','MB','GB','TB']; const i = Math.min(4, Math.floor(Math.log(n) / Math.log(1024))); return `${(n / 1024 ** i).toLocaleString('de-DE', {maximumFractionDigits: i > 2 ? 2 : 0})} ${units[i]}`; };
const date = value => new Date(Number(value) * 1000).toLocaleString('de-DE', {dateStyle:'short',timeStyle:'short'});
const icons = {
 control:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 9v12M6 6h.01M10 6h.01"/>',
 dashboard:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
 docker:'<rect x="3" y="9" width="18" height="11" rx="2"/><path d="M7 9V5h4v4m2 0V5h4v4M3 14h18m-13 0v6m8-6v6"/>',
 apps:'<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M8 12h8M12 8v8"/>',
 storage:'<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 17.5h.01M12 7.5h5M12 17.5h5"/>',
 files:'<path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 shares:'<circle cx="6" cy="12" r="3"/><circle cx="18" cy="5" r="3"/><circle cx="18" cy="19" r="3"/><path d="m9 10 6-4M9 14l6 4"/>',
 vms:'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4m-5-12 3 3 3-3"/>',
 users:'<circle cx="9" cy="8" r="4"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M17 4a4 4 0 0 1 0 8M22 21v-2a7 7 0 0 0-4-6"/>',
 updates:'<path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5M4 16a8 8 0 0 0 14 3l3-3m0 5v-5h-5"/>',
 backups:'<path d="M3 7h18v14H3zM3 7l3-4h12l3 4M8 12h8M12 12v5"/>',
 monitoring:'<path d="M3 12h4l3-7 4 14 3-7h4"/>',
 services:'<path d="M4 5h16M4 12h16M4 19h16"/><circle cx="8" cy="5" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="19" r="2"/>',
 terminal:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/>',
 jobs:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m8 8 1 1 2-2M13 8h3m-8 5 1 1 2-2m2 1h3M8 18h8"/>',
 logs:'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
 settings:'<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.files}</svg>`;
const nav = [['dashboard','Hauptmenü'],['control','Verwaltung'],['apps','App Store'],['docker','Docker'],['storage','Speicher'],['files','Dateimanager'],['shares','Freigaben'],['vms','Virtuelle Maschinen'],['services','Dienste'],['terminal','Terminal'],['users','Benutzer'],['backups','Backups'],['monitoring','Meldungen'],['updates','Updates'],['jobs','Aufträge'],['logs','Protokoll'],['settings','Einstellungen']];
let session, page = 'dashboard', generation = 0, currentShare = '', currentPath = '', catalogData = [], usersData = [], managedShares = [], vmsData = [], backupData = [], jobsData = [], fileOffset = 0, fileSearch = '', watched = new Set(), polling, activeUpload = null;
let filesView = null, servicesData = null;
let dashboardClockTimer = null;
function dashboardClockParts(now = new Date()) {
 return {time:now.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'}),day:now.toLocaleDateString('de-DE',{weekday:'long',day:'numeric',month:'long'})};
}
function dashboardDateCard() {
 const clock = dashboardClockParts();
 return `<div class="date-card"><strong id="dashboard-time">${esc(clock.time)}</strong><span id="dashboard-date">${esc(clock.day)}</span></div>`;
}
function stopDashboardClock() {
 if (dashboardClockTimer !== null) clearInterval(dashboardClockTimer);
 dashboardClockTimer = null;
}
function updateDashboardClock() {
 if (page !== 'dashboard' || !session?.user || document.hidden) return false;
 const time = $('#dashboard-time'), day = $('#dashboard-date');
 if (!time || !day) return false;
 const clock = dashboardClockParts();
 if (time.textContent !== clock.time) time.textContent = clock.time;
 if (day.textContent !== clock.day) day.textContent = clock.day;
 return true;
}
function syncDashboardClock() {
 stopDashboardClock();
 if (updateDashboardClock()) dashboardClockTimer = setInterval(updateDashboardClock,1000);
}

async function api(path, body) {
 const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: body ? {'Content-Type':'application/json','X-CSRF-Token':(path === '/api/setup' ? session?.setup_csrf : session?.user?.csrf) || ''} : {}, body:body ? JSON.stringify(body) : undefined});
 const data = await response.json();
 if (!response.ok) { if (response.status === 401 && session?.user && path !== '/api/login') { session.user = null; renderAuth(false); } const error = new Error(data.error || 'Anfrage fehlgeschlagen.'); error.status = response.status; throw error; }
 return data;
}
function toast(message, error = false) {
 const item = document.createElement('div'); item.className = 'toast' + (error ? ' error' : ''); item.textContent = message; $('#toasts').append(item); setTimeout(() => item.remove(), 6500);
}
function heading(title, subtitle, actions = '', eyebrow = 'DEIN PERSÖNLICHES NAS') {
 return `<div class="page-heading"><div><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p class="subtitle">${esc(subtitle)}</p></div>${actions}</div>`;
}
const button = (text, action, attributes = '', kind = '') => `<button type="button" class="button ${kind}" data-action="${action}" ${attributes}>${text}</button>`;
const empty = (text, symbol = '◇') => `<div class="empty"><span class="empty-icon">${symbol}</span>${esc(text)}</div>`;
const field = (label, name, type = 'text', value = '', attributes = '', hint = '') => `<div class="field"><label for="f-${name}">${esc(label)}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${attributes}>${hint ? `<small>${esc(hint)}</small>`:''}</div>`;
const selectField = (label, name, options, value = '') => `<div class="field"><label for="f-${name}">${esc(label)}</label><select id="f-${name}" name="${name}">${options.map(([key,text]) => `<option value="${esc(key)}" ${String(key) === String(value) ? 'selected':''}>${esc(text)}</option>`).join('')}</select></div>`;
const releaseLabels={alpha:'Alpha',beta:'Beta',stable:'Stable'};
const releaseRank={stable:0,beta:1,alpha:2};
const releaseLabel=stage=>releaseLabels[stage]||'Unbekannt';
const channelNotice=channel=>channel==='alpha'?'Alpha erlaubt Alpha-, Beta- und Stable-Releases. Alpha ist die früheste Entwicklungsphase; Funktionen können fehlen und Fehler oder Datenverlust auftreten. Nur mit Testdaten verwenden.':channel==='beta'?'Beta erlaubt Beta- und Stable-Releases. Beta dient der Erprobung vor der stabilen Freigabe und kann weiterhin Fehler enthalten.':'Stable erlaubt ausschließlich stabile Freigaben. Frühe Alpha- und Beta-Releases werden ausgeschlossen.';
const actionNames={service_create:'Dienst anlegen',service_action:'Dienst verwalten',component_install:'Systemkomponenten einrichten',volume_create:'Volume einrichten',volume_mount:'Volume einhängen',account_create:'Benutzer anlegen',account_update:'Benutzer ändern',user_update:'Benutzer ändern',user_remove:'Benutzer löschen',password_change:'Passwort ändern',share_create:'Freigabe erstellen',share_update:'Freigabenrechte ändern',share_remove:'Freigabe entfernen',pool_create:'Pool erstellen',dataset_create:'Dataset erstellen',snapshot_create:'Snapshot erstellen',scrub:'Pool prüfen',app_install:'App installieren',app_action:'App verwalten',vm_create:'VM erstellen',vm_media:'Installationsmedium ändern',iso_remove:'ISO entfernen',vm_update:'VM bearbeiten',vm_remove:'VM entfernen',vm_action:'VM verwalten',vm_backup:'VM sichern',vm_restore:'VM wiederherstellen',backup_create:'Datensicherung',backup_verify:'Sicherung prüfen',backup_restore:'Dateien wiederherstellen',backup_config_export:'Konfiguration exportieren',backup_config_restore:'Konfiguration wiederherstellen',monitoring_check:'System prüfen',system_updates:'Systemimage-Status prüfen',update_check:'Titan-Updates prüfen',update_install:'Titan aktualisieren',update_rollback:'Vorherige Systemversion vorbereiten',system_reboot:'NAS neu starten',app_network_create:'Docker-Netz anlegen',app_network_remove:'Docker-Netz entfernen',system_disk_grow:'Systemdisk erweitern'};
const pill = (text, style = '') => `<span class="pill ${style}">${esc(text)}</span>`;
let dialogReturnFocus=null;
let fileDialogRequest=0;
function dialog(title, html, submit) {
 if($('#dialog').open&&window.TitanFileEditor?.canCloseWithin($('#dialog-body'))===false)return false;
 fileDialogRequest++;
 if(!$('#dialog').open){const opener=document.activeElement;dialogReturnFocus=opener?{element:opener,service:opener.dataset?.service,serviceAction:opener.dataset?.serviceAction,action:opener.dataset?.action,id:opener.dataset?.id}:null;}
 window.TitanFileEditor?.disposeWithin($('#dialog-body'));
 window.TitanLocations?.disposeWithin($('#dialog-body')); window.TitanNetworks?.disposeWithin($('#dialog-body')); window.TitanVMImages?.disposeWithin($('#dialog-body')); window.TitanFolderPicker?.disposeWithin($('#dialog-body')); window.TitanSystemDisk?.disposeWithin($('#dialog-body'));
 $('#dialog-body').innerHTML = `<div class="dialog-title"><h2>${esc(title)}</h2><button class="close-button" data-action="close" aria-label="Dialog schließen">×</button></div>${html}${submit?'<p class="form-error" data-dialog-error role="alert" hidden></p>':''}`;
 $('#dialog').showModal();
 window.TitanLocations?.mount($('#dialog-body'),{api,toast});
 if (submit) $('#dialog form').addEventListener('submit', async event => {event.preventDefault(); const form = event.target; const submitButton = $('button[type=submit]',form); submitButton.disabled = true; try {await submit(new FormData(form)); $('#dialog').close();} catch (error) {const notice=$('[data-dialog-error]',$('#dialog-body'));if(notice){notice.textContent=error.message;notice.hidden=false;}else toast(error.message,true);} finally {submitButton.disabled = false;}});
 return true;
}
const formEnd = (text = 'Erstellen') => `<div class="form-actions">${button('Abbrechen','close')}<button class="button primary" type="submit">${esc(text)}</button></div></form>`;
const locationField=(label,name,value='',options={})=>window.TitanLocations?.field(label,name,value,options)||field(label,name,'text',value,'',options.hint||'');
const catalogState={query:'',category:'',availability:''};
const firstLoginLabels={setup:'Konto in der App anlegen',default:'Standardzugang',install:'Zugang bei Installation',generated:'Passwort im App-Protokoll',none:'Ohne Anmeldung'};
function firstLoginMetadata(app){
 const login=app?.first_login;
 if(!login||!Object.hasOwn(firstLoginLabels,login.mode))return null;
 return {mode:login.mode,instructions:typeof login.instructions==='string'?login.instructions:'',documentation:typeof login.documentation==='string'?login.documentation:'',
  ...(['default','generated'].includes(login.mode)&&typeof login.username==='string'?{username:login.username}:{}),
  ...(login.mode==='default'&&typeof login.password==='string'?{password:login.password}:{})};
}
function appDocumentation(app,login=firstLoginMetadata(app)){
 try{const url=new URL(login?.documentation||app.documentation||'');return url.protocol==='https:'&&!url.username&&!url.password?url.href:'';}catch{return '';}
}
function appLoginPanel(app,{logsAvailable=false}={}){
 const login=firstLoginMetadata(app),documentation=appDocumentation(app,login);
 if(!login)return `<section class="app-login-panel"><h3>Erste Anmeldung</h3><p>Für diese Vorlage ist die erste Anmeldung noch nicht beschrieben.</p>${documentation?`<a class="text-link" href="${esc(documentation)}" target="_blank" rel="noopener">Anleitung öffnen ↗</a>`:''}</section>`;
 const credentials=['username','password'].filter(key=>Object.hasOwn(login,key));
 return `<section class="app-login-panel" data-login-mode="${esc(login.mode)}" aria-label="Erste Anmeldung"><div class="app-login-heading"><h3>Erste Anmeldung</h3>${pill(firstLoginLabels[login.mode],login.mode==='default'?'purple':'gray')}</div><p>${esc(login.instructions)}</p>${credentials.length?`<dl class="app-login-values">${credentials.map(key=>`<div><dt>${key==='username'?'Benutzername':'Standardpasswort'}</dt><dd><code>${esc(login[key])}</code>${button('Kopieren','app-copy-login',`data-id="${esc(app.id)}" data-field="${key}" aria-label="${key==='username'?'Benutzername':'Standardpasswort'} kopieren"`,'small')}</dd></div>`).join('')}</dl>`:''}${login.mode==='default'?'<p class="app-login-reminder">Gilt beim ersten Start mit neuer App-Konfiguration. Ändere das Standardpasswort anschließend in der App. Danach gilt dein eigenes Passwort.</p>':''}${login.mode==='install'?'<p class="hint">Verwende die Zugangsdaten, die du bei der Installation eingegeben hast. Titan zeigt gespeicherte persönliche Passwörter hier nicht an.</p>':''}${login.mode==='generated'?(logsAvailable?button('App-Protokoll anzeigen','app-show-login-log','','small'):'<p class="hint">Nach der Installation: App verwalten → App-Protokoll öffnen.</p>'):''}${documentation?`<a class="text-link app-login-documentation" href="${esc(documentation)}" target="_blank" rel="noopener">Anleitung zur ersten Anmeldung ↗</a>`:''}${credentials.length?'<p class="hint" data-login-copy-status role="status" aria-live="polite" hidden></p>':''}</section>`;
}
async function catalogApp(id){
 let app=catalogData.find(item=>item.id===id);
 if(!app){const data=await api('/api/catalog');catalogData=data.apps;app=catalogData.find(item=>item.id===id);}
 if(!app)throw new Error('App-Vorlage nicht gefunden.');
 return app;
}
function appLoginCopyStatus(target,message){
 const panel=target.closest?.('.app-login-panel'),status=panel?$('[data-login-copy-status]',panel):null;
 if(!status)return false;status.textContent=message;status.hidden=!message;return true;
}
function appLoginCopyFallback(target,value,key){
 if(target.isConnected===false)return;
 const panel=target.closest?.('.app-login-panel');
 if(!panel){toast('Die Browser-Zwischenablage ist nicht verfügbar. Markiere den angezeigten Wert und kopiere ihn mit Strg+C oder dem Kopieren-Menü deines Geräts.',true);return;}
 $('[data-login-copy-fallback]',panel)?.remove();
 const fallback=document.createElement('div');fallback.dataset.loginCopyFallback='true';
 fallback.innerHTML=`<p role="status">Die Browser-Zwischenablage ist nicht verfügbar. Kopiere den markierten Wert mit Strg+C oder dem Kopieren-Menü deines Geräts.</p>${field(key==='username'?'Benutzername zum Kopieren':'Standardpasswort zum Kopieren','login-copy-value','text',value,'readonly autocomplete="off"')}`;
 panel.append(fallback);const input=$('input',fallback);input?.scrollIntoView?.({block:'nearest'});input?.focus?.({preventScroll:true});input?.select?.();
}
function appInstallFields(app){return (app.install_schema||[]).map(option=>field(option.label,'option-'+option.key,option.type,option.type==='password'?'':option.default??'',`${option.required?'required':''} ${option.min!==undefined?'min="'+Number(option.min)+'"':''} ${option.max!==undefined?'max="'+Number(option.max)+'"':''} ${option.min_length?'minlength="'+Number(option.min_length)+'"':''} ${option.max_length?'maxlength="'+Number(option.max_length)+'"':''} ${option.type==='password'?'autocomplete="new-password"':''} ${option.pattern?'pattern="'+esc(option.pattern)+'"':''}`,option.help||'')).join('');}
function appInstallArguments(app,data){const options={};for(const option of app.install_schema||[]){const value=data.get('option-'+option.key);if(value!==null&&value!=='')options[option.key]=option.type==='number'?Number(value):String(value);}return {app:app.id,port:Number(data.get('port')),share:data.get('share')||null,...(Object.keys(options).length?{options}:{}),...(window.TitanNetworks?.installArguments(app,data)||{})};}
function catalogMatches(item,state=catalogState){const words=state.query.toLocaleLowerCase('de-DE').trim().split(/\s+/).filter(Boolean);return words.every(word=>item.search.includes(word))&&(!state.category||item.category===state.category)&&(!state.availability||(state.availability==='installed')===item.installed);}
function bindCatalog(){
 const search=$('#app-search'),category=$('#app-category'),availability=$('#app-availability');
 if(!search)return;
 const filter=()=>{catalogState.query=search.value;catalogState.category=category.value;catalogState.availability=availability.value;let count=0;for(const item of document.querySelectorAll('.catalog-card')){item.hidden=!catalogMatches({search:item.dataset.search,category:item.dataset.category,installed:item.dataset.installed==='true'});if(!item.hidden)count++;}$('#catalog-count').textContent=`${count} von ${catalogData.length} Anwendungen`;$('#catalog-empty').hidden=Boolean(count);};
 [search,category,availability].forEach(control=>control.addEventListener(control===search?'input':'change',filter));filter();
}
async function action(operation, args = {}) {
 const result = await api('/api/actions', {operation, arguments:args}); watched.add(result.job); toast('Auftrag gestartet. Den Status findest du unter Aufträge.'); return result;
}
async function renderAuth(setup) {
 fileDialogRequest++;
 window.TitanDesktop?.dispose(); window.TitanFileEditor?.dispose(); if($('#dialog').open)$('#dialog').close();
 stopDashboardClock(); window.TitanUpdates?.dispose(); window.TitanSystemDisk?.dispose();
 window.TitanManagers?.dispose(); window.TitanSettingsCenter?.dispose(); window.TitanDashboard?.clear(); window.TitanFiles?.dispose(); window.TitanFileBrowser?.dispose(); window.TitanTerminal?.dispose(); window.TitanServices?.dispose(); filesView=null;
 $('#shell').hidden = true; $('#auth').hidden = false;
 $('#auth').innerHTML = `<div class="auth-card"><div class="brand"><img src="/logo.svg" alt=""><span>Titan<span class="brand-dot">.</span></span></div><div class="alpha-notice" role="note"><strong>Alpha · Frühe Entwicklung</strong><p>Titan steht ganz am Anfang. Nur mit Testdaten verwenden.</p></div><h1>${setup?'Dein NAS beginnt hier.':'Willkommen zu Hause.'}</h1><p class="subtitle">${setup?'Administrator direkt im Browser anlegen.':'Melde dich an, um deinen Server zu verwalten.'}</p><form>${field('Benutzername','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}" autocomplete="username"')}${field('Passwort','password','password','','required minlength="12" maxlength="256" autocomplete="'+(setup?'new-password':'current-password')+'"')}${setup?field('Passwort bestätigen','password_confirmation','password','','required minlength="12" maxlength="256" autocomplete="new-password"'):''}<p class="auth-error" id="auth-error" role="alert"></p><button class="button primary" type="submit">${setup?'Administrator erstellen':'Anmelden'} →</button></form><p class="hint">${setup?'Richte Titan direkt nach der Installation in deinem lokalen Netz ein.':'Privat. Übersichtlich. Unter deiner Kontrolle.'}</p></div>`;
 $('#auth form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = $('button[type=submit]',event.target); submit.disabled = true; $('#auth-error').textContent = '';
  try {
   const form = new FormData(event.target);
   if (setup && form.get('password') !== form.get('password_confirmation')) throw new Error('Die Passwörter stimmen nicht überein.');
   await api(setup?'/api/setup':'/api/login',{name:form.get('name'),password:form.get('password')});
   if (setup) {session.setup_required = false; delete session.setup_csrf; toast('Administrator angelegt. Bitte anmelden.'); renderAuth(false);} else await boot();
  } catch(error) {
   if (setup && error.status === 409) {
    try {session = await api('/api/session'); renderAuth(Boolean(session.setup_required));}
    catch(refreshError) {$('#auth-error').textContent = refreshError.message; return;}
   }
   $('#auth-error').textContent = error.message;
  } finally {submit.disabled=false;}
 });
}

async function boot() {
 session = await api('/api/session');
 if (!session.user) return renderAuth(session.setup_required);
 $('#auth').hidden = true; $('#shell').hidden = false;
 $('#footer-state').textContent=session.demo?'Demo · Beispieldaten':'Verbunden';
 $('#version').textContent = session.version; $('#demo-badge').hidden = !session.demo;
 $('#profile').setAttribute('title','Konto: '+session.user.name);
 $('#profile').setAttribute('aria-label','Konto: '+session.user.name);
 $('#main-menu').setAttribute('href',session.user.role==='admin'?'#dashboard':'#files');
 const existing = await api('/api/jobs'); watched = new Set(existing.filter(item => ['queued','running'].includes(item.status)).map(item => item.id));
 $('#alerts-button').hidden = session.user.role!=='admin';
 if (!polling) {polling = setInterval(pollJobs, 3000);setInterval(pollAlerts,30000);}
 await pollAlerts();
 await navigate();
}
async function navigate() {
 fileDialogRequest++;
 window.TitanLocations?.disposeWithin($('#main')); window.TitanUpdates?.dispose(); window.TitanSystemDisk?.dispose();
 stopDashboardClock();
 window.TitanManagers?.dispose(); window.TitanSettingsCenter?.dispose(); window.TitanDashboard?.dispose(); window.TitanFiles?.dispose(); window.TitanFileBrowser?.dispose(); window.TitanTerminal?.dispose(); window.TitanServices?.dispose(); filesView=null;
 const requested = location.hash.slice(1).split('?')[0] || (session.user.role === 'admin' ? 'dashboard' : 'files');
 page = nav.some(([name]) => name === requested) ? requested : 'dashboard';
 if (session.user.role !== 'admin') page = 'files';
 const mine = ++generation;
 $('#shell').dataset.page=page; $('#main').dataset.page=page;
 $('#page-crumb').textContent = nav.find(([key]) => key === page)[1];
 window.TitanDesktop?.dispose();
 $('#main').innerHTML = '<div class="loading">Server wird geladen …</div>';
 try {const html = await pages[page](); if (mine === generation) {$('#main').innerHTML = page==='dashboard'?html:`<section class="nas-window" aria-label="${esc(nav.find(([key])=>key===page)[1])}">${window.TitanDesktop?.application({page,title:esc(nav.find(([key])=>key===page)[1]),icon,user:session.user})||''}<div class="nas-window-content">${html}</div></section>`; window.TitanDesktop?.mount({root:document,user:session.user,page}); bindPage(); syncDashboardClock();}} catch(error) { if(mine===generation) $('#main').innerHTML = heading('Verbindung prüfen',error.message) + button('Erneut versuchen','refresh','','primary'); }
}

function vmCpuList(options, status) {
 const supplied=options.cpu_topology?.cpus;
 const cpus=Array.isArray(supplied)?supplied:[];
 return cpus.filter(cpu=>Number.isInteger(cpu.id)&&cpu.id>=0).sort((a,b)=>a.id-b.id);
}
function vmCpuFields(options, status, vm = {}) {
 const cpus=vmCpuList(options,status),online=cpus.filter(cpu=>cpu.online!==false),selected=new Set(vm.cpu_ids||[]);
 const types={performance:'P-Kern',efficiency:'E-Kern',standard:'Standardkern',unknown:'Typ nicht gemeldet'};
 const max=Math.max(1,online.length||Number(status.cpus)||1),manual=selected.size>0,maxMemory=Math.max(512,Math.floor(Number(status.memory_total)/1024**2)-1024);
 return `<fieldset class="vm-form-section"><legend>CPU und Arbeitsspeicher</legend><div class="form-grid">${field('Virtuelle CPUs','cpus','number',vm.cpus||Math.min(2,max),`required min="1" max="${max}"`, 'Anzahl der Prozessoren, die das Gastsystem sieht.')}${field('Arbeitsspeicher in MiB','memory_mb','number',vm.memory_mb||Math.min(4096,maxMemory),`required min="512" max="${maxMemory}"`,'1 GiB bleibt für das NAS-System frei.')}</div><div class="cpu-selection">${selectField('Host-CPUs zuweisen','cpu_mode',[['auto','Automatisch · Linux verteilt die Rechenzeit'],['manual','Manuell · einzelne Host-CPUs auswählen']],manual?'manual':'auto')}<p class="hint">CPU 0, CPU 1 usw. sind logische Host-CPUs. SMT-Geschwister teilen denselben physischen Kern. Ausgewählte CPUs werden nicht exklusiv reserviert.</p>${options.cpu_topology?.error?`<p class="hint">${esc(options.cpu_topology.error)}</p>`:''}<div data-cpu-manual ${manual?'':'hidden'}><div class="cpu-selection-toolbar">${button('Alle online','vm-cpu-select','data-group="all"','small')}${online.some(cpu=>cpu.core_type==='performance')?button('P-Kerne','vm-cpu-select','data-group="performance"','small'):''}${online.some(cpu=>cpu.core_type==='efficiency')?button('E-Kerne','vm-cpu-select','data-group="efficiency"','small'):''}${button('Auswahl leeren','vm-cpu-select','data-group="none"','small')}<span class="hint" data-cpu-count></span></div><div class="cpu-grid">${cpus.map(cpu=>{const type=Object.hasOwn(types,cpu.core_type)?cpu.core_type:'unknown';const siblings=(cpu.siblings||[]).filter(id=>Number.isInteger(id)&&id!==cpu.id);return `<label class="cpu-option cpu-option-${type}"><input type="checkbox" name="cpu_ids" value="${cpu.id}" data-core-type="${type}" ${selected.has(cpu.id)?'checked':''} ${cpu.online===false?'disabled':''}><span><strong>CPU ${cpu.id}</strong><small>${types[type]}${cpu.core_id===null||cpu.core_id===undefined?'':' · Kern '+esc(cpu.core_id)}${siblings.length?' · SMT mit CPU '+siblings.map(esc).join(', '):''}${cpu.online===false?' · Offline':''}</small></span></label>`;}).join('')||'<p class="hint">Der Host meldet keine CPU-Topologie. Die automatische Zuweisung bleibt verfügbar.</p>'}</div><p class="hint">P- und E-Kerne erscheinen nur, wenn der Host den Kerntyp zuverlässig meldet.</p></div></div></fieldset>`;
}
function bindVmCpuControls(form) {
 const mode=$('[name=cpu_mode]',form),area=$('[data-cpu-manual]',form),count=$('[data-cpu-count]',form),number=$('[name=cpus]',form);
 const boxes=[...form.querySelectorAll('[name=cpu_ids]')],online=boxes.filter(box=>!box.disabled);
 const maximum=Number(number.max);
 const sync=()=>{const manual=mode.value==='manual',selected=online.filter(box=>box.checked).length;area.hidden=!manual;count.textContent=`${selected} Host-CPU${selected===1?'':'s'} ausgewählt`;number.max=manual&&selected?selected:maximum;if(manual&&selected&&Number(number.value)>selected)number.value=selected;};
 mode.addEventListener('change',sync);boxes.forEach(box=>box.addEventListener('change',sync));
 form.querySelectorAll('[data-action=vm-cpu-select]').forEach(control=>control.addEventListener('click',()=>{online.forEach(box=>box.checked=control.dataset.group==='all'||box.dataset.coreType===control.dataset.group);sync();}));
 sync();
}
function vmCpuArguments(data, options, status) {
 const available=vmCpuList(options,status).filter(cpu=>cpu.online!==false).map(cpu=>cpu.id),online=new Set(available);
 const cpus=Number(data.get('cpus')),memory_mb=Number(data.get('memory_mb'));
 if(!Number.isInteger(cpus)||cpus<1||cpus>Math.max(1,available.length||Number(status.cpus)))throw new Error('Wähle eine gültige Anzahl virtueller CPUs.');
 const cpu_ids=data.get('cpu_mode')==='manual'?data.getAll('cpu_ids').map(Number):[];
 if(data.get('cpu_mode')==='manual'&&(!cpu_ids.length||cpu_ids.some(id=>!Number.isInteger(id)||!online.has(id))||new Set(cpu_ids).size!==cpu_ids.length||cpus>cpu_ids.length))throw new Error('Wähle mindestens so viele verfügbare Host-CPUs wie virtuelle CPUs.');
 if(!Number.isInteger(memory_mb)||memory_mb<512||memory_mb>Math.max(512,Math.floor(Number(status.memory_total)/1024**2)-1024))throw new Error('Wähle eine gültige Arbeitsspeichergröße. 1 GiB bleibt für das NAS-System frei.');
 return {cpus,memory_mb,cpu_ids};
}
function vmStorageField(options) {
 const storage=options.storage||[],selected=storage.find(item=>item.id==='system'&&item.available)||storage.find(item=>item.available);
 return `<div class="field"><label for="f-storage">Speicherort des virtuellen Laufwerks</label><select id="f-storage" name="storage" required>${storage.map(item=>`<option value="${esc(item.id)}" ${item.id===selected?.id?'selected':''} ${item.available?'':'disabled'}>${esc(item.label)} · ${item.available?bytes(item.free_bytes)+' frei':'nicht verfügbar'}</option>`).join('')}</select><small data-vm-storage-path>${esc(selected?.path||'Kein verfügbares Speicherziel')}</small></div>`;
}
function bindVmSourceControls(form, options) {
 const sources=[...form.querySelectorAll('[name=disk_source]')],image=$('[name=disk_image]',form),iso=$('[name=iso]',form),size=$('[name=disk_gb]',form),storage=$('[name=storage]',form),path=$('[data-vm-storage-path]',form);
 const sync=()=>{const imported=sources.find(item=>item.checked)?.value==='image',chosen=(options.disk_images||[]).find(item=>item.id===image.value);$('[data-vm-image]',form).hidden=!imported;image.disabled=!imported;image.required=imported;iso.required=!imported;const min=imported&&chosen?Math.max(8,Math.ceil(Number(chosen.virtual_size)/1024**3)):8;size.min=min;if(Number(size.value)<min)size.value=min;path.textContent=(options.storage||[]).find(item=>item.id===storage.value)?.path||'';};
 sources.forEach(control=>control.addEventListener('change',()=>{if(control.checked){if(control.value==='image')iso.value='';else if(!iso.value)iso.value=(options.isos||[])[0]||'';}sync();}));image.addEventListener('change',sync);storage.addEventListener('change',sync);sync();
}
function vmCreateArguments(data, options, status) {
 const source=data.get('disk_source'),disk_image=source==='image'?data.get('disk_image'):null,iso=data.get('iso')||null;
 const selected=(options.disk_images||[]).find(item=>item.id===disk_image),disk_gb=Number(data.get('disk_gb'));
 if(source!=='blank'&&source!=='image')throw new Error('Wähle eine gültige Laufwerksquelle.');
 if(source==='blank'&&!iso)throw new Error('Wähle ein Installations-ISO für das neue Laufwerk.');
 if(source==='image'&&!selected)throw new Error('Wähle ein verfügbares QCOW2- oder RAW-Laufwerksimage.');
 if(!Number.isInteger(disk_gb)||disk_gb<Math.max(8,Math.ceil(Number(selected?.virtual_size||0)/1024**3))||disk_gb>10000)throw new Error('Die Laufwerksgröße darf das Quellimage nicht verkleinern und muss zwischen 8 und 10000 GiB liegen.');
 const storage=data.get('storage');if(!(options.storage||[]).some(item=>item.id===storage&&item.available))throw new Error('Das gewählte Speicherziel ist nicht verfügbar.');
 return {name:data.get('name'),...vmCpuArguments(data,options,status),disk_gb,iso,storage,disk_image};
}
function vmHardwareDetails(vm) {
 const disk=Number(vm.virtual_size)||Number(vm.disk_gb)*1024**3;
 return `<div class="vm-hardware"><div class="stat-card"><small>Prozessoren</small><strong>${esc(vm.cpus)} vCPU</strong></div><div class="stat-card"><small>Arbeitsspeicher</small><strong>${bytes(vm.memory_mb*1024**2)}</strong></div><div class="stat-card"><small>Virtuelles Laufwerk</small><strong>${disk?bytes(disk):'Nicht ermittelt'}</strong></div></div><dl class="vm-detail-list"><div><dt>CPU-Zuweisung</dt><dd>${vm.cpu_ids?.length?vm.cpu_ids.map(id=>'CPU '+esc(id)).join(', '):'Automatisch'}</dd></div><div><dt>Laufwerkspfad</dt><dd>${esc(vm.disk_path||'Wird nach Aktualisierung ermittelt')}</dd></div><div><dt>Installationsmedium</dt><dd>${vm.iso?esc(vm.iso)+' · '+(vm.boot==='cdrom'?'ISO zuerst':'Festplatte zuerst'):'Keines · Start von Festplatte'}</dd></div></dl>`;
}

function componentPanel(data) {
 const repair=data.repair||{}, busy=Boolean(repair.running);
 return `<section class="panel component-panel"><div class="panel-heading"><h2>Systemkomponenten</h2>${busy?pill('Wird eingerichtet','purple'):''}</div><p class="hint">Docker und VM-Komponenten sind im Titan-Systemimage enthalten. Hier kannst du deren Dienste prüfen und reparieren.</p><div class="two-columns">${Object.entries(data.components||{}).map(([name,item])=>`<article class="component-card"><h3>${name==='docker'?'Docker und Compose':'KVM, libvirt und Browserkonsole'}</h3>${pill(item.available?'Bereit':item.installed?'Prüfen':'Image unvollständig',item.available?'':'gray')}<p>${esc(item.error||(item.available?'Pakete und Dienste sind erreichbar.':'Komponente ist noch nicht bereit. Fehlende Programme benötigen ein neues Systemimage.'))}</p>${item.missing?.length?`<p class="hint">Fehlt: ${item.missing.map(esc).join(', ')}</p>`:''}${button('Dienste reparieren','component-install',`data-component="${esc(name)}" ${busy?'disabled':''}`,'small')}</article>`).join('')}</div><div class="form-actions">${button('Alle Dienste reparieren','component-install',`data-component="all" ${busy?'disabled':''}`,'primary')}${button('Status prüfen','refresh','','small')}</div>${busy?`<p role="status">${esc(repair.phase||'Systemdienste werden geprüft.')} Den Auftrag findest du oben rechts.</p>`:''}${repair.error?`<pre class="code">${esc(repair.error)}</pre>`:''}${(repair.warnings||[]).map(x=>`<p class="hint">${esc(x)}</p>`).join('')}</section>`;
}

const pages = {
 async control(){
  const groups=[['Dateien und Speicher',[['files','Dateimanager','Dateien öffnen, organisieren und bearbeiten'],['storage','Speicher','Volumes, Dateisysteme und Laufwerke'],['shares','Freigaben','SMB-Zugriff und Berechtigungen'],['backups','Backups','Sicherungsziele, Zeitpläne und Wiederherstellung']]],['Anwendungen und Virtualisierung',[['apps','App Store','Apps suchen und installieren'],['docker','Docker','Installierte Container und Netzwerke verwalten'],['vms','Virtuelle Maschinen','CPU, Laufwerke und Browserkonsole'],['services','Dienste','Liste, Details, Protokolle und Steuerung'],['terminal','Terminal','Kommandos direkt auf dem Server']]],['NAS verwalten',[['users','Benutzer','Konten, Passwörter und Zugriffsrechte'],['monitoring','Meldungen','Status prüfen und Hinweise bearbeiten'],['jobs','Aufträge','Fortschritt und Ergebnisse deiner Aktionen'],['settings','Einstellungen','Server, Komponenten und Update-Kanal'],['updates','Updates','Neue Versionen prüfen und vorbereiten'],['logs','Protokoll','Verwaltungsaktionen nachvollziehen']]]];
  return heading('Verwaltung','Alle Werkzeuge nach Aufgaben geordnet.','','DEIN NAS')+'<div class="control-search search"><span>⌕</span><input id="control-search" type="search" placeholder="Werkzeug suchen …" aria-label="Verwaltung durchsuchen"></div>'+groups.map(([title,items])=>`<section class="control-section"><h2>${esc(title)}</h2><div class="control-grid">${items.map(([key,label,description])=>`<a class="control-card" href="#${key}" data-control-search="${esc((label+' '+description).toLocaleLowerCase('de-DE'))}"><span class="control-icon nav-icon">${icon(key)}</span><div><h3>${esc(label)}</h3><p>${esc(description)}</p></div><span class="control-arrow" aria-hidden="true">→</span></a>`).join('')}</div></section>`).join('')+'<p class="empty" id="control-empty" hidden>Kein passendes Werkzeug gefunden.</p>';
 },
 async services() {
  servicesData=await api('/api/services');
  return heading('Dienste','Systemdienste starten, verwalten und eigene Programme einrichten.','','SYSTEM')+window.TitanServices.render(servicesData,{esc,pill});
 },
 async terminal() {
  const tools=[['open','Verbinden'],['close','Sitzung beenden'],['copy','Kopieren'],['paste','Einfügen'],['interrupt','Befehl abbrechen'],['clear','Bildschirm leeren']];
  return heading('Terminal','Direkt auf deinem uCore-NAS arbeiten.','','SYSTEM')+`<section class="panel terminal-panel"><div class="terminal-heading"><div><h2>Server-Konsole</h2><p id="terminal-state" role="status">Nicht verbunden</p></div><span class="pill purple">${session.demo?'Demo-Shell':'root · Administrator'}</span></div>${session.demo?'<p class="notice">Isolierte Demo: Nur Beispielbefehle wie help, pwd und echo werden simuliert.</p>':'<p class="hint">Die Shell hat Administratorrechte auf deinem NAS. Eine Sitzung endet beim Seitenwechsel oder Abmelden, nach 15 Minuten ohne Eingabe oder spätestens nach 8 Stunden.</p>'}<div class="terminal-toolbar">${tools.map(([key,label])=>`<button type="button" class="button ${key==='open'?'primary':''}" data-terminal-action="${key}" ${key!=='open'?'disabled':''}>${label}</button>`).join('')}</div><div id="terminal-screen" aria-label="Interaktive Server-Konsole"></div><p class="hint terminal-shortcuts">Strg+C: markierten Text kopieren, sonst Befehl abbrechen · Strg+Umschalt+C: kopieren · Strg+V: einfügen · Pfeiltasten und Tab: Befehle bearbeiten</p></section>`;
 },
 async dashboard() {
  const dashboard = window.TitanDashboard;
  const [status, apps, shares, vms, layout] = await Promise.all([api('/api/status'),api('/api/apps'),api('/api/shares'),api('/api/vms'),dashboard?.load(api,session.user.name) || Promise.resolve({order:['storage','resources','health','apps','shares','vms'],available:false})]);
  const percent = (used,total) => total > 0 ? Math.max(0,Math.min(100,Math.round(used / total * 100))) : 0;
  const storageAvailable=Number.isFinite(status.storage?.total)&&status.storage.total>0&&Number.isFinite(status.storage?.used);
  const used = storageAvailable?percent(status.storage.used,status.storage.total):null;
  const ram = percent(status.memory_used,status.memory_total);
  const cpu = Number.isFinite(status.cpu_percent)?Math.max(0,Math.min(100,status.cpu_percent)):null;
  const hour = new Date().getHours(); const greeting = hour < 11 ? 'Guten Morgen' : hour < 18 ? 'Guten Tag' : 'Guten Abend';
  const services = [['web','Titan-Oberfläche','dashboard'],['agent','Titan-Verwaltung','settings'],['https','HTTPS','settings'],['docker','Docker','docker'],['samba','SMB-Freigaben','shares'],['zfs','ZFS-Speicher','storage'],['vms','Virtualisierung','vms']];
  const serviceDetails = status.service_details || Object.fromEntries(Object.entries(status.services).map(([name,active])=>[name,{installed:active,active,state:active?'active':'missing'}]));
  const relevant = item=>item && (item.relevant ?? (item.installed || item.active || item.configured));
  const visibleServices = services.filter(([key])=>relevant(serviceDetails[key]));
  const configured = Object.values(serviceDetails).filter(relevant);
  const healthy = configured.length>0&&configured.every(item=>item.active);
  $('#footer-state').textContent = session.demo?'Demo · Beispieldaten':healthy?'Alle eingerichteten Dienste aktiv':'Dienste prüfen';
  const tile = (id,title,body,action='',classes='') => `<section class="panel dashboard-tile ${classes}" data-dashboard-tile="${id}" aria-labelledby="tile-${id}-title"><div class="panel-heading"><h2 id="tile-${id}-title">${title}</h2><div class="tile-heading-actions">${action}${dashboard?.controls(id,title)||''}</div></div>${body}</section>`;
  const tiles = {
   storage:tile('storage','Dein Speicher',`${storageAvailable?`<div class="storage-content"><div class="storage-ring"><svg viewBox="0 0 120 120" role="img" aria-label="${used} Prozent des Speichers belegt"><circle class="track" cx="60" cy="60" r="50"/><circle class="progress" cx="60" cy="60" r="50" stroke-dasharray="${used*3.142} 314.2"/></svg><div class="ring-label" aria-hidden="true"><strong>${used}<span>%</span></strong><small>belegt</small></div></div><div class="storage-detail"><strong>${bytes(status.storage.used)}</strong><small>von ${bytes(status.storage.total)} verwendet · ${status.storage.scope==='system'?'Systemlaufwerk':'Datenlaufwerke'}</small><div class="legend"><span>Belegt · ${bytes(status.storage.used)}</span><span>Verfügbar · ${bytes(Math.max(0,status.storage.total-status.storage.used))}</span></div></div></div>`:`<div class="notice warning">${esc(status.storage_error||'Datenlaufwerk nicht erreichbar. Keine Kapazitätsmessung verfügbar.')}</div>`}<a class="tile-footer text-link" href="#storage">Speicher verwalten →</a>`),
   resources:tile('resources','Systemressourcen',`<div data-live-resources>${dashboard?.resourceMetrics?.(status,{bytes,esc,demo:session.demo})||'<p class="hint">Messwerte werden geladen …</p>'}</div>`),
   health:tile('health','Systemstatus',`<div class="health-list">${visibleServices.map(([key,label,glyph]) => `<div class="health-row"><span class="health-icon nav-icon">${icon(glyph)}</span><span>${label}</span><span class="${serviceDetails[key].active?'healthy':'error-text'}">${serviceDetails[key].active?'Aktiv':!serviceDetails[key].installed?'Nicht installiert':({failed:'Fehlgeschlagen',degraded:'Fehler',unknown:'Unbekannt','not-found':'Dienst fehlt'})[serviceDetails[key].state]||'Inaktiv'}</span></div>`).join('') || empty('Noch kein Dienststatus verfügbar.')}</div><div class="health-caption">${session.demo?'Isolierte Vorschau mit Beispieldaten':'Vorhandene und genutzte Komponenten · '+esc(status.hostname)}</div>`,pill(healthy?'Bereit':'Prüfen',healthy?'':'red'),'health-panel'),
   apps:tile('apps','Docker-Anwendungen',`${apps.available?'':`<div class="notice warning">${esc(apps.error||'Docker ist nicht bereit.')} ${button('Docker einrichten','component-install','data-component="docker"','small')}</div>`}${apps.installed.slice(0,5).map(app=>`<div class="desktop-app-status"><span class="app-icon ${esc(app.id)}">▣</span><button class="text-link" data-action="app-manage" data-id="${esc(app.id)}"><strong>${esc(app.name)}</strong><small>${esc(window.TitanNetworks?.summary(app)||app.status||'')}</small></button>${pill(app.phase==='failed'?'Fehler':app.state==='running'?'Läuft':'Gestoppt',app.phase==='failed'?'red':app.state==='running'?'':'gray')}</div>`).join('')||empty('Apps findest du im App Store.')}<a class="tile-footer text-link" href="#docker">Container verwalten →</a>`,pill(String(apps.installed.length),'gray')),
   shares:tile('shares','Deine Freigaben',`${shares.length ? shares.slice(0,4).map(item => `<a href="#files" class="list-row"><span class="row-icon">▱</span><span class="row-main"><strong>${esc(item.name)}</strong><small>${esc(item.path)}</small></span><span class="row-end">${new Set([...item.readers,...item.writers]).size} Berechtigte ↗</span></a>`).join('') : empty('Erstelle deine erste SMB-Freigabe.')}<a class="tile-footer text-link" href="#shares">Freigaben verwalten →</a>`,pill(String(shares.length),'gray')),
   vms:tile('vms','Virtuelle Maschinen',`${vms.available?'':`<div class="notice warning">${esc(vms.error||'VM-Komponenten sind nicht bereit.')} ${button('VM-Komponenten einrichten','component-install','data-component="vms"','small')}</div>`}${vms.vms.length ? vms.vms.slice(0,3).map(vm => `<div class="list-row"><span class="row-icon">▣</span><span class="row-main"><strong>${esc(vm.name)}</strong><small>${vm.cpus} vCPU · ${bytes(vm.memory_mb*1024**2)} RAM</small></span>${pill(vm.state==='running'?'Läuft':'Gestoppt',vm.state==='running'?'':'gray')}</div>`).join('') : empty('Dein Platz für virtuelle Maschinen.','▣')}<a class="tile-footer text-link" href="#vms">Virtuelle Maschinen verwalten →</a>`,pill(String(vms.vms.length),'gray')),
  };
  return heading(`${greeting}, ${session.user.name}.`,'Deine Anwendungen und dein NAS im Blick.',dashboardDateCard(),'DEIN NAS · '+status.hostname)+
   `<div class="nas-desktop"><div class="desktop-workspace">${window.TitanDesktop?.launcher({esc,icon,user:session.user})||''}</div><aside class="desktop-status" aria-label="NAS-Status">${dashboard?.toolbar()||''}${!layout.available&&dashboard?'<p class="hint layout-load-hint">Die gespeicherte Anordnung ist gerade nicht erreichbar.</p>':''}<div id="dashboard-grid" class="dashboard-grid">${layout.order.map(id=>tiles[id]).join('')}</div></aside></div>`;
 },
 async apps() {
  const [catalog, installed] = await Promise.all([api('/api/catalog'),api('/api/apps')]); catalogData = catalog.apps;
  const installedIds=new Set(installed.installed.map(item=>item.id)),categories=[...new Set(catalog.apps.map(item=>item.category))].sort((a,b)=>a.localeCompare(b,'de'));
  if(!categories.includes(catalogState.category))catalogState.category='';
  return heading('App Store','Apps entdecken, Zugänge prüfen und mit deinen Einstellungen installieren.',button('Netzwerke','app-networks')+pill(catalog.source||'LinuxServer.io','purple'),'ANWENDUNGEN')+
   (catalog.error?`<div class="notice warning">${esc(catalog.error)}</div>`:'')+
   (installed.available?'':`<div class="notice warning">${esc(installed.error||'Docker ist noch nicht bereit.')} ${button('Docker einrichten','component-install','data-component="docker"','small')}</div>`)+
   `<section class="app-installed-section"><div class="section-heading"><h2>Installiert <small>${installed.installed.length} Anwendungen</small></h2><a href="#docker" class="text-link">Docker-Verwaltung →</a><a href="#jobs" class="text-link">Installationsfortschritt →</a></div><div class="apps-grid">${installed.installed.map(appCard).join('') || empty('Noch keine Apps installiert. Wähle unten eine Vorlage.')}</div></section><section class="app-discover-section"><div class="section-heading"><h2>Entdecken</h2><span id="catalog-count" class="hint" aria-live="polite"></span></div><div class="catalog-filters"><div class="search"><span>⌕</span><input id="app-search" type="search" placeholder="Name, Zweck oder Kategorie …" value="${esc(catalogState.query)}" aria-label="Apps durchsuchen"></div>${selectField('Kategorie','app-category',[['','Alle Kategorien'],...categories.map(name=>[name,name])],catalogState.category).replace('id="f-app-category"','id="app-category"').replace('for="f-app-category"','for="app-category"')}${selectField('Auswahl','app-availability',[['','Alle Anwendungen'],['available','Noch nicht installiert'],['installed','Bereits installiert']],catalogState.availability).replace('id="f-app-availability"','id="app-availability"').replace('for="f-app-availability"','for="app-availability"')}</div><div class="catalog-grid">${catalog.apps.map(app=>`<article class="app-card catalog-card" data-search="${esc([app.id,app.name,app.category,app.description].join(' ').toLocaleLowerCase('de-DE'))}" data-category="${esc(app.category)}" data-installed="${installedIds.has(app.id)}"><div class="app-top"><div class="app-icon ${esc(app.id)}">${esc(app.symbol)}</div>${pill(app.category,'gray')}</div><h3>${esc(app.name)}</h3><p>${esc(app.description)}</p><p class="catalog-login-summary">${esc(firstLoginLabels[firstLoginMetadata(app)?.mode]||'Anmeldedetails ansehen')}</p><div class="app-bottom">${button('Details & Anmeldung','app-info',`data-id="${esc(app.id)}" data-installed="${installedIds.has(app.id)}" data-can-install="${installed.available&&!app.deprecated}"`,'small')}${installedIds.has(app.id)?button('Verwalten','app-manage',`data-id="${esc(app.id)}"`,'small'):button('Installieren','app-install',`data-id="${esc(app.id)}" ${app.deprecated||!installed.available?'disabled':''}`,'small primary')}</div></article>`).join('')}</div><p id="catalog-empty" class="empty" hidden>Keine passenden Apps. Ändere Suchbegriff oder Filter.</p></section>`;
 },
 async docker() {
  const data=await api('/api/apps');
  return window.TitanManagers.renderApps({data,session,esc,bytes,button,empty,pill,connection:app=>window.TitanNetworks?.connection(app),networkSummary:app=>window.TitanNetworks?.summary(app)||'Nicht ermittelt'});
 },
 async storage() {
  const [storage, snapshots, systemDiskResult] = await Promise.all([api('/api/storage'),api('/api/snapshots'),api('/api/system-disk').then(data=>({data})).catch(error=>({error:error.message}))]);
  const existingFilesystems=(storage.existing_filesystems||[]).filter(item=>!(systemDiskResult.data?.supported===true&&typeof systemDiskResult.data.partition==='string'&&item.name===systemDiskResult.data.partition));
  return heading('Speicher','Ext4 als Standard, XFS für einzelne Laufwerke und ZFS für Pools.',`<div class="form-actions">${button('+ Volume einrichten','volume-create','','primary')}${button('+ ZFS-Pool','pool-create')}</div>`,'SPEICHER')+
   `<div class="notice">Neue einzelne Laufwerke werden standardmäßig mit <strong>Ext4</strong> eingerichtet. Du kannst auch XFS wählen. ZFS bietet zusätzlich Pools und Snapshots. Der Installer formatiert keine Laufwerke.</div><div class="stack">${window.TitanSystemDisk?.panel(systemDiskResult.data,systemDiskResult.error)||''}<section class="panel"><div class="panel-heading"><h2>Ext4- und XFS-Volumes</h2><span class="hint">Ein Laufwerk je Volume · dauerhaft über UUID eingehängt</span></div><div class="two-columns">${(storage.volumes||[]).map(volume=>`<section class="panel"><div class="panel-heading"><h2>${esc(volume.name)}</h2>${pill(volume.filesystem.toUpperCase(),'purple')}</div><p class="hint">${esc(volume.mountpoint)}<br>${esc(volume.disk)} · UUID ${esc(volume.uuid)}</p><div class="stat-row"><div class="stat-card"><small>Kapazität</small><strong>${volume.total?bytes(volume.total):'—'}</strong></div><div class="stat-card"><small>Verfügbar</small><strong>${volume.mounted?bytes(volume.free):'—'}</strong></div></div>${pill(volume.state,volume.mounted?'':'red')}${volume.error?`<p class="hint">${esc(volume.error)}</p>`:''}<div class="form-actions">${volume.mounted?'<a class="button small" href="#shares">Freigabe erstellen</a>':button('Einhängen','volume-mount',`data-name="${esc(volume.name)}" ${['format_failed','formatting'].includes(volume.phase)?'disabled':''}`,'small')}</div>${volume.mounted?'':'<p class="hint">Dateizugriffe und Apps bleiben bis zum Einhängen gesperrt. Bestehende Dateien werden nicht neu formatiert.</p>'}</section>`).join('')||empty('Richte ein leeres Laufwerk mit Ext4 oder XFS ein. Danach kannst du darauf Freigaben anlegen.')}</div></section><div class="section-heading"><h2>ZFS-Pools</h2><span class="hint">Optional · mehrere Laufwerke und Snapshots</span></div><div class="two-columns">${storage.pools.map(pool=>`<section class="panel"><div class="panel-heading"><h2>${esc(pool.name)}</h2>${pill(pool.health,pool.health==='ONLINE'?'':'red')}</div><div class="stat-row"><div class="stat-card"><small>Kapazität</small><strong>${bytes(pool.size)}</strong></div><div class="stat-card"><small>Verfügbar</small><strong>${bytes(pool.free)}</strong></div></div><div class="meter" data-percent="${pool.used/pool.size*100}"><span></span></div><div class="form-actions">${button('Prüflauf starten','scrub',`data-pool="${esc(pool.name)}"`,'small')}${button('+ Dataset','dataset-create',`data-parent="${esc(pool.name)}"`,'small')}</div></section>`).join('') || `<section class="panel">${empty('Noch keine ZFS-Pools vorhanden.')}</section>`}</div>
   <section class="panel"><div class="panel-heading"><h2>Datasets</h2><span class="hint">Getrennte Speicherbereiche für deine Daten</span></div><div id="upload-status">${uploadStatus()}</div><div class="table-wrap"><table><thead><tr><th>NAME</th><th>BELEGT</th><th>VERFÜGBAR</th><th></th></tr></thead><tbody>${storage.datasets.map(item=>`<tr><td><strong>${esc(item.name)}</strong><div class="hint">${esc(item.mountpoint)}</div></td><td>${bytes(item.used)}</td><td>${bytes(item.available)}</td><td class="table-actions">${button('Snapshot','snapshot-create',`data-dataset="${esc(item.name)}"`,'small')}${button('+ Dataset','dataset-create',`data-parent="${esc(item.name)}"`,'small')}</td></tr>`).join('')}</tbody></table></div></section>
   <section class="panel"><div class="panel-heading"><h2>Laufwerke</h2><span class="hint">Vorhandene Partitionen bleiben erhalten</span></div><div class="table-wrap"><table><thead><tr><th>LAUFWERK</th><th>MODELL</th><th>KAPAZITÄT</th><th>DATEISYSTEM</th><th></th></tr></thead><tbody>${storage.disks.map(disk=>`<tr><td>${esc(disk.name)}</td><td>${esc(disk.model || '—')}</td><td>${bytes(disk.size)}</td><td>${esc(disk.fstype || (disk.children?'Partitioniert':'Leer'))}</td><td>${button('SMART','smart',`data-disk="${esc(disk.name)}"`,'small')}</td></tr>`).join('')}</tbody></table></div></section>
   <section class="panel"><div class="panel-heading"><h2>Snapshots</h2><span class="hint">${snapshots.length} vorhanden · Zusätzlich unabhängige Backups einplanen</span></div>${snapshots.length? snapshots.map(s=>`<div class="list-row"><span class="row-icon">◷</span><span class="row-main"><strong>${esc(s.name)}</strong><small>${bytes(s.used)} exklusiv belegt</small></span></div>`).join(''):empty('Noch keine Snapshots erstellt.')}</section><section class="panel"><div class="panel-heading"><h2>Vorhandene Ext4-/XFS-Dateisysteme</h2><span class="hint">Nur Bestandsanzeige · keine Übernahme oder Formatierung</span></div>${existingFilesystems.map(item=>`<div class="list-row"><span class="row-main"><strong>${esc(item.name)} · ${esc(item.fstype?.toUpperCase())}</strong><small>Gerätegröße: ${bytes(item.size)}</small><details><summary>Einbindung anzeigen</summary><p class="hint">${esc((item.mountpoints||[]).filter(Boolean).join(", ")||"Nicht eingehängt")}</p></details></span></div>`).join("")||empty("Keine weiteren Ext4- oder XFS-Dateisysteme erkannt.")}</section><section class="panel"><div class="panel-heading"><h2>Poolstatus</h2></div><pre class="code">${esc(storage.status)}</pre></section></div>`;
 },
 async shares() {
  managedShares = await api('/api/managed-shares');
  return heading('Freigaben','SMB-Freigaben mit klaren Lese- und Schreibrechten.',button('+ Freigabe erstellen','share-create','','primary'),'FREIGABEN')+
   `<div class="notice">Freigaben sind im lokalen Netzwerk über <strong>\\\\${esc(location.hostname)}\\Freigabename</strong> erreichbar. Melde dich mit einem angelegten SMB-Benutzer an.</div><section class="panel"><div class="table-wrap"><table><thead><tr><th>FREIGABE</th><th>LESEN</th><th>SCHREIBEN</th><th></th></tr></thead><tbody>${managedShares.map(share=>`<tr><td><div class="table-name"><span class="row-icon">▱</span><div><button class="text-link" data-action="share-edit" data-name="${esc(share.name)}"><strong>${esc(share.name)}</strong></button><div class="hint">${esc(share.path)}</div></div></div></td><td>${esc(share.readers.join(', ') || '—')}</td><td>${esc(share.writers.join(', ') || '—')}</td><td class="table-actions">${button('Zugänge und Rechte','share-edit',`data-name="${esc(share.name)}"`,'small')}${button('Freigabe entfernen','share-remove',`data-name="${esc(share.name)}"`,'small danger')}</td></tr>`).join('')}</tbody></table>${managedShares.length?'':empty('Lege deine erste Freigabe an.')}</div></section>`;
 },
 async files() {
  const shares = fileLocations(await api('/api/shares'));
  if (!shares.some(item=>item.name===currentShare)) {currentShare=shares[0]?.name || '';currentPath='';fileOffset=0;fileSearch='';}
  let data = {entries:[],total:0,limit:200,offset:0};
  if(currentShare) data=await api(`/api/files?${new URLSearchParams({share:currentShare,path:currentPath,offset:String(fileOffset),limit:'200',search:fileSearch})}`);
  if(data.total&&fileOffset>=data.total){fileOffset=Math.floor((data.total-1)/data.limit)*data.limit;data=await api(`/api/files?${new URLSearchParams({share:currentShare,path:currentPath,offset:String(fileOffset),limit:'200',search:fileSearch})}`);}
  if(!data.total)fileOffset=0;
  if(currentShare==='@system'&&typeof data.path==='string')currentPath=data.path;
  const selected = shares.find(item=>item.name===currentShare);
  const writable = selected&&!selected.blocked&&(session.user.role==='admin'||selected.writers.includes(session.user.system_user));
  const targets=shares.filter(item=>!item.blocked&&(session.user.role==='admin'||item.writers.includes(session.user.system_user)));
  const canCopy = targets.length>0;
  filesView={share:currentShare,path:currentPath,writable,targets,entries:data.entries.map(entry=>({...entry,
   readable:currentShare==='@system'?(entry.directory||entry.readable!==false):!entry.symlink,
   mutable:Boolean(writable&&(currentShare==='@system'?entry.mutable!==false:!entry.symlink))}))};
  if(window.TitanFileBrowser)return heading('Dateimanager','Wähle links einen Ort. Eine Zeile zeigt Vorschau und Details; der Name öffnet den Eintrag.','','DATEIEN')+window.TitanFileBrowser.render({...filesView,shares,data,search:fileSearch,offset:fileOffset,admin:session.user.role==='admin',owner:session.user.name,esc,bytes,date,fileUrl,breadcrumbs:fileBreadcrumbs(),uploadStatus:uploadStatus()});
  return heading('Deine Dateien. Direkt hier.','Klicke auf eine Zeile, um den Ordner oder die Dateivorschau zu öffnen.',writable?button('+ Neue Datei','file-create','','primary')+button('+ Neuer Ordner','folder-create'):'','DATEIMANAGER')+
   (currentShare==='@system'?'<div class="notice">Administratorzugriff auf das System. Änderungen an Systemdateien wirken sofort. Virtuelle Kernel- und Gerätedateien sind schreibgeschützt.</div>':'')+
   `<section class="panel"><div class="files-toolbar"><select id="share-select" aria-label="Dateibereich wählen">${shares.map(item=>`<option value="${esc(item.name)}" ${item.name===currentShare?'selected':''}>${esc(item.label||item.name)}</option>`).join('')}</select>${button('↑','file-up',`aria-label="Übergeordneten Ordner öffnen" ${currentPath?'':'disabled'}`,'small')}${fileBreadcrumbs()}${writable?(currentShare==='@system'?'':button('Papierkorb','trash-view','','small'))+`<label class="button small">↑ Hochladen<input id="file-upload" type="file" hidden multiple></label>`:''}</div>${currentShare==='@system'?`<form id="system-path-form" class="inline-form"><input name="path" value="/${esc(currentPath)}" aria-label="Systempfad" maxlength="4096"><button type="submit" class="button small">Öffnen</button></form>`:''}<form id="file-search-form" class="inline-form"><input name="search" value="${esc(fileSearch)}" maxlength="200" placeholder="Namen in diesem Ordner suchen …" aria-label="Dateien in diesem Ordner suchen"><button class="button small" type="submit">Suchen</button>${fileSearch?button('Zurücksetzen','file-search-clear','','small'):''}</form><div class="file-selection-bar" data-file-selection-bar><span data-file-selection-count aria-live="polite">0 ausgewählt</span><div>${canCopy?'<button type="button" class="button small" data-file-batch="copy" disabled>Kopieren</button>':''}${writable?'<button type="button" class="button small" data-file-batch="move" disabled>Verschieben</button>'+(currentShare==='@system'?'':'<button type="button" class="button small" data-file-batch="trash" disabled>Papierkorb</button>'):''}<button type="button" class="button small" data-file-batch="clear" disabled>Auswahl aufheben</button></div></div><p class="hint file-shortcuts">Strg+A: sichtbare Einträge auswählen · F2: umbenennen · Entf: Papierkorb / bestätigtes Löschen · Strg+S: Editor speichern</p><div class="table-wrap"><table class="file-table"><thead><tr><th class="file-check"><input type="checkbox" data-file-select-all aria-label="Alle auswählbaren Einträge dieser Seite auswählen"></th><th>NAME</th><th>GRÖSSE</th><th>GEÄNDERT</th><th>AKTIONEN</th></tr></thead><tbody>${data.entries.map((entry,index)=>{
    const path=[currentPath,entry.name].filter(Boolean).join('/'),system=currentShare==='@system';
    const readable=system?(entry.directory||entry.readable!==false):!entry.symlink;
    const mutable=writable&&(system?entry.mutable!==false:!entry.symlink);
    const selectable=readable&&!entry.symlink&&(!system||entry.mutable!==false);
    return `<tr ${readable?`class="file-row" data-open-action="${entry.directory?'folder-open':'file-preview'}" data-path="${esc(path)}"`:''}><td class="file-check">${selectable?`<input type="checkbox" data-file-select value="${index}" aria-label="${esc(entry.name)} auswählen">`:''}</td><td><button type="button" class="file-link" data-action="${entry.directory?'folder-open':'file-preview'}" data-path="${esc(path)}" ${readable?'':'disabled'}><span class="row-icon">${entry.directory?'▱':'▤'}</span>${esc(entry.name)}</button>${entry.symlink?`<small class="hint">Symbolischer Link${system?' → '+esc(entry.target||'Ziel nicht verfügbar'):' · nicht geöffnet'}</small>`:''}</td><td>${entry.directory?'—':bytes(entry.size)}</td><td class="hint">${date(entry.modified)}</td><td class="table-actions">${button('Details','file-details',`data-index="${index}"`,'small')}${entry.directory||!readable?'':`<a class="button small" href="${fileUrl(path)}" aria-label="${esc(entry.name)} herunterladen">↓</a>`}${writable&&!entry.directory&&readable&&entry.editable!==false?button('Bearbeiten','file-edit',`data-path="${esc(path)}"`,'small'):''}${canCopy&&readable&&!entry.symlink?button('Kopieren','file-transfer',`data-path="${esc(path)}" data-command="copy"`,'small'):''}${mutable?(!entry.symlink?button('Verschieben','file-transfer',`data-path="${esc(path)}" data-command="move"`,'small'):'')+button('Umbenennen','file-rename',`data-path="${esc(path)}"`,'small')+(system?'':button('Papierkorb','file-trash',`data-path="${esc(path)}"`,'small'))+(session.user.role==='admin'?button('Löschen','file-delete',`data-path="${esc(path)}"`,'small danger'):''):''}</td></tr>`;
   }).join('')}</tbody></table></div>${data.entries.length?'':empty(currentShare?(fileSearch?'Keine passenden Namen in diesem Ordner.':'Dieser Ordner wartet auf deine Dateien.'):'Für dich sind noch keine Freigaben verfügbar.','▱')}<div class="pagination"><span class="hint">${data.total?`${data.offset+1}–${data.offset+data.entries.length} von ${data.total}`:'0'} Einträge${fileSearch?' · Gefiltert':''}</span><div>${button('← Zurück','file-page',`data-offset="${Math.max(0,fileOffset-data.limit)}" ${fileOffset?'':'disabled'}`,'small')}${button('Weiter →','file-page',`data-offset="${fileOffset+data.limit}" ${data.has_more?'':'disabled'}`,'small')}</div></div></section>`;
 },
 async vms() {
  const [data,library,options,status]=await Promise.all([api('/api/vms'),api('/api/iso-library'),api('/api/vm-options').catch(()=>null),api('/api/status').catch(()=>null)]);vmsData=data.vms;
  return window.TitanManagers.renderVMs({data,library,options,status,session,esc,bytes,button,empty,pill,uploadStatus});
 },
 async users() {
  const data=await api('/api/users'); usersData=data.web;
  data.system=data.system.filter(account=>!account.removed);
  return heading('Benutzer','Benutzer für Weboberfläche und SMB-Freigaben verwalten.',button('+ Benutzer erstellen','user-create','','primary'),'BENUTZER')+
   `<div class="notice">Administratoren verwalten das NAS. Normale Benutzer sehen nur ihre freigegebenen Dateien. Das Dienstkonto <strong>${esc(data.service_user)}</strong> dient freigegebenen Apps und besitzt keinen SMB-Login. Ein aktivierter Administrator muss erhalten bleiben.</div>${data.web.some(user=>user.system_user===data.service_user)?'<div class="notice warning">Ältere Administratoren ohne eigenes SMB-Konto: Unten links das eigene Profil öffnen und Passwort ändern wählen. Mit Bestätigung des bisherigen Passworts wird ein SMB-Zugang mit deinem Web-Benutzernamen eingerichtet; vorhandene ausdrücklich zugewiesene Freigaberechte werden übernommen. Danach erneut anmelden.</div>':''}<section class="panel"><div class="table-wrap"><table><thead><tr><th>BENUTZER</th><th>ROLLE</th><th>STATUS</th><th>DATEI-/SMB-KONTO</th><th></th></tr></thead><tbody>${data.web.map(user=>`<tr><td><div class="table-name"><span class="avatar">${esc(user.name.slice(0,1).toUpperCase())}</span><strong>${esc(user.name)}${user.name===session.user.name?' · Du':''}</strong></div></td><td>${pill(user.role==='admin'?'Administrator':'Benutzer',user.role==='admin'?'purple':'gray')}</td><td>${pill(user.enabled===false?'Gesperrt':'Aktiv',user.enabled===false?'red':'')}</td><td>${esc(user.system_user)}<small class="hint">SMB: ${user.system_user===data.service_user?'Eigenes Konto noch einrichten':data.system.find(account=>account.name===user.system_user)?.smb_ready===true?'Bereit':data.system.find(account=>account.name===user.system_user)?.smb_ready===false?'Nicht bereit oder gesperrt':'Status nicht geprüft'}</small></td><td><div class="form-actions wrap">${button('Bearbeiten','user-edit',`data-name="${esc(user.name)}"`,'small')}${button('Löschen','user-remove',`data-name="${esc(user.name)}" ${user.name===session.user.name||(user.role==='admin'&&user.enabled!==false&&data.web.filter(item=>item.role==='admin'&&item.enabled!==false).length===1)?'disabled title="Das eigene Konto und der letzte aktive Administrator sind geschützt."':''}`,'small danger')}</div></td></tr>`).join('')}</tbody></table></div></section>${data.system.filter(account=>!data.web.some(user=>user.system_user===account.name)).length?`<section class="panel section-heading"><div><h2>Weitere SMB-Konten</h2><p class="hint">${esc(data.system.filter(account=>!data.web.some(user=>user.system_user===account.name)).map(account=>account.name).join(', '))}</p></div></section>`:''}`;
 },
 async backups() {
  const [data,settings,shares]=await Promise.all([api('/api/backups'),api('/api/backup/settings'),api('/api/managed-shares')]);
  backupData=data.items||data.backups||[];
  return heading('Backups','Freigaben auf ein unabhängiges Laufwerk sichern und kontrolliert wiederherstellen.',button('Jetzt sichern','backup-create',settings.target?'':'disabled','primary'),'BACKUPS')+
   (data.error?`<div class="notice warning">${esc(data.error)}</div>`:'')+
   (data.last?`<div class="notice ${data.last.ok?'':'warning'}">Letzter Sicherungslauf: ${date(data.last.time)} · ${data.last.ok?'Erfolgreich':esc(data.last.error||'Fehlgeschlagen')}</div>`:'')+
   `<form id="backup-settings-form"><div class="two-columns"><section class="panel"><div class="panel-heading"><h2>Sicherungsziel und Inhalt</h2></div>${locationField('Externes Sicherungslaufwerk','target',settings.target,{purpose:'backup',hint:'Angezeigt werden geprüfte, eingehängte Laufwerke getrennt von der Systemplatte und den Quelldaten.'})}<div class="field"><label>Freigaben sichern</label><div class="checkbox-list">${shares.map(share=>`<label><input type="checkbox" name="shares" value="${esc(share.name)}" ${settings.shares.includes(share.name)?'checked':''}>${esc(share.name)}</label>`).join('')||'<span class="hint">Zuerst eine Freigabe anlegen.</span>'}</div></div><label class="check-label"><input type="checkbox" name="include_config" ${settings.include_config?'checked':''}> NAS-Konfiguration mit sichern</label><p class="hint">VMs sicherst du auf der VM-Seite. App-Konfigurationen und freigegebene Nutzdaten haben getrennte Sicherungen.</p></section><section class="panel"><div class="panel-heading"><h2>Zeitplan und Aufbewahrung</h2></div><label class="check-label"><input type="checkbox" name="auto_backup" ${settings.auto_backup?'checked':''}> Automatische Sicherungen aktivieren</label>${selectField('Intervall','interval',[['daily','Täglich'],['weekly','Wöchentlich']],settings.interval)}<div class="form-grid">${selectField('Wochentag bei wöchentlicher Sicherung','window_day',[[0,'Montag'],[1,'Dienstag'],[2,'Mittwoch'],[3,'Donnerstag'],[4,'Freitag'],[5,'Samstag'],[6,'Sonntag']],settings.window_day)}${selectField('Uhrzeit auf dem NAS','window_hour',Array.from({length:24},(_,i)=>[i,String(i).padStart(2,'0')+':00']),settings.window_hour)}</div>${field('Anzahl Sicherungen aufbewahren','retention','number',settings.retention,'required min="1" max="100"','Ältere geprüfte Datensicherungen werden nach einem erfolgreichen Lauf entfernt.')}</section></div><div class="form-actions"><button class="button primary" type="submit">Sicherungseinstellungen speichern</button></div></form><section class="panel section-heading"><div><h2>Vorhandene Sicherungen</h2><p class="hint">${esc(settings.target||'Noch kein Ziel eingerichtet')}</p></div>${button('↻ Aktualisieren','refresh')}</section><section class="panel"><div class="table-wrap"><table><thead><tr><th>SICHERUNG</th><th>INHALT</th><th>GRÖSSE</th><th></th></tr></thead><tbody>${backupData.map(backup=>`<tr><td><strong>${esc(backup.id)}</strong><div class="hint">${date(backup.created)}</div></td><td>${backup.type==='vm'?'Virtuelle Maschine':esc((backup.shares||[]).join(', ')||'Nur NAS-Konfiguration')}${backup.include_config?' · Konfiguration':''}</td><td>${bytes(backup.bytes)}</td><td class="table-actions">${button('Prüfen','backup-verify',`data-id="${esc(backup.id)}"`,'small')}${backup.type==='vm'?button('VM wiederherstellen','vm-restore',`data-id="${esc(backup.id)}"`,'small'):button('Dateien wiederherstellen','backup-restore',`data-id="${esc(backup.id)}" ${(backup.shares||[]).length?'':'disabled'}`,'small')}${backup.include_config?button('Konfiguration exportieren','backup-config',`data-id="${esc(backup.id)}"`,'small')+button('NAS-Konfiguration wiederherstellen','backup-config-restore',`data-id="${esc(backup.id)}"`,'small danger'):''}</td></tr>`).join('')}</tbody></table></div>${backupData.length?'':empty('Nach deiner ersten Sicherung erscheinen hier die Versionen.')}</section>`;
 },
 async monitoring() {
  const data=await api('/api/monitoring');
  const labels={docker:'Docker',samba:'SMB-Freigaben',zfs:'ZFS',vms:'Virtualisierung'};
  const alerts=data.alerts||[];
  return heading('Meldungen','Dienstzustände, Laufwerke und Warnungen an einer Stelle.',button('↻ Jetzt prüfen','monitoring-check','','primary'),'MELDUNGEN')+
   `<p class="hint">Letzte Prüfung: ${data.checked?date(data.checked):'Noch keine'} · Bestätigte Warnungen bleiben sichtbar, solange ihre Ursache besteht.</p><div class="two-columns"><section class="panel"><div class="panel-heading"><h2>Dienste</h2></div>${Object.entries(data.services||{}).map(([name,service])=>`<div class="list-row"><span class="row-main"><strong>${esc(labels[name]||name)}</strong><small>${esc(service.state||'')}</small></span>${pill(service.active?'Läuft':service.installed?'Gestoppt':'Nicht eingerichtet',service.active?'':service.installed?'red':'gray')}</div>`).join('')}</section><section class="panel"><div class="panel-heading"><h2>Laufwerke</h2></div>${(data.disks||[]).map(disk=>`<div class="list-row"><span class="row-main"><strong>${esc(disk.name)}</strong><small>${esc(disk.error||[disk.health, disk.temperature!=null?disk.temperature+' °C':''].filter(Boolean).join(' · '))}</small></span>${button('Details','smart',`data-disk="${esc(disk.name)}"`,'small')}</div>`).join('')||empty('Keine SMART-fähigen Laufwerke erkannt.')}</section></div><section class="panel section-heading"><div><h2>Meldungen</h2><p class="hint">${alerts.filter(item=>item.active!==false&&!item.acknowledged).length} offene Meldungen</p></div></section><section class="panel">${alerts.map(alert=>`<div class="list-row"><span class="row-icon">${alert.active===false?'✓':'!'}</span><span class="row-main"><strong>${esc(alert.title)}</strong><p class="hint">${esc(alert.message||alert.detail)}</p><small>${date(alert.time||alert.last_seen||alert.first_seen)} · ${alert.active===false?'Behoben':alert.acknowledged?'Bestätigt':'Offen'}</small></span>${pill(alert.severity||alert.level||'Warnung',(alert.severity||alert.level)==='critical'?'red':'gray')}${alert.acknowledged?'':button('Bestätigen','alert-ack',`data-id="${esc(alert.id)}"`,'small')}</div>`).join('')||empty('Aktuell liegen keine Warnungen vor.','✓')}</section>`;
 },
 async updates() {
  let system=null,systemError='';
  const [settings,update]=await Promise.all([api('/api/settings'),api('/api/updates'),api('/api/updates/system').then(value=>{system=value;}).catch(error=>{systemError=error.message;})]);
  const currentStage=session.stage||update.current_stage;
  const matchingCheck=update.channel===settings.channel;
  const latest=matchingCheck?update.latest:null;
  const updateError=matchingCheck?update.error:null;
  const available=matchingCheck&&update.available&&!system?.reboot_required&&!system?.reboot_scheduled;
  const waiting=releaseRank[currentStage]>releaseRank[settings.channel]&&!available;
  return heading('Deine Version. Dein Update-Kanal.','Du entscheidest, welche Entwicklungsphase dein NAS künftig erhält.',button('↻ Jetzt prüfen','update-check','','primary'),'UPDATES')+
   `<div class="notice ${settings.channel==='stable'?'':'warning'}"><strong>Gewählter Kanal: ${esc(releaseLabel(settings.channel))}</strong><br>${esc(channelNotice(settings.channel))} Ein Kanalwechsel installiert keine ältere Version und ändert die Phase deiner aktuellen Installation nicht.</div>`+
   (system?.reboot_scheduled?'<div class="notice warning"><strong>Neustart geplant</strong><br>Der NAS wird in etwa einer Minute geordnet neu gestartet. Die Verbindung wird kurz unterbrochen.</div>':'')+
   (waiting?'<div class="notice">Kanal geändert: Deine aktuelle Installation bleibt erhalten, bis im gewählten Kanal eine passende neuere Version verfügbar ist.</div>':'')+
   `<div class="two-columns"><section class="panel"><div class="panel-heading"><h2>Titan</h2>${pill(updateError?'Prüfung fehlgeschlagen':available?'Update verfügbar':update.checked&&matchingCheck?'Kein neueres Update':'Noch nicht geprüft',updateError?'red':available?'purple':'gray')}</div><div class="stat-row"><div class="stat-card"><small>Installiert</small><strong>v${esc(session.version)}</strong>${pill(releaseLabel(currentStage),currentStage==='stable'?'':currentStage?'purple':'gray')}</div><div class="stat-card"><small>Neueste Version im Kanal</small><strong>${esc(latest||'—')}</strong>${latest?pill(releaseLabel(update.latest_stage),update.latest_stage==='stable'?'':'purple'):''}</div></div><p class="hint">Quelle: ${esc(settings.repository)} · Kanal: ${esc(releaseLabel(settings.channel))}<br>Letzte Prüfung dieses Kanals: ${update.checked&&matchingCheck?date(update.checked):'Noch keine'}</p>${updateError?`<div class="notice warning">${esc(updateError)}</div>`:''}${matchingCheck&&update.message?`<p class="hint">${esc(update.message)}</p>`:''}${matchingCheck&&update.notes?`<pre class="code">${esc(update.notes)}</pre>`:''}${available?button('Systemimage vorbereiten','update-install',`data-version="${esc(latest)}" ${!update.signed||session.demo?'disabled':''}`,'primary'):''}<p class="hint">${session.demo?'Demo: Die Kanalprüfung zeigt Beispieldaten. Updates werden nicht installiert.':'Signierte Systemimages werden für den nächsten Neustart vorbereitet. Deine Daten bleiben im persistenten Bereich.'}</p></section>
   <section class="panel"><div class="panel-heading"><h2>Automatische Prüfung</h2><a href="#settings?section=updates" class="text-link">Einstellungen →</a></div><div class="switch-row"><div><strong>Nach Updates suchen</strong><small>${settings.check_interval==='daily'?'Täglich':'Wöchentlich'} · Prüfung läuft im Hintergrund</small></div>${pill(settings.auto_check?'Aktiv':'Aus',settings.auto_check?'':'gray')}</div><div class="switch-row"><div><strong>Installation</strong><small>${settings.installation==='manual'?'Du startest die Installation per Klick.':'Automatisch im festgelegten Wartungsfenster.'}</small></div>${pill(settings.installation==='manual'?'Manuell':'Automatisch','gray')}</div><p class="hint">Vor dem Vorbereiten wird die Titan-Datenbank gesichert. Docker-Apps haben eigene Updates.</p></section></div>${window.TitanUpdates?.panel(system||{},systemError)||''}<section class="notice">Ein vorbereitetes Systemimage wird beim nächsten bestätigten Neustart aktiv. Ein System-Rollback stellt keine Nutzdaten oder Datenbanken zurück.</section>`;
 },
 async jobs() {
  jobsData=await api('/api/jobs');
  return heading('Aufträge','Laufende und abgeschlossene Aktionen mit Ergebnis und Fehlerdetails.',button('↻ Aktualisieren','refresh'),'VERWALTUNG')+`<section class="panel"><div class="panel-heading"><h2>Aktivität</h2><span class="hint">Aktualisiert alle 3 Sekunden</span></div><div id="job-list">${jobRows(jobsData)}</div></section>`;
 },
 async logs() {
  const data=await api('/api/logs');
  return heading('Protokoll','Anmeldungen, Einstellungen und Verwaltungsaktionen im Überblick.',button('↻ Aktualisieren','refresh'),'PROTOKOLL')+
   `<section class="panel"><div class="table-wrap"><table><thead><tr><th>ZEIT</th><th>BENUTZER</th><th>AKTION</th><th>DETAILS</th></tr></thead><tbody>${data.map(item=>`<tr><td class="hint">${date(item.time)}</td><td>${esc(item.username)}</td><td>${esc(item.action)}</td><td class="hint">${esc(item.detail)}</td></tr>`).join('')}</tbody></table></div>${data.length?'':empty('Noch keine Ereignisse aufgezeichnet.')}</section>`;
 },
 async settings() {
  const [settings,components]=await Promise.all([api('/api/settings'),api('/api/components')]);
  const section=new URLSearchParams(location.hash.split('?')[1]||'').get('section')||'';
  return window.TitanSettingsCenter.render({section,settings,components,session,esc,field,selectField,button,componentPanel,channelNotice,icon,releaseLabel});
 }

};
function appCard(app) {
 const running=app.state==='running',endpoint=window.TitanNetworks?.connection(app),fallback=`${app.scheme||'http'}://${location.hostname.includes(':')?'['+location.hostname+']':location.hostname}:${Number(app.port)}`;
 return `<article class="app-card"><div class="app-top"><div class="app-icon ${esc(app.id)}">${esc({jellyfin:'▶',syncthing:'↻',nextcloud:'☁',heimdall:'H',freshrss:'◔','calibre-web':'▤',prowlarr:'P',radarr:'R'}[app.id]||'▣')}</div>${pill(app.phase==='failed'?'Fehler':running?'Läuft':'Gestoppt',app.phase==='failed'?'red':running?'':'gray')}</div><h3>${esc(app.name)}</h3><p>Webport ${Number(app.port)} · ${esc(app.status || '')}</p>${window.TitanNetworks?`<p class="app-network-summary"><span>Container</span><code>${esc(window.TitanNetworks.summary(app))}</code></p>`:''}<div class="app-bottom"><button class="text-link" data-action="app-manage" data-id="${esc(app.id)}">Details & Anmeldung</button>${session.demo?'<span>Demo-App</span>':!running?'<span>App gestoppt</span>':`<a href="${esc(endpoint||fallback)}" target="_blank" rel="noopener">Öffnen ↗</a>`}</div></article>`;
}
function fileUrl(path, preview=false) {return `/api/file?share=${encodeURIComponent(currentShare)}&path=${encodeURIComponent(path)}${preview?'&preview=1':''}`;}
function fileLocations(shares) {return session.user.role==='admin'?[{name:'@system',label:'System /',system:true,readers:[],writers:[]},...shares]:shares;}
function fileDisplayPath(share,path) {return share==='@system'?'/'+path:share+'/'+path;}
function textBase64(value) {
 const data=new TextEncoder().encode(value);let binary='';
 for(let index=0;index<data.length;index+=8192)binary+=String.fromCharCode(...data.subarray(index,index+8192));
 return btoa(binary);
}
function fileBreadcrumbs() {
 const parts=currentPath.split('/').filter(Boolean);
 return `<div class="file-breadcrumbs" aria-label="Ordnerpfad">${button(esc(currentShare==='@system'?'System /':currentShare||'Freigabe'),'folder-open','data-path=""','small')}${parts.map((part,index)=>`<span aria-hidden="true">/</span>${button(esc(part),'folder-open',`data-path="${esc(parts.slice(0,index+1).join('/'))}"`,'small')}`).join('')}</div>`;
}
function uploadStatus() {
 const item=activeUpload;
 return item?`<div class="upload-status" role="status"><span>${esc(item.name)} · ${Math.floor(item.percent)} %</span><progress value="${item.percent}" max="100" aria-label="Upload-Fortschritt"></progress>${button('Abbrechen','upload-cancel','','small')}</div>`:'';
}
function renderUploadStatus() {const box=$('#upload-status');if(box)box.innerHTML=uploadStatus();}
function permissionsFields(accounts, readers = [], writers = [], service = 'titan-files') {
 const names=[...new Set([service,...accounts.system.filter(user=>!user.removed).map(user=>user.name),...readers,...writers])];
 return `<fieldset class="share-permissions"><legend>Zugriff pro Benutzer</legend><p class="hint">Wähle für jedes Konto genau eine Berechtigung. Ohne Zugriff ist die Freigabe für dieses Konto nicht sichtbar. Schreibzugriff enthält auch Lesen.</p>${names.map(name=>{const account=accounts.system.find(user=>user.name===name),web=(accounts.web||[]).find(user=>user.system_user===name),label=name===service?'Titan-Apps':web?web.name:name;return `<div class="share-permission-row"><div><strong>${esc(label)}</strong><small>${name===service?'App-Dateizugriff: ':'SMB-Benutzer: '}<code>${esc(name)}</code>${name===service?' · kein SMB-Login':''}${name!==service&&account?.smb_ready===false?' · SMB-Zugang nicht bereit':''}${account?.enabled===false?' · Konto gesperrt':''}</small></div><select name="permission-${esc(name)}" aria-label="Zugriff für ${esc(label)}"><option value="none" ${!readers.includes(name)&&!writers.includes(name)?'selected':''}>Kein Zugriff</option><option value="read" ${readers.includes(name)?'selected':''}>Nur Lesen</option><option value="write" ${writers.includes(name)?'selected':''}>Lesen und Schreiben</option></select></div>`;}).join('')}<p class="hint">Für die SMB-Anmeldung den angegebenen SMB-Benutzernamen und dessen Passwort verwenden. Gesperrte Konten erhalten trotz gespeicherter Rechte keinen Zugriff.</p></fieldset>`;
}
function readPermissions(data,allowEmpty=false) {
 const selected=[...data.entries()].filter(([key])=>key.startsWith('permission-'));
 const readers=selected.length?[]:data.getAll('readers'),writers=selected.length?[]:data.getAll('writers');
 for(const [key,value] of selected){const name=key.slice(11);if(!/^[a-z][a-z0-9_-]{0,30}$/.test(name)||!['none','read','write'].includes(value))throw new Error('Ungültige Benutzerberechtigung.');if(value==='read')readers.push(name);if(value==='write')writers.push(name);}
 if(readers.some(name=>writers.includes(name))||new Set(readers).size!==readers.length||new Set(writers).size!==writers.length)throw new Error('Jedes Konto darf nur eine Berechtigung erhalten.');
 if(!allowEmpty&&!writers.length&&!readers.length)throw new Error('Wähle mindestens ein berechtigtes Konto.');
 return {readers,writers};
}
function shareAccessLinks(share,access,accounts){
 const addresses=(access.host_addresses||[]).filter(item=>item.scope==='lan'&&Number(item.family)===4);
 const rows=addresses.map(item=>{const windows='\\\\'+item.address+'\\'+share.name,smb='smb://'+item.address+'/'+encodeURIComponent(share.name);return `<div class="share-address-group"><strong>${esc(item.address)} · ${esc(item.interface||'LAN')}</strong>${[['Windows',windows],['Mac und Linux',smb]].map(([label,value])=>`<div class="share-connection"><label>${label}</label><input readonly value="${esc(value)}" aria-label="${label}-Adresse für ${esc(share.name)}"><button type="button" class="button small" data-action="share-copy-link">Kopieren</button></div>`).join('')}<a class="text-link" href="${esc(smb)}">In einem SMB-Dateimanager öffnen ↗</a></div>`;}).join('');
 const service=accounts.service_user,members=[...share.writers,...share.readers],legacy=(accounts.web||[]).filter(user=>members.includes(user.system_user)&&user.system_user===service),system=accounts.system||[];
 const loginNames=names=>names.filter(name=>name!==service&&system.find(user=>user.name===name)?.smb_ready!==false).map(name=>{const user=system.find(item=>item.name===name);return name+(user?.smb_ready===true?'':' (SMB-Status nicht geprüft)');}).join(', ')||'Keine';
 const unavailable=members.filter(name=>name!==service&&system.find(user=>user.name===name)?.smb_ready===false);
 return `<section class="share-access"><h3>Mit deinen Geräten verbinden</h3>${access.service_active===false?'<div class="notice warning">Der SMB-Dienst läuft derzeit nicht. Unter Dienste beziehungsweise Einstellungen prüfen.</div>':''}${(access.warnings||[]).map(warning=>`<div class="notice warning">${esc(warning)}</div>`).join('')}${rows||'<p class="hint">Keine LAN-IPv4-Adresse gemeldet. Prüfe die Netzwerkschnittstelle des NAS.</p>'}<p class="hint" data-share-copy-status role="status" aria-live="polite"></p><p class="hint">SMB-Anmeldung mit Schreibzugriff: <strong>${esc(loginNames(share.writers))}</strong><br>Nur Lesen: <strong>${esc(loginNames(share.readers))}</strong>. Verwende das Passwort des jeweiligen Kontos.</p>${members.includes(service)?'<p class="hint">Titan-Apps haben den gewählten Dateizugriff. Das App-Servicekonto hat keinen SMB-Login.</p>':''}${unavailable.length?`<div class="notice warning">SMB-Zugang nicht bereit oder gesperrt: ${esc(unavailable.join(', '))}. Konto unter Benutzer prüfen.</div>`:''}${legacy.length?`<div class="notice warning">Für ${legacy.map(user=>esc(user.name)).join(', ')} wurde in älteren Titan-Versionen noch kein eigenes SMB-Konto eingerichtet. Unten links Profil → Passwort ändern öffnen und das bisherige Passwort bestätigen, um ein eigenes SMB-Konto mit deinem Web-Benutzernamen einzurichten.</div>`:''}</section>`;
}
function bindPage() {
 if(['docker','vms'].includes(page))window.TitanManagers?.mount($('#main'),{owner:session.user.name});
 if(page==='settings')window.TitanSettingsCenter?.mount($('#main')); 
 if(page==='updates')window.TitanUpdates?.mount($('#main'),{api});
 if(page==='storage')window.TitanSystemDisk?.mount($('#main'),{api,dialog,toast,admin:session.user.role==='admin',refresh:()=>navigate()});
 window.TitanLocations?.mount($('#main'),{api,toast});
 $('#control-search')?.addEventListener('input',event=>{const words=event.target.value.toLocaleLowerCase('de-DE').trim().split(/\s+/).filter(Boolean);let count=0;document.querySelectorAll('[data-control-search]').forEach(item=>{item.hidden=!words.every(word=>item.dataset.controlSearch.includes(word));if(!item.hidden)count++;});document.querySelectorAll('.control-section').forEach(section=>section.hidden=![...section.querySelectorAll('[data-control-search]')].some(item=>!item.hidden));$('#control-empty').hidden=Boolean(count);});
 if(page==='terminal')window.TitanTerminal?.mount($('#main'),{api,toast,dialog,esc,csrf:session.user.csrf});
 if(page==='services')window.TitanServices?.mount($('#main'),{api,action,toast,dialog,esc,pill,field,selectField,formEnd,navigate,locationField,bytes},servicesData);
 if(page==='dashboard')window.TitanDashboard?.mount($('#main'),{api,owner:session.user.name,toast,metricsFormat:{bytes,esc,demo:session.demo}});
 if(page==='files'&&filesView){window.TitanFiles?.mount($('#main'),{...filesView,api,toast,dialog,navigate,actions,esc,bytes,selectField,field,formEnd});window.TitanFileBrowser?.mount($('#main'),{...filesView,api,admin:session.user.role==='admin',owner:session.user.name,actions,toast,bytes,date,fileUrl,esc,navigate,dialog,openLocation:(share,path)=>{currentShare=share;currentPath=path;fileOffset=0;fileSearch='';navigate();}});}
 $('#f-channel')?.addEventListener('change',event=>{const notice=$('#channel-notice');notice.textContent=channelNotice(event.target.value);notice.classList.toggle('warning',event.target.value!=='stable');});
 $('#file-search-form')?.addEventListener('submit',event=>{event.preventDefault();fileSearch=String(new FormData(event.target).get('search')||'');fileOffset=0;navigate();});
 $('#system-path-form')?.addEventListener('submit',event=>{event.preventDefault();currentPath=String(new FormData(event.target).get('path')||'').replace(/^\/+|\/+$/g,'');fileOffset=0;fileSearch='';navigate();});
 $('#backup-settings-form')?.addEventListener('submit',async event=>{event.preventDefault();const form=event.target,submit=$('button[type=submit]',form);submit.disabled=true;try{const data=Object.fromEntries(new FormData(form));data.shares=new FormData(form).getAll('shares');data.auto_backup=form.elements.auto_backup.checked;data.include_config=form.elements.include_config.checked;for(const key of ['window_day','window_hour','retention'])data[key]=Number(data[key]);await api('/api/backup/settings',data);toast('Sicherungseinstellungen gespeichert.');await navigate();if(page==='backups')$('#backup-settings-form button[type=submit]')?.focus?.({preventScroll:true});}catch(error){toast(error.message,true);}finally{submit.disabled=false;}});
 document.querySelectorAll('[data-percent]').forEach(item => $('span',item).style.width=Math.min(100,Number(item.dataset.percent))+'%');
 bindCatalog();
 $('#share-select')?.addEventListener('change',event=>{currentShare=event.target.value;currentPath='';fileOffset=0;fileSearch='';navigate();});
 $('#file-upload')?.addEventListener('change',async event=>{if(activeUpload){toast('Ein Upload läuft bereits.',true);return;}const destination={share:currentShare,path:currentPath};const files=[...event.target.files];try{for(const file of files)await upload(file,false,destination);await navigate();toast('Dateien hochgeladen.');}catch(error){toast(error.message,true);}finally{renderUploadStatus();}});
 $('#iso-upload')?.addEventListener('change',async event=>{if(activeUpload){toast('Ein Upload läuft bereits.',true);return;}try{await upload(event.target.files[0],true);await navigate();toast('ISO vollständig hochgeladen.');}catch(error){toast(error.message,true);}finally{renderUploadStatus();}});
 $('#settings-form')?.addEventListener('submit',async event=>{event.preventDefault();const form=event.target;const submit=$('button[type=submit]',form);submit.disabled=true;try{const data=Object.fromEntries(new FormData(form));data.auto_check=form.elements.auto_check.checked;data.window_day=Number(data.window_day);data.window_hour=Number(data.window_hour);await api('/api/settings',data);toast('Einstellungen gespeichert.');}catch(error){toast(error.message,true);}finally{submit.disabled=false;if(document.contains?.(form)&&document.activeElement===document.body)submit.focus?.({preventScroll:true});}});
}
async function upload(file, iso, destination={share:currentShare,path:currentPath}) {
 if(!file)return;
 if(iso&&(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.iso$/.test(file.name)||!file.size))throw new Error('Wähle eine nicht leere ISO-Datei mit einfachem Dateinamen.');
 const progress={name:file.name,percent:0,controller:new AbortController()};activeUpload=progress;renderUploadStatus();
 const chunkSize=1024*1024;let offset=0,uploadId;
 try{
  do {
   if(progress.controller.signal.aborted)throw new Error('Upload abgebrochen.');
   const chunk=new Uint8Array(await file.slice(offset,offset+chunkSize).arrayBuffer());let binary='';for(let i=0;i<chunk.length;i+=8192)binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
   const body=iso?{name:file.name,offset,total:file.size,data:btoa(binary),...(uploadId?{upload_id:uploadId}:{})}:{share:destination.share,path:[destination.path,file.name].filter(Boolean).join('/'),action:'upload',offset,data:btoa(binary)};
   const response=await fetch(iso?'/api/isos':'/api/files',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.user.csrf},body:JSON.stringify(body),signal:progress.controller.signal});
   const result=await response.json();if(!response.ok)throw new Error(result.error||'Upload fehlgeschlagen.');
   if(result.offset!==offset+chunk.length)throw new Error('Server meldet eine unerwartete Upload-Position.');
   offset=result.offset;uploadId=result.upload_id;progress.percent=file.size?offset/file.size*100:100;renderUploadStatus();
  }while(offset<file.size);
 }catch(error){
  if(iso&&uploadId)try{await api('/api/isos/cancel',{upload_id:uploadId});}catch(cleanupError){/* Abandoned chunks are purged after one day. */}
  throw new Error(progress.controller.signal.aborted?'Upload abgebrochen.':error.message);
 }finally{if(activeUpload===progress)activeUpload=null;renderUploadStatus();}
}

const actions = {
 async 'component-install'(target){const component=target.dataset.component||'all';if(!['all','docker','vms'].includes(component))throw new Error('Ungültige Komponente.');target.disabled=true;try{const result=await api('/api/components/install',{component});watched.add(result.job);toast('Systemdienste werden repariert. Fortschritt unter Aufträge.');if(page==='settings'){const data=await api('/api/components');const panel=$('.component-panel');if(panel)panel.outerHTML=componentPanel(data);}}finally{target.disabled=false;}},

 close(){ if(window.TitanFileEditor?.canCloseWithin($('#dialog-body'))!==false){fileDialogRequest++;$('#dialog').close();} }, refresh(){navigate();}, 'upload-cancel'(){activeUpload?.controller.abort();},
 async 'app-info'(target){
  const app=await catalogApp(target.dataset.id),documentation=appDocumentation(app),installed=target.dataset.installed==='true';
  dialog(`${app.name} · Details & Anmeldung`,`<p class="subtitle">${esc(app.description)}</p>${appLoginPanel(app)}${app.note?`<div class="notice">${esc(app.note)}</div>`:''}${documentation?`<a class="text-link" href="${esc(documentation)}" target="_blank" rel="noopener">Vollständige App-Dokumentation ↗</a>`:''}<div class="form-actions">${button('Schließen','close')}${installed?button('App verwalten','app-manage',`data-id="${esc(app.id)}"`,'primary'):button('Installieren','app-install',`data-id="${esc(app.id)}" ${target.dataset.canInstall==='true'?'':'disabled'}`,'primary')}</div>`);
 },
 async 'app-copy-login'(target){
  const login=firstLoginMetadata(await catalogApp(target.dataset.id)),key=target.dataset.field;
  if(!['username','password'].includes(key)||!login||!Object.hasOwn(login,key))throw new Error('Diese Vorlage enthält keinen öffentlichen Standardwert.');
  if(target.disabled)return;target.disabled=true;let timer;appLoginCopyStatus(target,'Zwischenablage wird geöffnet …');
  try{
   if(!navigator.clipboard?.writeText)throw new Error('Zwischenablage nicht verfügbar.');
   await Promise.race([navigator.clipboard.writeText(login[key]),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Zwischenablage antwortet nicht.')),1500);})]);
   if(target.isConnected!==false){
    const panel=target.closest?.('.app-login-panel');if(panel)$('[data-login-copy-fallback]',panel)?.remove();
    const message=key==='username'?'Benutzername kopiert.':'Standardpasswort kopiert.';
    if(!appLoginCopyStatus(target,message))toast(message);
   }
  }catch{appLoginCopyStatus(target,'');appLoginCopyFallback(target,login[key],key);}
  finally{clearTimeout(timer);target.disabled=false;}
 },
 'app-show-login-log'(){const target=$('#app-startup-log');target?.scrollIntoView?.({behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});target?.focus?.({preventScroll:true});},
 async 'app-install'(target) {const app=catalogData.find(item=>item.id===target.dataset.id);if(!app)throw new Error('App nicht gefunden.');const [shares,networks]=await Promise.all([api('/api/shares'),window.TitanNetworks?api('/api/app-networks'):Promise.resolve(null)]);dialog(`${app.name} installieren`,`<p class="subtitle">${esc(app.description)}</p>${appLoginPanel(app)}<form><fieldset class="vm-form-section"><legend>Zugang und App-Einstellungen</legend>${field('Port für die Weboberfläche','port','number',app.default_port||(app.id==='nextcloud'?8443:app.port),'required min="1024" max="65535"')}${appInstallFields(app)}</fieldset>${networks?window.TitanNetworks.installFields(app,networks):''}<fieldset class="vm-form-section"><legend>Speicher</legend>${selectField('Nutzdaten','share',[['','Eigenes App-Verzeichnis'],...shares.filter(s=>s.writers.includes('titan-files')).map(s=>[s.name,s.name+' · '+s.path])])}<p class="hint">Wähle eine Freigabe, um dort vorhandene Daten in der App zu nutzen. Unter Freigaben kannst du vorher ein Datenvolume auswählen und der Titan-App Zugriff geben.</p><a class="text-link" href="#shares" data-action="close">Freigaben verwalten →</a></fieldset>${app.note?`<div class="notice warning">${esc(app.note)}</div>`:''}<p class="hint">Die Konfiguration bleibt im App-Verzeichnis gespeichert. Zusätzliche Ports werden von der Vorlage vorgegeben; Eingaben gelten nur für diese App.</p>${formEnd('Installieren')}`,data=>action('app_install',appInstallArguments(app,data)));if(networks)window.TitanNetworks.mountInstall($('#dialog-body'),app,networks,{api});},
 async 'app-manage'(target){
  const id=target.dataset.id,[data,recipe]=await Promise.all([api('/api/app-details?'+new URLSearchParams({app:id,tail:'150'})),catalogApp(id)]),app=data.app,container=data.container;
  const running=app.state==='running';
  dialog(`${app.name} verwalten`,`<div class="panel-heading">${pill(app.phase==='failed'?'Fehler':running?'Läuft':'Gestoppt',app.phase==='failed'?'red':running?'':'gray')}${button('↻ Aktualisieren','app-manage',`data-id="${esc(id)}"`,'small')}</div>${app.last_error?`<div class="notice warning">${esc(app.last_error)}</div>`:''}${(data.warnings||[]).map(warning=>`<p class="hint error-text">${esc(warning)}</p>`).join('')}${appLoginPanel(recipe,{logsAvailable:true})}${window.TitanNetworks?.details(container||app)||''}<div class="app-details"><div><small>Status</small><p>${esc(app.status||app.state)}</p></div><div><small>Image</small><p>${esc(container?.image||'Container noch nicht vorhanden')}</p></div><div><small>Konfiguration</small><p>${esc(data.config_path)}</p></div><div><small>Nutzdaten</small><p>${esc(data.data_path||'Eigene App-Konfiguration')}</p></div>${container?`<div><small>Gesundheit / Neustarts</small><p>${esc(container.health||'Kein Healthcheck')} · ${container.restarts} Neustarts · Exit ${container.exit_code}</p></div><div><small>Ports</small><p>${(container.ports||[]).map(port=>`${Number(port.port)}/${esc(port.protocol)} → ${esc(port.target)}`).join('<br>')||'Keine veröffentlichten Ports'}</p></div>`:''}</div><div class="form-actions wrap">${button(app.phase==='failed'?'Installation erneut versuchen':'Starten','app-action',`data-id="${esc(id)}" data-command="start" ${running&&app.phase!=='failed'?'disabled':''}`)}${button('Stoppen','app-action',`data-id="${esc(id)}" data-command="stop" ${container?'':'disabled'}`)}${button('Neustarten','app-action',`data-id="${esc(id)}" data-command="restart" ${running?'':'disabled'}`)}${!session.demo&&running?`<a class="button primary" href="${esc(window.TitanNetworks?.connection(container||app)||`${app.scheme||'http'}://${location.hostname.includes(':')?'['+location.hostname+']':location.hostname}:${Number(app.port)}`)}" target="_blank" rel="noopener">App öffnen ↗</a>`:''}</div><div class="form-actions wrap">${button('Konfiguration sichern','app-action',`data-id="${esc(id)}" data-command="backup"`)}${button('Aktualisieren','app-action',`data-id="${esc(id)}" data-command="update"`)}${button('App entfernen','app-action',`data-id="${esc(id)}" data-command="remove"`,'danger')}</div><p class="hint">Entfernen behält App-Konfiguration und Nutzdaten. Eine Konfigurationssicherung enthält keine externen Nutzdaten und ersetzt kein Datenbank-Backup.</p><h3 id="app-startup-log" tabindex="-1">App-Protokoll · Letzte 150 Logzeilen</h3><pre class="code" aria-label="App-Protokoll">${esc(data.logs||'Noch keine Logs vorhanden.')}</pre>`);
 },
 async 'app-action'(target){if(target.dataset.command==='remove'&&!confirm('Container entfernen? Deine gespeicherten App-Daten bleiben erhalten.'))return;await action('app_action',{app:target.dataset.id,action:target.dataset.command});$('#dialog').close();},
 async 'volume-create'(){
  const storage=await api('/api/storage');
  const disks=storage.disks.filter(item=>item.type==='disk'&&!item.fstype&&!item.children?.length&&!item.mountpoints?.some(Boolean)&&[false,0,'0'].includes(item.ro));
  const choices=[['ext4','Ext4 · Standard für einzelne Laufwerke'],['xfs','XFS · Alternative für große Datenmengen']].filter(([name])=>storage.filesystems?.[name]?.available);
  dialog('Ein leeres Laufwerk einrichten',`<div class="notice warning">Nur vollständig leere, unpartitionierte Laufwerke werden akzeptiert. Das gewählte Laufwerk erhält ein neues Dateisystem. Vorhandene Daten, Systemlaufwerke und eingebundene Laufwerke werden abgelehnt.</div><form>${field('Volume-Name','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${selectField('Dateisystem','filesystem',choices,'ext4')}${selectField('Leeres Laufwerk','disk',disks.map(disk=>[disk.name,disk.name+' · '+bytes(disk.size)+' · '+(disk.model||'Laufwerk')]))}${!disks.length?'<p class="hint">Kein geeignetes leeres Laufwerk vorhanden.</p>':''}${!choices.length?'<p class="hint">Dateisystem-Werkzeuge fehlen. Installiere die Speicher-Komponente im Titan-Systemimage.</p>':''}${field('Volume-Namen zur Bestätigung erneut eingeben','confirmation_name','text','','required autocomplete="off"')}${field('Exakten Laufwerkspfad bestätigen','confirmation_disk','text','','required autocomplete="off"','Beispiel: /dev/sdc. Kein anderes Laufwerk wird formatiert.')}${session.demo?'<p class="hint">Demo: Einrichtung wird ausschließlich simuliert, kein echtes Laufwerk wird verändert.</p>':''}${formEnd('Volume einrichten')}`,data=>{if(!disks.length||!choices.length)throw new Error('Es fehlen ein geeignetes Laufwerk oder Dateisystem-Werkzeuge.');return action('volume_create',Object.fromEntries(data));});
 },
 'volume-mount'(target){return action('volume_mount',{name:target.dataset.name});},
 async 'pool-create'(){const storage=await api('/api/storage');const disks=storage.disks.filter(item=>!item.fstype&&!item.children&&!item.mountpoints?.some(Boolean));dialog('ZFS-Pool erstellen',`<div class="notice warning">Ausgewählte leere Laufwerke werden für den Pool eingerichtet. Vorhandene Dateisysteme und Partitionen werden abgelehnt.</div><form>${field('Poolname','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${selectField('Layout','layout',[['mirror','Mirror · ab 2 Laufwerken'],['raidz1','RAIDZ1 · ab 3 Laufwerken'],['raidz2','RAIDZ2 · ab 4 Laufwerken']])}<div class="field"><label>Leere Laufwerke</label><div class="checkbox-list">${disks.map(item=>`<label><input type="checkbox" name="disks" value="${esc(item.name)}">${esc(item.name)} · ${bytes(item.size)}</label>`).join('')||'<span class="hint">Keine geeigneten leeren Laufwerke.</span>'}</div></div>${field('Poolname zur Bestätigung erneut eingeben','confirmation','text','','required')}${formEnd('Pool erstellen')}`,data=>action('pool_create',{name:data.get('name'),layout:data.get('layout'),disks:data.getAll('disks'),confirmation:data.get('confirmation')}));},
 'dataset-create'(target){dialog('Dataset erstellen',`<p class="subtitle">Übergeordnet: ${esc(target.dataset.parent)}</p><form>${field('Name','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${field('Speicherlimit in GB','quota_gb','number',0,'min="0" max="1000000"','0 bedeutet kein eigenes Limit.')}${formEnd()}`,data=>action('dataset_create',{parent:target.dataset.parent,name:data.get('name'),quota_gb:Number(data.get('quota_gb'))}));},
 'snapshot-create'(target){dialog('Snapshot erstellen',`<p class="subtitle">Dataset: ${esc(target.dataset.dataset)}</p><form>${field('Snapshotname','name','text','manuell-'+new Date().toISOString().slice(0,10),'required pattern="[a-z][a-z0-9_-]{0,30}"')}${formEnd()}`,data=>action('snapshot_create',{dataset:target.dataset.dataset,name:data.get('name')}));},
 'scrub'(target){return action('scrub',{pool:target.dataset.pool});},
 async smart(target){const result=await api('/api/smart?disk='+encodeURIComponent(target.dataset.disk));dialog('Laufwerkszustand',`<pre class="code">${esc(JSON.stringify(result,null,2))}</pre>`);},
 async 'share-create'(){
  const [accounts,storage]=await Promise.all([api('/api/users'),api('/api/storage')]);
  const locations=[['','Neuer Ordner auf dem Systemlaufwerk'],...(storage.volumes||[]).filter(item=>item.mounted).map(item=>['volume:'+item.name,item.name+' · '+item.filesystem.toUpperCase()]),...storage.datasets.map(item=>['dataset:'+item.name,item.name+' · ZFS'])];
  const suggested=(storage.volumes||[]).find(item=>item.mounted);
  dialog('SMB-Freigabe erstellen',`<form>${field('Freigabename','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${selectField('Speicherbereich','location',locations,suggested?'volume:'+suggested.name:'')}<p class="hint">Auf Ext4-/XFS-Volumes erhält jede Freigabe einen eigenen Ordner. Nur tatsächlich eingehängte Volumes sind auswählbar.</p>${session.user.system_user===accounts.service_user?'<div class="notice warning">Dein Administrator besitzt noch keinen eigenen SMB-Zugang. Unten links Profil → Passwort ändern öffnen und anschließend dein eigenes Konto für diese Freigabe auswählen.</div>':''}${permissionsFields(accounts,[],[...new Set([accounts.service_user,session.user.system_user].filter(Boolean))],accounts.service_user)}${formEnd()}`,data=>{const location=data.get('location');return action('share_create',{name:data.get('name'),dataset:location.startsWith('dataset:')?location.slice(8):null,volume:location.startsWith('volume:')?location.slice(7):null,...readPermissions(data)});});
 },
 async 'share-edit'(target){
  const [accounts,access]=await Promise.all([api('/api/users'),api('/api/shares/access')]),share=managedShares.find(item=>item.name===target.dataset.name);
  if(!share)throw new Error('Freigabe nicht gefunden. Bitte aktualisieren.');
  dialog('Freigabe · Verbindung und Rechte',`<p class="subtitle">${esc(share.name)} · ${esc(share.path)}</p>${shareAccessLinks(share,access,accounts)}<form>${permissionsFields(accounts,share.readers,share.writers,accounts.service_user)}<p class="hint">Die Rechte gelten für SMB und den Dateimanager. Wenn alle Konten keinen Zugriff haben, bleibt die Freigabe für SMB geschlossen. Laufende Dateizugriffe können eine erneute Verbindung benötigen.</p>${formEnd('Rechte speichern')}`,data=>action('share_update',{name:share.name,...readPermissions(data,true)}));
 },
 async 'share-copy-link'(target){const input=$('input',target.closest('.share-connection')),status=$('[data-share-copy-status]',$('#dialog-body'));try{if(!navigator.clipboard?.writeText)throw new Error('Keine Zwischenablage.');await navigator.clipboard.writeText(input.value);if(status)status.textContent='Freigabe-Adresse kopiert.';}catch{input.focus();input.select();if(status)status.textContent='Adresse markiert. Mit Strg+C oder dem Kopieren-Menü kopieren.';}},
 'share-remove'(target){
  dialog('SMB-Freigabe entfernen',`<p class="subtitle">${esc(target.dataset.name)} wird aus SMB und dem Dateimanager entfernt. Der Ordner und alle Dateien bleiben erhalten.</p><form><p>Möchtest du diese Freigabe entfernen?</p>${formEnd('Ja, Freigabe entfernen')}`,()=>{return action('share_remove',{name:target.dataset.name});});
 },
 'user-edit'(target){
  const user=usersData.find(item=>item.name===target.dataset.name);
  if(!user)throw new Error('Benutzer nicht gefunden. Bitte aktualisieren.');
  const own=user.name===session.user.name;
  const lastAdmin=user.role==='admin'&&user.enabled!==false&&usersData.filter(item=>item.role==='admin'&&item.enabled!==false).length===1;
  dialog('Benutzer bearbeiten',`<p class="subtitle">${esc(user.name)} · Dateizugriff als ${esc(user.system_user)}</p><form>${selectField('Rolle','role',[['user','Benutzer · eigene Dateien'],['admin','Administrator · vollständige Verwaltung']],user.role)}${selectField('Kontostatus','enabled',[['true','Aktiv'],['false','Gesperrt']],String(user.enabled!==false))}${field('Neues Passwort (optional)','password','password','','minlength="12" maxlength="256" autocomplete="new-password"','Leer lassen, um das bisherige Passwort zu behalten.')}${own?'<div class="notice">Dein eigenes Konto kann hier nicht gesperrt werden. Zum Ändern deines Passworts öffne unten links dein Profil.</div>':''}${lastAdmin?'<div class="notice">Mindestens ein aktiver Administrator muss erhalten bleiben.</div>':''}${user.system_user==='titan-files'?'<p class="hint">Bei diesem Konto wird nur das Webpasswort geändert. Das gemeinsame Dienstkonto erhält kein SMB-Passwort.</p>':'<p class="hint">Passwortänderungen gelten für Webanmeldung und SMB. Sperren beendet Websitzungen und verhindert neue SMB-Anmeldungen.</p>'}${formEnd('Änderungen speichern')}`,async data=>{
   const changes={name:user.name,role:data.get('role'),enabled:data.get('enabled')==='true'};
   if(own&&!changes.enabled)throw new Error('Du kannst dein eigenes Konto nicht sperren.');
   if(lastAdmin&&(!changes.enabled||changes.role!=='admin'))throw new Error('Lege zuerst einen weiteren aktiven Administrator an.');
   if(data.get('password'))changes.password=data.get('password');
   const result=await api('/api/users/update',changes);watched.add(result.job);toast('Benutzeränderung gestartet.');
  });
 },
 'user-remove'(target){
  const user=usersData.find(item=>item.name===target.dataset.name);
  if(!user)throw new Error('Benutzer nicht gefunden. Bitte aktualisieren.');
  if(user.name===session.user.name)throw new Error('Du kannst dein eigenes Konto nicht löschen.');
  if(user.role==='admin'&&user.enabled!==false&&usersData.filter(item=>item.role==='admin'&&item.enabled!==false).length===1)throw new Error('Lege zuerst einen weiteren aktiven Administrator an.');
  dialog('Benutzer löschen',`<p class="subtitle">${esc(user.name)}</p><div class="notice warning">Webzugang, SMB-Zugang und persönliche Freigabenrechte werden entfernt. Bestehende Sitzungen werden beendet. Ordner und Dateien bleiben erhalten.</div>${user.system_user==='titan-files'?'<p class="hint">Das gemeinsame Dienstkonto und dessen Freigaberechte bleiben für das NAS und Apps erhalten.</p>':''}${session.demo?'<p class="hint">Demo: Die Löschung wird ausschließlich simuliert.</p>':''}<form><p>Möchtest du diesen Benutzer löschen?</p>${formEnd('Ja, Benutzer löschen')}`,async data=>{
   const result=await api('/api/users/remove',{name:user.name,confirmation:user.name});watched.add(result.job);toast('Benutzerlöschung gestartet.');
  });
 },
 'profile-menu'(){dialog('Dein Konto',`<p class="subtitle">${esc(session.user.name)} · ${session.user.role==='admin'?'Administrator':'Dateizugriff'}</p><div class="form-actions">${button('Passwort ändern','password-change','','primary')}${session.demo?'':button('Abmelden','logout')}</div>${session.demo?'<p class="hint">Demo: Konten und Kennwörter werden ausschließlich simuliert.</p>':''}`);},
 'password-change'(){dialog('Dein Passwort ändern',`<form>${field('Bisheriges Passwort','current_password','password','','required maxlength="256" autocomplete="current-password"')}${field('Neues Passwort','password','password','','required minlength="12" maxlength="256" autocomplete="new-password"')}${field('Neues Passwort wiederholen','repeat','password','','required minlength="12" maxlength="256" autocomplete="new-password"')}<p class="hint">Nach erfolgreicher Änderung werden alle deine Websitzungen beendet. Melde dich anschließend mit dem neuen Passwort an.${session.user.system_user==='titan-files'?' Mit deinem bestätigten bisherigen Passwort wird ein eigenes SMB-Konto namens '+esc(session.user.name)+' eingerichtet. Ausdrücklich dem App-Servicekonto zugewiesene Rechte auf verfügbaren Freigaben werden für dein Konto übernommen. Das App-Servicekonto behält seinen Zugriff und erhält keinen SMB-Login.':' Das neue Passwort gilt auch für SMB.'}</p>${session.demo?'<div class="notice">Demo: Dieser Vorgang wird simuliert. Das Demo-Anmeldepasswort bleibt erhalten.</div>':''}${formEnd('Passwort ändern')}`,async data=>{if(data.get('password')!==data.get('repeat'))throw new Error('Die neuen Passwörter stimmen nicht überein.');const result=await api('/api/password',{current_password:data.get('current_password'),password:data.get('password')});if(result.job)watched.add(result.job);toast(session.demo?'Passwortänderung wird simuliert.':'Passwortänderung gestartet. Danach erneut anmelden.');});},
 async logout(){await api('/api/logout',{});$('#dialog').close();session.user=null;renderAuth(false);},
 'user-create'(){dialog('Benutzer erstellen',`<p class="subtitle">Ein Konto für die Weboberfläche und SMB.</p><form>${field('Benutzername','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}" autocomplete="off"')}${field('Passwort','password','password','','required minlength="12" maxlength="256" autocomplete="new-password"')}${selectField('Rolle','role',[['user','Benutzer · eigene Dateien'],['admin','Administrator · vollständige Verwaltung']])}${formEnd()}`,async data=>{const result=await api('/api/users',Object.fromEntries(data));watched.add(result.job);toast('Benutzer wird angelegt.');});},
 'file-page'(target){fileOffset=Number(target.dataset.offset);navigate();},
 'file-search-clear'(){fileSearch='';fileOffset=0;navigate();},
 async 'file-transfer'(target){
  const mode=target.dataset.command;
  const shares=fileLocations(await api('/api/shares')).filter(share=>!share.blocked&&(session.user.role==='admin'||share.writers.includes(session.user.system_user)));
  if(!shares.length)throw new Error('Es gibt keine Freigabe, auf die du schreiben darfst.');
  const sourceShare=currentShare,sourcePath=target.dataset.path,destination=mode==='copy'?fileCopyPath(sourcePath):sourcePath,initialPath=shares.some(share=>share.name===sourceShare)?destination.split('/').slice(0,-1).join('/'):'';
  const picker=window.TitanFolderPicker,options={pathField:'destination',shareField:'destination_share',leafField:'destination_name',initialPath};
  dialog(mode==='copy'?'Kopieren':'Verschieben',`<p class="subtitle">${esc(sourceShare)} / ${esc(sourcePath)}</p><form>${selectField('Zielfreigabe','destination_share',shares.map(share=>[share.name,share.label||share.name]),sourceShare)}${picker?field('Zielname','destination_name','text',destination.split('/').pop(),'required maxlength="255"')+picker.render(options):field('Zielpfad mit Dateiname','destination','text',destination,'required maxlength="4096"','Relativ zur Zielfreigabe. Der Zielordner muss vorhanden sein. Bestehende Dateien werden nicht überschrieben.')}<p class="hint">Ordner werden mit ihrem Inhalt ${mode==='copy'?'kopiert. Die Quelle bleibt erhalten.':'verschoben.'}</p>${formEnd(mode==='copy'?'Kopieren':'Verschieben')}`,async data=>{await api('/api/files',{share:sourceShare,path:sourcePath,action:mode,destination_share:data.get('destination_share'),destination:data.get('destination')});toast(mode==='copy'?'Kopiert.':'Verschoben.');if(page==='files')await navigate();});
  picker?.mount($('#dialog-body'),{api,toast,...options});
 },
 'folder-open'(target){currentPath=target.dataset.path;fileOffset=0;fileSearch='';navigate();},
 'file-up'(){currentPath=currentPath.split('/').slice(0,-1).join('/');fileOffset=0;fileSearch='';navigate();},
 'folder-create'(){const share=currentShare,path=currentPath;dialog('Ordner erstellen',`<form>${field('Ordnername','name','text','','required maxlength="255"')}${formEnd()}`,async data=>{const name=fileLeafName(data.get('name'));await api('/api/files',{share,path:[path,name].filter(Boolean).join('/'),action:'mkdir'});if(page==='files')await navigate();});},
 'file-create'(){const share=currentShare,path=currentPath;dialog('Neue Datei',`<p class="subtitle">${esc(fileDisplayPath(share,path))}</p><form><div class="two-columns">${field('Name ohne Dateiendung','name','text','Neue Datei','required maxlength="220"')}${field('Dateiendung (optional)','extension','text','txt','maxlength="32" placeholder="z. B. txt, md, csv, json"')}</div><label class="field">Inhalt (optional)<textarea name="content" class="file-editor" rows="10" spellcheck="false"></textarea></label><p class="hint">Ohne Inhalt wird eine leere Datei erstellt. Text wird als UTF-8 gespeichert (maximal 1 MiB). Dateiendungen erzeugen kein Office-, Bild- oder Archivformat. Vorhandene Dateien werden nicht überschrieben.</p>${formEnd('Datei erstellen')}`,async data=>{const base=fileLeafName(data.get('name')),extension=String(data.get('extension')||'').trim().replace(/^\.+/,'');if(extension&&!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,31}$/.test(extension))throw new Error('Bitte eine gültige Dateiendung ohne Pfad angeben.');const name=fileLeafName(base+(extension?'.'+extension:'')),content=String(data.get('content')||'');if(new TextEncoder().encode(content).length>1048576)throw new Error('Der Text ist größer als 1 MiB.');await api('/api/files',{share,path:[path,name].filter(Boolean).join('/'),action:'create',data:textBase64(content)});toast('Datei erstellt.');if(page==='files')await navigate();});},
 'file-details'(target){const view=filesView,entry=view?.entries[Number(target.dataset.index)];if(!entry)return;const path=[view.path,entry.name].filter(Boolean).join('/');dialog('Dateidetails',`<dl class="file-details"><dt>Name</dt><dd>${esc(entry.name)}</dd><dt>Pfad</dt><dd>${esc(fileDisplayPath(view.share,path))}</dd><dt>Typ</dt><dd>${entry.symlink?'Symbolischer Link':entry.directory?'Ordner':'Datei'}</dd><dt>Größe</dt><dd>${entry.directory?'Ordnergröße wird nicht rekursiv berechnet':bytes(entry.size)}</dd><dt>Geändert</dt><dd>${esc(date(entry.modified))}</dd>${entry.target?`<dt>Linkziel</dt><dd>${esc(entry.target)}</dd>`:''}</dl>`);},
 'file-rename'(target){const share=currentShare,path=target.dataset.path;dialog('Umbenennen',`<form>${field('Neuer Name','name','text',path.split('/').pop(),'required maxlength="255"')}${formEnd('Speichern')}`,async data=>{const parent=path.split('/').slice(0,-1).join('/'),name=fileLeafName(data.get('name'));await api('/api/files',{share,path,action:'rename',destination:[parent,name].filter(Boolean).join('/')});if(page==='files')await navigate();});},
 async 'file-edit'(target){
  const share=target.dataset.share||currentShare,path=target.dataset.path,request=++fileDialogRequest,mine=generation,user=session?.user;
  const file=await api('/api/files',{share,path,action:'read',size:1048577});
  if(request!==fileDialogRequest||mine!==generation||!user||session?.user!==user)return;
  if(file.total>1048576)throw new Error('Der Texteditor unterstützt Dateien bis 1 MiB.');
  let text;try{text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(Uint8Array.from(atob(file.data),char=>char.charCodeAt(0)));}catch(error){throw new Error('Diese Datei enthält keinen UTF-8-Text.');}
  if(text.includes('\0'))throw new Error('Binärdateien können nicht im Texteditor bearbeitet werden.');
  const crlf=text.includes('\r\n')&&!/(^|[^\r])\n/.test(text);
  if(window.TitanFileEditor){
   const options={share,path,text,file,api,toast,close:()=>$('#dialog').close()};
   if(dialog('Datei bearbeiten',window.TitanFileEditor.render(options))===false)return;
   window.TitanFileEditor.mount($('#dialog-body'),options);return;
  }
  dialog('Datei bearbeiten',`<p class="subtitle">${esc(fileDisplayPath(share,path))}</p><p class="hint">UTF-8-Text · maximal 1 MiB · Strg+S zum Speichern. Gleichzeitige Änderungen werden vor dem Speichern geprüft.</p><form><label class="field" for="file-editor">Dateiinhalt<textarea id="file-editor" name="content" class="file-editor" rows="16" spellcheck="false">${esc(text)}</textarea></label>${formEnd('Speichern')}`,async data=>{
   let content=String(data.get('content'));if(crlf)content=content.replace(/\r?\n/g,'\r\n');
   if(new TextEncoder().encode(content).length>1048576)throw new Error('Der Text ist größer als 1 MiB.');
   await api('/api/files',{share,path,action:'write',data:textBase64(content),revision:file.revision});toast('Datei gespeichert.');if(page==='files')await navigate();
  });
 },
 'file-delete'(target){
  const share=currentShare,path=target.dataset.path,confirmation=fileDisplayPath(share,path);
  dialog('Dauerhaft löschen',`<p class="subtitle">${esc(confirmation)}</p><p>Der Eintrag und sein Ordnerinhalt werden dauerhaft gelöscht.</p><form>${field('Angezeigten Pfad bestätigen','confirmation_path','text','','required autocomplete="off"')}${formEnd('Dauerhaft löschen')}`,async data=>{
   if(data.get('confirmation_path')!==confirmation)throw new Error('Der bestätigte Pfad stimmt nicht überein.');
   await api('/api/files',{share,path,action:'delete',confirmation_path:confirmation});toast('Eintrag gelöscht.');if(page==='files')await navigate();
  });
 },
 async 'file-trash'(target){if(!confirm('In den Papierkorb verschieben? Die Datei bleibt in .titan-trash auf der Freigabe erhalten.'))return;await api('/api/files',{share:currentShare,path:target.dataset.path,action:'trash'});toast('In den Papierkorb verschoben.');navigate();},
 async 'trash-view'(){await showTrash(0);},
 async 'trash-page'(target){await showTrash(Number(target.dataset.offset));},
 'trash-restore'(target){const name=target.dataset.name;dialog('Datei wiederherstellen',`<p class="subtitle">Wiederherstellung im aktuell geöffneten Ordner.</p><form>${field('Dateiname','name','text',name.replace(/^\d+-/,''),'required')}${formEnd('Wiederherstellen')}`,async data=>{await api('/api/files',{share:currentShare,action:'restore',trash_name:name,destination:[currentPath,data.get('name')].filter(Boolean).join('/')});toast('Datei wiederhergestellt.');navigate();});},
 async 'file-preview'(target){
  const share=target.dataset.share||currentShare,path=target.dataset.path,request=++fileDialogRequest,mine=generation,user=session?.user,entry=filesView?.entries.find(item=>[filesView.path,item.name].filter(Boolean).join('/')===path);
  let canEdit=Boolean(filesView?.share===share&&(window.TitanFileBrowser?.canEdit(entry,filesView)??(filesView.writable&&entry&&!entry.directory&&entry.readable&&entry.editable!==false)));
  const ext=path.split('.').pop().toLowerCase(),query=new URLSearchParams({share,path}),downloadUrl='/api/file?'+query,url=downloadUrl+'&preview=1';let html;
  if(['png','jpg','jpeg','gif','webp'].includes(ext))html=`<img class="preview-image" src="${esc(url)}" alt="${esc(path)}">`;
  else if(['mp4','webm'].includes(ext))html=`<video class="preview-video" src="${esc(url)}" controls></video>`;
  else if(['mp3','wav','ogg'].includes(ext))html=`<audio src="${esc(url)}" controls></audio>`;
  else if(ext==='pdf')html=`<iframe class="preview-frame" src="${esc(url)}" title="Dateivorschau"></iframe>`;
  else if(window.TitanFileBrowser){
   try{const response=await fetch(url,{headers:{Range:'bytes=0-1048575'}}),result=await window.TitanFileBrowser.readTextPreview(response,{limit:1048576});html=`<pre class="code">${esc(result.text)}</pre>${result.truncated?'<p class="hint">Vorschau: erste 1 MiB. Die vollständige Datei kannst du herunterladen.</p>':''}`;}
   catch(error){canEdit=false;html=empty(error.message||'Die Vorschau ist nicht verfügbar.');}
  }else html=empty('Die Textvorschau ist noch nicht geladen. Bitte die Seite neu laden.');
  if(request!==fileDialogRequest||mine!==generation||!user||session?.user!==user)return;
  dialog(path.split('/').pop(),html+`<div class="form-actions">${canEdit?button('Bearbeiten','file-edit',`data-share="${esc(share)}" data-path="${esc(path)}"`,'primary'):''}<a class="button" href="${esc(downloadUrl)}">↓ Herunterladen</a></div>`);
 },
 async 'vm-create'(){
  const [options,status]=await Promise.all([api('/api/vm-options'),api('/api/status')]);
  const isos=options.isos||[],images=options.disk_images||[];
  if(!(options.storage||[]).some(item=>item.available))throw new Error('Kein verfügbares Speicherziel für VM-Laufwerke.');
  if(!isos.length&&!images.length&&!window.TitanVMImages)throw new Error('Lade ein Installations-ISO hoch oder wähle ein QCOW2-/RAW-Laufwerksimage auf dem NAS.');
  const imported=!isos.length;
  dialog('Virtuelle Maschine erstellen',`<form class="vm-create-form">${field('Name','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${vmCpuFields(options,status)}<fieldset class="vm-form-section"><legend>Virtuelles Laufwerk</legend><div class="vm-source-options"><label class="check-label"><input type="radio" name="disk_source" value="blank" ${imported?'':'checked'} ${isos.length?'':'disabled'}> Neues Laufwerk · Betriebssystem vom ISO installieren</label><label class="check-label"><input type="radio" name="disk_source" value="image" ${imported?'checked':''} ${images.length||window.TitanVMImages?'':'disabled'}> Vorhandenes QCOW2- oder RAW-Image kopieren</label></div><div data-vm-image ${imported?'':'hidden'}>${selectField('Laufwerksimage auf dem NAS','disk_image',[['','Image auswählen'],...images.map(item=>[item.id,`${item.name} · ${bytes(item.virtual_size)} · ${item.path}`])])}${window.TitanVMImages?.fields()||''}<p class="hint">Images aus deinen Freigaben werden in ein neues VM-Laufwerk kopiert. Die Quelldatei bleibt erhalten.</p></div>${vmStorageField(options)}${field('Virtuelle Laufwerksgröße in GiB','disk_gb','number',32,'required min="8" max="10000"','Ein importiertes Image kann vergrößert werden. Partitionen und Dateisysteme anschließend im Gastsystem erweitern.')}${selectField('Installationsmedium','iso',[['','Kein ISO · Start vom Laufwerksimage'],...isos.map(name=>[name,name])],isos[0]||'')}</fieldset>${(options.warnings||[]).concat(options.cpu_topology?.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}<p class="hint">Die VM verwendet das NAT-Netzwerk des NAS. Windows benötigt passende VirtIO-Treiber.</p>${formEnd('VM erstellen')}`,data=>action('vm_create',vmCreateArguments(data,options,status)));
  const form=$('#dialog form');bindVmCpuControls(form);bindVmSourceControls(form,options);window.TitanVMImages?.mount(form,options,{api,bytes});
 },
 async 'vm-media'(target){
  const vm=vmsData.find(item=>item.id===target.dataset.id);if(!vm||vm.state!=='shut off')throw new Error('Die VM muss vollständig heruntergefahren sein.');
  const isos=await api('/api/isos');
  dialog('Installationsmedium ändern',`<p class="subtitle">${esc(vm.name)}</p><form>${selectField('CD/DVD-Medium','iso',[['','Auswerfen · von Festplatte starten'],...isos.map(name=>[name,name])],vm.iso||'')}<p class="hint">Mit ISO startet die VM zuerst vom Installationsmedium. Nach der Installation auswerfen, damit sie von der virtuellen Festplatte startet.</p>${formEnd('Speichern')}`,data=>action('vm_media',{vm:vm.id,iso:data.get('iso')||null}));
 },
 'iso-remove'(target){if(!confirm(`ISO ${target.dataset.name} löschen? Noch zugewiesene Medien können nicht entfernt werden.`))return;return action('iso_remove',{name:target.dataset.name});},
 'vm-force-off'(target){const vm=vmsData.find(item=>item.id===target.dataset.id);if(!vm)return;dialog('Ausschalten erzwingen',`<div class="notice warning">${esc(vm.name)} wird sofort ausgeschaltet. Ungespeicherte Daten im Gastsystem können verloren gehen. Nutze dies nur, wenn normales Herunterfahren nicht funktioniert.</div><form>${field('VM-Namen bestätigen','confirmation','text','','required autocomplete="off"')}${formEnd('Sofort ausschalten')}`,data=>{if(data.get('confirmation')!==vm.name)throw new Error('Der VM-Name stimmt nicht überein.');return action('vm_action',{vm:vm.id,action:'poweroff'});});},
 async 'vm-edit'(target){
  const vm=vmsData.find(item=>item.id===target.dataset.id);
  if(!vm||vm.state!=='shut off')throw new Error('Die VM muss vollständig heruntergefahren sein.');
  const [options,status]=await Promise.all([api('/api/vm-options'),api('/api/status')]);
  dialog('CPU und RAM ändern',`<p class="subtitle">${esc(vm.name)}</p><form>${vmCpuFields(options,status,vm)}${(options.cpu_topology?.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}${formEnd('Speichern')}`,data=>action('vm_update',{vm:vm.id,...vmCpuArguments(data,options,status)}));
  bindVmCpuControls($('#dialog form'));
 },
 'vm-remove'(target){
  const vm=vmsData.find(item=>item.id===target.dataset.id);
  if(!vm||vm.state!=='shut off')throw new Error('Die VM muss vollständig heruntergefahren sein.');
  dialog('Virtuelle Maschine entfernen',`<p class="subtitle">${esc(vm.name)} wird aus der VM-Verwaltung entfernt. Das virtuelle Laufwerk bleibt auf dem NAS erhalten und wird nicht gelöscht.</p><form><p>Möchtest du diese virtuelle Maschine entfernen?</p>${formEnd('Ja, VM entfernen')}`,()=>{return action('vm_remove',{vm:vm.id});});
 },
 async 'vm-backup'(target){
  const settings=await api('/api/backup/settings'),vm=vmsData.find(item=>item.id===target.dataset.id);
  if(!vm||vm.state!=='shut off')throw new Error('Die VM muss vollständig heruntergefahren sein.');
  dialog('Virtuelle Maschine sichern',`<p class="subtitle">${esc(vm.name)} · Virtuelles Laufwerk und Einstellungen auf ein externes Laufwerk sichern.</p><form>${locationField('Sicherungsziel','target',settings.target,{purpose:'backup',required:true,hint:'Wähle ein externes eingehängtes Laufwerk getrennt vom System und dem VM-Laufwerk.'})}<p class="hint">Während der Sicherung muss die VM ausgeschaltet bleiben. Dieses Ziel gilt anschließend für alle Titan-Sicherungen.</p>${formEnd('Sichern')}`,data=>action('vm_backup',{vm:vm.id,target:data.get('target')}));
 },
 async 'vm-backups'(){
  const data=await api('/api/backups');backupData=data.items||data.backups||[];
  const items=backupData.filter(item=>item.type==='vm');
  dialog('Virtuelle Maschinen wiederherstellen',items.map(item=>`<div class="list-row"><span class="row-main"><strong>${esc(item.name||item.vm_name||item.id)}</strong><small>${date(item.created)} · ${bytes(item.bytes)}</small></span>${button('Wiederherstellen','vm-restore',`data-id="${esc(item.id)}"`,'small')}</div>`).join('')||empty(data.error||'Noch keine VM-Sicherungen am konfigurierten Sicherungsziel vorhanden.'));
 },
 'vm-restore'(target){
  dialog('VM als neue Maschine wiederherstellen',`<p class="subtitle">${esc(target.dataset.id)} · Die Sicherung wird geprüft und als neue ausgeschaltete VM importiert.</p><form>${field('Name für die neue VM','name','text','','required pattern="[a-z][a-z0-9_-]{0,30}"')}${formEnd('Wiederherstellen')}`,data=>action('vm_restore',{backup:target.dataset.id,name:data.get('name')}));
 },
 async 'backup-create'(){
  const [settings,shares]=await Promise.all([api('/api/backup/settings'),api('/api/managed-shares')]);
  if(!settings.target)throw new Error('Richte zuerst ein externes Sicherungsziel ein.');
  dialog('Sicherung starten',`<p class="subtitle">Ziel: ${esc(settings.target)}</p><form><div class="field"><label>Freigaben</label><div class="checkbox-list">${shares.map(share=>`<label><input type="checkbox" name="shares" value="${esc(share.name)}" ${settings.shares.includes(share.name)?'checked':''}>${esc(share.name)}</label>`).join('')}</div></div><label class="check-label"><input type="checkbox" name="include_config" ${settings.include_config?'checked':''}> NAS-Konfiguration sichern</label><p class="hint">Ein vollständiger Sicherungslauf kann bei großen Datenmengen länger dauern. Den Status findest du unter Aufträge.</p>${formEnd('Sicherung starten')}`,data=>{const args={shares:data.getAll('shares'),include_config:data.get('include_config')==='on'};if(!args.shares.length&&!args.include_config)throw new Error('Wähle mindestens eine Freigabe oder die NAS-Konfiguration.');return action('backup_create',args);});
 },
 'backup-verify'(target){return action('backup_verify',{backup:target.dataset.id});},
 async 'backup-restore'(target){
  const shares=await api('/api/managed-shares');
  dialog('Dateien wiederherstellen',`<p class="subtitle">${esc(target.dataset.id)} · Die Freigaben aus der Sicherung erscheinen unter einem neuen Ordner. Vorhandene Dateien werden nicht überschrieben.</p><form>${selectField('Zielfreigabe','share',shares.map(share=>[share.name,share.name]))}${field('Neuer Wiederherstellungsordner','name','text','restore-'+new Date().toISOString().slice(0,10),'required pattern="[a-z][a-z0-9_-]{0,30}"')}${formEnd('Prüfen und wiederherstellen')}`,data=>action('backup_restore',{backup:target.dataset.id,share:data.get('share'),name:data.get('name')}));
 },
 'backup-config'(target){dialog('Gesicherte Konfiguration exportieren',`<p class="subtitle">Die Konfiguration aus ${esc(target.dataset.id)} wird zur Prüfung in ein separates Verzeichnis auf dem NAS exportiert. Die laufende Konfiguration bleibt erhalten.</p><form>${formEnd('Exportieren')}`,()=>action('backup_config_export',{backup:target.dataset.id}));},
 'backup-config-restore'(target){dialog('NAS-Konfiguration wiederherstellen',`<div class="notice warning">Die gesicherten Benutzer, Freigabenrechte und NAS-Einstellungen ersetzen die aktuellen Einstellungen auf diesem NAS. Aktuelle Konfigurationen werden vorher gesichert. Datenordner bleiben erhalten. Weboberfläche und SMB werden kurz gestoppt. Alle Websitzungen enden; die Anmeldung erfolgt danach mit den Konten und Passwörtern aus der Sicherung.</div><p class="hint">Nur Sicherungen dieses NAS mit weiterhin vorhandenen Benutzerkennungen und Datenpfaden können übernommen werden.${session.demo?' In der Demo wird die Wiederherstellung ausschließlich simuliert.':''}</p><form>${field('Backup-ID zur Bestätigung','confirmation','text','','required autocomplete="off"',target.dataset.id)}${formEnd('Konfiguration wiederherstellen')}`,data=>{if(data.get('confirmation')!==target.dataset.id)throw new Error('Die vollständige Backup-ID stimmt nicht überein.');return action('backup_config_restore',{backup:target.dataset.id,confirmation:data.get('confirmation')});});},
 'monitoring-check'(){return action('monitoring_check');},
 async 'alert-ack'(target){await api('/api/monitoring/ack',{id:target.dataset.id});toast('Meldung bestätigt.');await navigate();await pollAlerts();},
 'vm-action'(target){return action('vm_action',{vm:target.dataset.id,action:target.dataset.command});},
 'vm-console'(target){window.open('/console.html?vm='+encodeURIComponent(target.dataset.id),'_blank','noopener');},
 async 'app-networks'(){const data=await api('/api/app-networks');dialog('Docker-Netzwerke',window.TitanNetworks.inventoryPanel(data));},
 'app-network-remove'(target){const name=target.dataset.name;dialog('Docker-Netz entfernen',`<p>Das ungenutzte Titan-Netz <strong>${esc(name)}</strong> entfernen?</p><form>${formEnd('Ja, Netz entfernen')}`,()=>{return action('app_network_remove',{name,confirmation:name});});},
 async 'update-check'(){const result=await api('/api/updates/check',{});watched.add(result.job);toast('GitHub-Releases werden geprüft.');},
 'update-install'(target){dialog('Titan aktualisieren',`<p class="subtitle">${esc(target.dataset.version)} vorbereiten? Die Titan-Datenbank wird vorher gesichert. Das neue System startet erst nach deinem manuellen Neustart.</p><form>${formEnd('Systemimage vorbereiten')}`,()=>action('update_install',{expected_version:target.dataset.version}));},
 async 'update-rollback'(target){const selected=target.closest('.system-deployments')?.querySelector('#rollback-version')?.value;const state=await api('/api/updates/system');const choices=window.TitanUpdates.rollbackChoices(state),choice=choices.find(item=>item.digest===selected);if(!state.rollback_available||!choice)throw new Error(state.rollback_reason||'Der gewählte Rollback-Stand ist nicht mehr verfügbar. Status erneut laden.');const digest=choice.digest;dialog('System-Rollback vorbereiten',`<p>Zurück zu <strong>${esc(choice.version?'v'+choice.version:'dem ausgewählten Stand')}</strong>. Der Betriebssystemstand wechselt erst beim anschließenden Neustart. Freigaben, App-/VM-Daten und die aktuelle NAS-Konfiguration bleiben erhalten. Die Titan-Konfiguration wird vorher gesichert.</p><form><p>Möchtest du diesen Systemstand für den nächsten Start auswählen?</p>${formEnd('Ja, Rollback vorbereiten')}`,()=>{return action('update_rollback',{expected_digest:digest,confirmation:'ROLLBACK'});});},
 async 'system-reboot'(){const state=await api('/api/updates/system'),next=state.next_boot||state.staged||(state.rollback_queued?state.rollback:state.booted);if(!next||state.reboot_scheduled)throw new Error('Neustart ist bereits geplant oder der Systemstatus ist nicht verfügbar.');const digest=next.digest;dialog('NAS neu starten',`<p>Der NAS wird in etwa einer Minute geordnet neu gestartet${next.version?' mit <strong>v'+esc(next.version)+'</strong>':''}. Speichere offene Arbeiten. Laufende VMs müssen vorher heruntergefahren werden; Titan schaltet sie nicht zwangsweise aus. Apps beendet systemd beim Neustart.</p><form><p>Möchtest du das NAS jetzt neu starten?</p>${formEnd('Ja, neu starten')}`,()=>{return action('system_reboot',{expected_digest:digest,confirmation:'NEUSTART'});});},
 'system-check'(){return action('system_updates');},
 async jobs(){location.hash='jobs';},
 'job-result'(target){const job=jobsData.find(item=>item.id===target.dataset.id);if(!job)throw new Error('Auftrag nicht mehr vorhanden.');dialog(actionNames[job.action]||job.action,jobDetails(job));}

};
async function pollAlerts(){if(!session?.user||session.user.role!=='admin')return;try{const data=await api('/api/monitoring');const count=(data.alerts||[]).filter(item=>item.active!==false&&!item.acknowledged).length;$('#alert-count').hidden=!count;$('#alerts-button').setAttribute('aria-label',count?`${count} offene Meldungen`:'Meldungen anzeigen');}catch(error){/* Monitoring errors remain available on its page. */}}
async function showTrash(offset){
 const result=await api('/api/files',{share:currentShare,action:'trash_list',offset,limit:200});
 dialog('Papierkorb',result.entries.map(item=>`<div class="list-row"><span class="row-main"><strong>${esc(item.name.replace(/^\d+/, '').replace(/^-/,''))}</strong><small>${item.directory?'Ordner':bytes(item.size)}</small></span>${button('Wiederherstellen','trash-restore',`data-name="${esc(item.name)}" ${item.symlink?'disabled':''}`,'small')}</div>`).join('')+(result.entries.length?'':empty('Der Papierkorb ist leer.'))+`<div class="pagination"><span class="hint">${result.total?`${result.offset+1}–${result.offset+result.entries.length} von ${result.total}`:'0'} Einträge</span><div>${button('← Zurück','trash-page',`data-offset="${Math.max(0,offset-result.limit)}" ${offset?'':'disabled'}`,'small')}${button('Weiter →','trash-page',`data-offset="${offset+result.limit}" ${result.has_more?'':'disabled'}`,'small')}</div></div>`);
}
function jobRows(jobs) {
 const labels={queued:'Wartet',running:'Läuft',completed:'Abgeschlossen',failed:'Fehlgeschlagen'};
 return jobs.map(job=>`<div class="list-row job-row"><span class="row-icon">${job.status==='completed'?'✓':job.status==='failed'?'!':'◷'}</span><span class="row-main"><strong>${esc(actionNames[job.action]||job.action)}</strong><small>${date(job.time)} · ${esc(job.username||'System')}</small>${job.result?.error?`<small class="error-text">${esc(job.result.error)}</small>`:''}</span>${pill(labels[job.status]||job.status,job.status==='failed'?'red':job.status==='completed'?'':'gray')}${['completed','failed'].includes(job.status)?button('Ergebnis','job-result',`data-id="${esc(job.id)}"`,'small'):''}</div>`).join('')||empty('Aktuell keine Aufträge.');
}
function jobDetails(job){
 const result=job.result||{}, details=[];
 if(result.path)details.push(['Pfad',result.path]);
 if(result.disk)details.push(['Virtuelles Laufwerk',result.disk]);
 if(result.backup)details.push(['Sicherung',typeof result.backup==='string'?result.backup:result.backup.id||result.backup.path||'Erstellt']);
 if(typeof result.files==='number')details.push(['Geprüfte Einträge',result.files]);
 if(typeof result.bytes==='number')details.push(['Datenumfang',bytes(result.bytes)]);
 if(result.id&&job.action==='backup_create')details.push(['Sicherung',result.id]);
 if(result.service)details.push(['Dienst',typeof result.service==='string'?result.service:result.service.name]);
 if(result.created)details.push(['Dienstdatei','Erstellt; bei Startfehlern unter Dienste prüfen und erneut starten']);
 if(result.disk_retained)details.push(['Laufwerk','Bleibt auf dem NAS erhalten']);
 return `<p class="subtitle">${esc(result.error||result.message||(job.status==='failed'?'Auftrag fehlgeschlagen.':'Auftrag abgeschlossen.'))}</p>${details.map(([label,value])=>`<div class="field"><label>${esc(label)}</label><pre class="code">${esc(value)}</pre></div>`).join('')}${(result.warnings||[]).map(message=>`<p class="notice warning">${esc(message)}</p>`).join('')}${result.output?`<pre class="code">${esc(result.output)}</pre>`:''}`;
}
async function pollJobs(){
 if(!session?.user)return;
 try{
  const jobs=await api('/api/jobs');jobsData=jobs;
  if(page==='jobs'&&$('#job-list'))$('#job-list').innerHTML=jobRows(jobs);
  const running=jobs.filter(item=>['queued','running'].includes(item.status));$('#job-count').hidden=!running.length;$('#job-count').textContent=String(running.length);
  for(const job of jobs){
   if(!watched.has(job.id)||!['completed','failed'].includes(job.status))continue;
   watched.delete(job.id);
   if(job.action==='component_install'&&page==='settings'){const data=await api('/api/components');const panel=$('.component-panel');if(panel)panel.outerHTML=componentPanel(data);}
   if(job.status==='failed'){toast(job.result.error||'Auftrag fehlgeschlagen.',true);if(job.result.created&&page==='services')dialog(actionNames[job.action]||job.action,jobDetails(job));if(['apps','docker','vms','users','services'].includes(page))await navigate();}
   else{
    toast(job.result.message||'Auftrag abgeschlossen.');
    if(job.action==='user_update'){await boot();continue;}
    if(page!=='terminal'&&(job.result.path||job.result.disk||job.action==='system_updates'||job.action==='component_install'))dialog(actionNames[job.action]||job.action,jobDetails(job));
    if(page!=='terminal'&&!$('#settings-form')&&!$('#backup-settings-form')&&!window.TitanDashboard?.editing())await navigate();
   }
  }
 }catch(error){/* Session errors are handled by api(). */}
}

function fileLeafName(value){const name=String(value||'');if(!name||['.','..'].includes(name)||name.includes('/')||name.includes('\0')||name.length>255)throw new Error('Bitte einen einzelnen Datei- oder Ordnernamen eingeben.');return name;}
function fileCopyPath(path){const parts=path.split('/'),name=parts.pop(),dot=name.lastIndexOf('.');parts.push(dot>0?name.slice(0,dot)+'-Kopie'+name.slice(dot):name+'-Kopie');return parts.join('/');}
function fileRowTarget(event) {
 // Keep links, action buttons and text selection independent of row navigation.
 if(event.target.closest('a,button,input,select,textarea,label')||window.getSelection()?.toString())return null;
 const row=event.target.closest('.file-row');
 return row?{dataset:{action:row.dataset.openAction,path:row.dataset.path}}:null;
}
document.addEventListener('keydown',event=>{if(!event.defaultPrevented&&(event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&event.target.matches?.('textarea.file-editor')){event.preventDefault();const form=event.target.closest('form');if(form&&!$('button[type=submit]',form)?.disabled)form.requestSubmit();}});
document.addEventListener('click',async event=>{const target=event.target.closest('[data-action]')||fileRowTarget(event);if(!target||target.disabled)return;try{await actions[target.dataset.action]?.(target);}catch(error){toast(error.message,true);}});
$('#dialog').addEventListener('close',()=>{
 if($('#dialog').open)return;
 fileDialogRequest++;
 window.TitanFileEditor?.disposeWithin($('#dialog-body'));
 window.TitanLocations?.disposeWithin($('#dialog-body')); window.TitanNetworks?.disposeWithin($('#dialog-body')); window.TitanVMImages?.disposeWithin($('#dialog-body')); window.TitanFolderPicker?.disposeWithin($('#dialog-body')); window.TitanSystemDisk?.disposeWithin($('#dialog-body'));
 const saved=dialogReturnFocus;dialogReturnFocus=null;if(!saved)return;
 let target=saved.element;
 if(target.isConnected===false||target.disabled){target=[...document.querySelectorAll('#main [data-service-action], #main [data-action]')].find(item=>saved.service?item.dataset.service===saved.service&&item.dataset.serviceAction===saved.serviceAction:saved.action&&item.dataset.action===saved.action&&item.dataset.id===saved.id)||$('#main');}
 target?.focus?.({preventScroll:true});
});
$('#dialog').addEventListener('cancel',event=>{if(window.TitanFileEditor?.canCloseWithin($('#dialog-body'))===false)event.preventDefault();});
document.querySelector('.skip-link')?.addEventListener('click',event=>{event.preventDefault();$('#main')?.focus();});
$('#jobs-button').addEventListener('click',()=>actions.jobs().catch(error=>toast(error.message,true)));
$('#profile').addEventListener('click',()=>actions['profile-menu']());
$('#alerts-button')?.addEventListener('click',()=>{location.hash='monitoring';});
window.addEventListener('hashchange',()=>{if(session?.user)navigate();});
document.addEventListener('visibilitychange',syncDashboardClock);
window.addEventListener('pageshow',syncDashboardClock);
boot().catch(error=>toast(error.message,true));
