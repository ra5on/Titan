'use strict';
(function(root,factory){const center=factory();if(typeof module==='object'&&module.exports)module.exports=center;if(root)root.TitanSettingsCenter=center;})(typeof window==='undefined'?null:window,function(){
 const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const groups=[
  {title:'System',items:[
   {key:'general',title:'Server & Zugriff',description:'Anzeigename, Webzugriff und Konten',icon:'settings',href:'#settings?section=general',keywords:'hostname name server https port anmelden konto zugang'},
   {key:'updates',title:'Updates & Rollback',description:'Version, Update-Kanal und automatische Prüfung',icon:'updates',href:'#updates',keywords:'alpha beta stable release repository github zeitplan wartung'},
   {key:'components',title:'Systemkomponenten',description:'Docker, Virtualisierung und Dienste prüfen',icon:'control',href:'#settings?section=components',keywords:'kvm libvirt qemu novnc reparieren installation'}
  ]},
  {title:'Daten & Berechtigungen',items:[
   {key:'storage',title:'Speicher',description:'Laufwerke, Volumes und Systemplatte',icon:'storage',href:'#storage',keywords:'festplatte kapazität xfs ext4 zfs disk pool'},
   {key:'users',title:'Benutzer',description:'Konten, Passwörter und Zugriffsrechte',icon:'users',href:'#users',keywords:'konto anmelden login administrator passwort'},
   {key:'shares',title:'Freigaben',description:'SMB-Freigaben und Lese- und Schreibrechte',icon:'shares',href:'#shares',keywords:'samba netzwerk windows mac lesen schreiben berechtigung'}
  ]},
  {title:'Betrieb & Wartung',items:[
   {key:'services',title:'Dienste',description:'Systemdienste starten, stoppen und verwalten',icon:'services',href:'#services',keywords:'service systemd status protokolle'},
   {key:'backups',title:'Backups',description:'Sicherungsziel, Zeitplan und Wiederherstellung',icon:'backups',href:'#backups',keywords:'sicherung daten wiederherstellen retention aufbewahrung'},
   {key:'monitoring',title:'Meldungen',description:'Systemzustand und Warnungen kontrollieren',icon:'monitoring',href:'#monitoring',keywords:'warnung fehler gesundheit smart temperatur status'},
   {key:'logs',title:'Protokoll',description:'Anmeldungen und Verwaltungsaktionen nachvollziehen',icon:'logs',href:'#logs',keywords:'audit log aktivität verlauf'}
  ]}
 ];
 const sections=new Set(['general','updates','components']),labels={general:'Server & Zugriff',updates:'Updates & Kanäle',components:'Systemkomponenten'};
 const normalize=value=>String(value??'').toLocaleLowerCase('de-DE').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/ß/g,'ss');
 const stages={alpha:'Alpha',beta:'Beta',stable:'Stable'};
 let mounted=null;
 function defaultField(label,name,type,value,attributes='',hint=''){return `<div class="field"><label for="f-${escape(name)}">${escape(label)}</label><input id="f-${escape(name)}" name="${escape(name)}" type="${escape(type)}" value="${escape(value)}" ${attributes}>${hint?`<small>${escape(hint)}</small>`:''}</div>`;}
 function defaultSelect(label,name,choices,value){return `<div class="field"><label for="f-${escape(name)}">${escape(label)}</label><select id="f-${escape(name)}" name="${escape(name)}">${choices.map(([key,title])=>`<option value="${escape(key)}" ${String(key)===String(value)?'selected':''}>${escape(title)}</option>`).join('')}</select></div>`;}
 const streamKeys=['auto_check','check_interval','installation','window_day','window_hour'];
 function streamSettings(settings,kind){const fallback=kind==='system'?{auto_check:true,check_interval:'daily',installation:'manual',window_day:settings.window_day??0,window_hour:settings.window_hour??3}:{auto_check:settings.auto_check??true,check_interval:settings.check_interval||'daily',installation:settings.installation||'manual',window_day:settings.window_day??0,window_hour:settings.window_hour??3};return {...fallback,...settings.update_streams?.[kind]};}
 function formValues(form){
  const data=Object.fromEntries(new FormData(form));data.auto_check=form.elements.auto_check.checked;data.window_day=Number(data.window_day);data.window_hour=Number(data.window_hour);
  const preserved=data.update_streams;if(preserved){data.update_streams=JSON.parse(preserved);}else delete data.update_streams;
  if(form.elements.titan_auto_check){data.update_streams={};for(const kind of ['titan','system']){const value={};for(const key of streamKeys){const name=kind+'_'+key;value[key]=key==='auto_check'?form.elements[name].checked:key==='window_day'||key==='window_hour'?Number(data[name]):data[name];delete data[name];}data.update_streams[kind]=value;}Object.assign(data,data.update_streams.titan);}
  if(!form.elements.titan_auto_check&&data.update_streams&&form.elements.repository?.type!=='hidden'){data.update_streams={...data.update_streams,titan:Object.fromEntries(streamKeys.map(key=>[key,data[key]]))};}
  return data;
 }
 function preserved(settings,visible){
  const keys=['hostname','repository','channel','check_interval','installation','window_day','window_hour'];
  let html=settings.update_streams&&!visible.has('update_streams')?`<input type="hidden" name="update_streams" value="${escape(JSON.stringify(settings.update_streams))}">`:'';
  html+=keys.filter(key=>!visible.has(key)).map(key=>`<input type="hidden" name="${key}" value="${escape(settings[key])}">`).join('');
  if(!visible.has('auto_check'))html+=`<input type="checkbox" name="auto_check" hidden aria-hidden="true" tabindex="-1" ${settings.auto_check?'checked':''}>`;
  return html;
 }
 function sectionNav(section,esc){return `<nav class="sc-section-nav" aria-label="Einstellungsbereiche">${['general','updates','components'].map(key=>`<a href="${key==='updates'?'#updates':'#settings?section='+key}" ${key===section?'class="active" aria-current="page"':''}>${esc(labels[key])}</a>`).join('')}</nav>`;}
 function render(context={}){
  const esc=context.esc||escape,field=context.field||defaultField,select=context.selectField||defaultSelect,settings=context.settings||{},session=context.session||{},section=sections.has(context.section)?context.section:'',releaseLabel=context.releaseLabel||(stage=>stages[stage]||'Unbekannt');
  const heading=(title,description)=>`<header class="sc-heading"><div>${section?'<a class="sc-back" href="#settings">← Alle Einstellungen</a>':''}<h1>${esc(title)}</h1><p>${esc(description)}</p></div><a class="button small sc-diagnostics" href="/api/diagnostics?download=1">Diagnose herunterladen</a></header>`;
  if(!section){
   return `<section class="settings-center" data-settings-center>${heading('Einstellungen','Dein NAS nach Aufgaben geordnet. Wähle einen Bereich, um ihn zu verwalten.')}<div class="sc-search-row"><label class="sc-search"><span aria-hidden="true">⌕</span><span class="sr-only">Einstellungen suchen</span><input type="search" data-settings-search-input placeholder="Einstellungen suchen …" maxlength="200" autocomplete="off"></label><span class="sc-result-count" data-settings-result-count role="status" aria-live="polite">${groups.reduce((sum,group)=>sum+group.items.length,0)} Bereiche</span></div>${groups.map(group=>`<section class="sc-category" data-settings-group><h2>${esc(group.title)}</h2><div class="sc-category-grid">${group.items.map(item=>`<a class="sc-category-tile" href="${item.href}" data-settings-category="${item.key}" data-settings-search="${esc(normalize([item.title,item.description,item.keywords].join(' ')))}"><span class="sc-category-icon sc-icon-${item.key}" aria-hidden="true">${typeof context.icon==='function'?context.icon(item.icon):'<span>⚙</span>'}</span><span class="sc-category-copy"><strong>${esc(item.title)}</strong><span>${esc(item.description)}</span></span><span class="sc-category-arrow" aria-hidden="true">›</span></a>`).join('')}</div></section>`).join('')}<div class="sc-search-empty" data-settings-empty hidden><strong>Keine passenden Einstellungen gefunden</strong><p>Versuche einen anderen Begriff.</p><button class="button small" type="button" data-settings-search-reset>Suche zurücksetzen</button></div></section>`;
  }
  let body='';
  if(section==='general'){
   body=`<form id="settings-form" class="sc-settings-form">${preserved(settings,new Set(['hostname']))}<section class="panel sc-form-panel"><div class="panel-heading"><h2>Servername</h2></div>${field('Anzeigename','hostname','text',settings.hostname,'required maxlength="64"','Dieser Name erscheint in Titan. Der Linux-Systemname bleibt separat verwaltet.')}</section><section class="panel sc-form-panel"><div class="panel-heading"><h2>Zugriff auf dein NAS</h2></div><dl class="sc-access-details"><div><dt>Weboberfläche</dt><dd>HTTPS · Port 5000</dd></div><div><dt>System</dt><dd>Debian · Titan v${esc(session.version||'—')} · ${esc(releaseLabel(session.stage))}</dd></div></dl><p class="hint">Konten und Dateifreigaben verwaltest du in ihren eigenen Bereichen.</p><div class="form-actions"><a class="button small" href="#users">Benutzer verwalten</a><a class="button small" href="#shares">Freigaben verwalten</a></div></section><div class="form-actions sc-save-actions"><button class="button primary" type="submit">Einstellungen speichern</button></div></form>`;
  }else if(section==='updates'){
   const notice=typeof context.channelNotice==='function'?context.channelNotice(settings.channel):'Der Update-Kanal bestimmt, welche neuen Titan-Versionen angeboten werden.';
   const schedule=`<fieldset class="sc-update-schedule"><legend>Automatische Suche & Wartungsfenster</legend><div class="switch-row"><div><strong>Automatisch nach Updates suchen</strong><small>Auch bei geschlossenem Browser.</small></div><label class="switch"><input type="checkbox" name="auto_check" aria-label="Automatisch nach Updates suchen" ${settings.auto_check?'checked':''}><span></span></label></div>${select('Prüfintervall','check_interval',[['daily','Täglich'],['weekly','Wöchentlich']],settings.check_interval)}${select('Vorbereitung','installation',[['manual','Manuell · nur benachrichtigen'],['automatic','Automatisch im Wartungsfenster vorbereiten']],settings.installation)}<div class="form-grid">${select('Wartungstag','window_day',[[0,'Montag'],[1,'Dienstag'],[2,'Mittwoch'],[3,'Donnerstag'],[4,'Freitag'],[5,'Samstag'],[6,'Sonntag']],settings.window_day)}${select('Uhrzeit auf dem NAS','window_hour',Array.from({length:24},(_,index)=>[index,String(index).padStart(2,'0')+':00']),settings.window_hour)}</div></fieldset>`;
   body=`<form id="settings-form" class="sc-settings-form sc-update-settings">${preserved(settings,new Set(['repository','channel','auto_check','check_interval','installation','window_day','window_hour']))}<section class="panel sc-form-panel sc-update-source"><div class="panel-heading"><h2>Quelle & Freigaben</h2><a class="text-link" href="#updates">Versionsstatus öffnen →</a></div>${field('GitHub-Repository','repository','text',settings.repository,'required','Quelle für signierte Titan-Systemupdates, als owner/name.')}${select('Update-Kanal','channel',[['stable','Stable · stabile Freigaben'],['beta','Beta · Beta und Stable'],['alpha','Alpha · Alpha, Beta und Stable']],settings.channel)}<div id="channel-notice" class="notice ${settings.channel==='stable'?'':'warning'}">${esc(notice)}</div><p class="hint">Titan und Debian verwenden denselben Ablauf. Ein Kanalwechsel führt zu keinem Downgrade. Installiert: v${esc(session.version||'—')} · ${esc(releaseLabel(session.stage))}.</p></section><section class="panel sc-form-panel sc-update-schedules">${schedule}<p class="hint">Die Automatik bereitet ausschließlich geprüfte, signierte Systemstände vor. Neustarts werden immer von dir bestätigt.</p></section><div class="form-actions sc-save-actions"><button class="button primary" type="submit">Update-Einstellungen speichern</button></div></form>`;
  }else{
   body=typeof context.componentPanel==='function'?context.componentPanel(context.components||{}):'<section class="panel"><p>Der Komponentenstatus ist nicht verfügbar. Lade die Seite erneut.</p></section>';
   body+='<section class="sc-component-links"><a class="button small" href="#apps">Docker-Apps verwalten</a><a class="button small" href="#vms">Virtuelle Maschinen verwalten</a><a class="button small" href="#services">Alle Dienste anzeigen</a></section>';
  }
  if(context.formOnly)return body;
  return `<section class="settings-center" data-settings-center data-settings-section="${section}">${heading(labels[section],section==='general'?'Name und Zugänge deines Servers.':section==='updates'?'Wähle deinen Kanal und lege fest, wann Titan nach Updates sucht.':'Prüfe die installierten Komponenten und repariere ihre Dienste.')}${sectionNav(section,esc)}${body}</section>`;
 }
 function dispose(){mounted?.dispose();mounted=null;}
 function mount(scope){
  dispose();const center=scope?.querySelector('[data-settings-center]');if(!center)return null;
  const input=center.querySelector('[data-settings-search-input]'),count=center.querySelector('[data-settings-result-count]'),empty=center.querySelector('[data-settings-empty]'),reset=center.querySelector('[data-settings-search-reset]'),listeners=[];let alive=true;
  function filter(){if(!alive||!input)return;const words=normalize(input.value).trim().split(/\s+/).filter(Boolean),tiles=[...center.querySelectorAll('[data-settings-category]')];let visible=0;for(const tile of tiles){tile.hidden=!words.every(word=>String(tile.dataset.settingsSearch||'').includes(word));if(!tile.hidden)visible++;}for(const group of center.querySelectorAll('[data-settings-group]'))group.hidden=![...group.querySelectorAll('[data-settings-category]')].some(tile=>!tile.hidden);if(count)count.textContent=`${visible} ${visible===1?'Bereich':'Bereiche'}`;if(empty)empty.hidden=visible>0;}
  const listen=(node,type,callback)=>{node?.addEventListener(type,callback);if(node)listeners.push([node,type,callback]);};
  listen(input,'input',filter);listen(input,'keydown',event=>{if(event.key==='Escape'&&input.value){event.preventDefault();input.value='';filter();}});listen(reset,'click',()=>{input.value='';filter();input.focus();});
  const state={filter,dispose(){if(!alive)return;alive=false;for(const[node,type,callback]of listeners)node.removeEventListener(type,callback);listeners.length=0;}};mounted=state;filter();return state;
 }
 return {render,mount,dispose,normalize,streamSettings,formValues};
});
