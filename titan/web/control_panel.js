'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanControlPanel=ui;})(typeof window==='undefined'?null:window,function(){
 const groups=[
  ['Dateifreigabe und Berechtigungen',[
   ['shares','Freigegebene Ordner','shares','Ordner, SMB-Zugriff und Berechtigungen'],
   ['users','Benutzer','users','Konten, Kennwörter und Zugriffsrechte'],
   ['groups','Gruppen und Rechte','users','Mitgliedschaften und vererbte Zugriffe']]],
  ['System',[
   ['general','Allgemein','settings','Servername und Zugriff'],
   ['security','Sicherheit','settings','Anmeldeschutz, Zwei-Faktor-Anmeldung und Sitzungen'],
   ['updates','Updates & Rollback','updates','Titan, System und Sicherheitsupdates'],
   ['monitoring','Systemzustand','monitoring','Dienste, Laufwerke und Warnungen'],
   ['components','Komponenten','control','Docker, QEMU und Systemdienste']]],
  ['Anwendungen und Wartung',[
   ['services','Dienste','services','Start, Stopp und Autostart'],
   ['backups','Datensicherung','backups','Sicherungsziel, Zeitplan und Versionen'],
   ['logs','Protokoll','logs','Anmeldungen und Verwaltungsaktionen']]]
 ];
 const items=groups.flatMap(group=>group[1]),pages=new Set(items.map(item=>item[0]).filter(id=>!['general','components'].includes(id)));
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function resolve(hash){const [root,query]=String(hash||'').replace(/^#/,'').split('?');if(!['settings','control'].includes(root))return null;const value=new URLSearchParams(query||'').get('section')||'';const section=items.some(item=>item[0]===value)?value:'';return {section,page:pages.has(section)?section:'settings'};}
 function link(id){return '#settings'+(id?'?section='+id:'');}
 function internal(hash){const root=String(hash).replace(/^#/,'').split('?')[0];return pages.has(root)?link(root):hash;}
 function render(section,content,{icon,esc=escape}={}){
  const selected=items.find(item=>item[0]===section),symbol=id=>typeof icon==='function'?icon(id):'';
  const nav=`<aside class="cp-sidebar"><a class="cp-home ${section?'':'active'}" href="#settings" ${section?'':'aria-current="page"'}>${symbol('control')}<span>Übersicht</span></a>${groups.map(([title,children])=>`<section><h2>${esc(title)}</h2>${children.map(([id,name,glyph])=>`<a href="${link(id)}" ${id===section?'class="active" aria-current="page"':''}>${symbol(glyph)}<span>${esc(name)}</span></a>`).join('')}</section>`).join('')}</aside>`;
  const tile=([id,name,glyph,description])=>`<div class="cp-tile" data-cp-item data-search="${esc((name+' '+description).toLocaleLowerCase('de-DE'))}"><a href="${link(id)}"><span class="cp-color-icon" data-app="${glyph}">${symbol(glyph)}</span><strong>${esc(name)}</strong><small>${esc(description)}</small></a><button type="button" class="cp-pin" data-cp-pin="${id}" aria-label="${esc(name)} als Favorit merken" aria-pressed="false" title="Als Favorit merken">☆</button></div>`;
  const hub=`<div class="cp-overview" data-cp-overview><header class="cp-overview-heading"><h1>Systemsteuerung</h1><div class="cp-overview-tools"><div class="cp-view-switch" role="group" aria-label="Ansicht der Systemsteuerung"><button type="button" data-cp-view="grid" aria-pressed="true" title="Symbole">Symbole</button><button type="button" data-cp-view="list" aria-pressed="false" title="Liste">Liste</button></div><label class="cp-search"><span class="sr-only">Systemsteuerung durchsuchen</span><input type="search" placeholder="Einstellung suchen …" data-cp-search></label></div></header><section class="cp-category cp-favorites" data-cp-favorites hidden><h2>Favoriten</h2><div class="cp-favorites-grid" data-cp-favorite-items></div></section>${groups.map(([title,children])=>`<section class="cp-category" data-cp-category><h2>${esc(title)}</h2><div class="cp-icon-grid">${children.map(tile).join('')}</div></section>`).join('')}<p class="empty" data-cp-empty hidden>Keine passende Einstellung gefunden.</p></div>`;
  return `<section class="cp-window" data-control-panel data-section="${esc(section)}"><header class="cp-toolbar"><a href="#settings" class="button small" aria-label="Alle Einstellungen anzeigen">${symbol('control')}<span>Alle Einstellungen</span></a><span class="cp-current">${esc(selected?.[1]||'Übersicht')}</span><label class="cp-mobile-select"><span class="sr-only">Einstellungsbereich</span><select data-cp-select><option value="">Übersicht</option>${items.map(([id,name])=>`<option value="${id}" ${id===section?'selected':''}>${esc(name)}</option>`).join('')}</select></label><a class="button small cp-diagnostics" href="/api/diagnostics?download=1">Diagnose</a></header><div class="cp-layout">${nav}<div class="cp-content" tabindex="-1">${section?content:hub}</div></div></section>`;
 }
 const allowed=new Set(items.map(item=>item[0]));
 function normalizePreferences(value){return {view:value?.view==='list'?'list':'grid',favorites:Array.isArray(value?.favorites)?[...new Set(value.favorites.filter(id=>allowed.has(id)))].slice(0,items.length):[]};}
 function readPreferences(storage,userName){try{return normalizePreferences(JSON.parse(storage.getItem('titan.control-panel.'+encodeURIComponent(userName||'local'))));}catch{return normalizePreferences(null);}}
 function writePreferences(storage,userName,value){try{storage.setItem('titan.control-panel.'+encodeURIComponent(userName||'local'),JSON.stringify(normalizePreferences(value)));return true;}catch{return false;}}
 function mount(scope,{userName='local'}={}){
  const root=scope?.querySelector('[data-control-panel]');if(!root)return;
  const win=root.ownerDocument.defaultView;let storage;try{storage=win.localStorage;}catch{}
  const state=readPreferences(storage,userName),search=root.querySelector('[data-cp-search]');
  function filter(){if(!search)return;const words=search.value.toLocaleLowerCase('de-DE').trim().split(/\s+/).filter(Boolean);let count=0;
   root.querySelectorAll('[data-cp-item]').forEach(item=>{item.hidden=!words.every(word=>item.dataset.search.includes(word));if(!item.hidden)count++;});
   root.querySelectorAll('[data-cp-category]').forEach(group=>group.hidden=![...group.querySelectorAll('[data-cp-item]')].some(item=>!item.hidden));
   root.querySelector('[data-cp-favorites]').hidden=Boolean(words.length)||!state.favorites.length;root.querySelector('[data-cp-empty]').hidden=count>0;
  }
  function update(){root.dataset.view=state.view;root.querySelectorAll('[data-cp-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.cpView===state.view)));
   root.querySelectorAll('[data-cp-pin]').forEach(button=>{const active=state.favorites.includes(button.dataset.cpPin);button.setAttribute('aria-pressed',String(active));button.textContent=active?'★':'☆';const name=items.find(item=>item[0]===button.dataset.cpPin)?.[1]||'';button.setAttribute('aria-label',name+(active?' aus Favoriten entfernen':' als Favorit merken'));button.title=active?'Aus Favoriten entfernen':'Als Favorit merken';});
   const favoriteItems=root.querySelector('[data-cp-favorite-items]');if(favoriteItems)favoriteItems.innerHTML=state.favorites.map(id=>{const item=items.find(item=>item[0]===id);return `<a class="cp-favorite-link" href="${link(id)}"><strong>${escape(item[1])}</strong><span aria-hidden="true">↗</span></a>`;}).join('');filter();
  }
  search?.addEventListener('input',filter);
  root.querySelectorAll('[data-cp-pin]').forEach(button=>button.addEventListener('click',()=>{const id=button.dataset.cpPin;state.favorites=state.favorites.includes(id)?state.favorites.filter(value=>value!==id):[...state.favorites,id];writePreferences(storage,userName,state);update();}));
  root.querySelectorAll('[data-cp-view]').forEach(button=>button.addEventListener('click',()=>{state.view=button.dataset.cpView==='list'?'list':'grid';writePreferences(storage,userName,state);update();}));
  root.querySelector('[data-cp-select]')?.addEventListener('change',event=>{win.location.hash=link(event.target.value);});update();
 }
 return {groups,resolve,internal,render,mount,normalizePreferences,readPreferences,writePreferences};
});
