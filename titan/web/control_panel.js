'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanControlPanel=ui;})(typeof window==='undefined'?null:window,function(){
 const groups=[
  ['Dateifreigabe und Berechtigungen',[
   ['shares','Freigegebene Ordner','shares','Ordner, SMB-Zugriff und Berechtigungen'],
   ['users','Benutzer','users','Konten, Kennwörter und Zugriffsrechte']]],
  ['System',[
   ['general','Allgemein','settings','Servername und Zugriff'],
   ['updates','Updates & Rollback','updates','Version, Kanal und Wiederherstellung'],
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
  const hub=`<div class="cp-overview" data-cp-overview><header class="cp-overview-heading"><h1>Systemsteuerung</h1><label class="cp-search"><span class="sr-only">Systemsteuerung durchsuchen</span><input type="search" placeholder="Einstellung suchen …" data-cp-search></label></header>${groups.map(([title,children])=>`<section class="cp-category" data-cp-category><h2>${esc(title)}</h2><div class="cp-icon-grid">${children.map(([id,name,glyph,description])=>`<a href="${link(id)}" data-cp-item data-search="${esc((name+' '+description).toLocaleLowerCase('de-DE'))}"><span class="cp-color-icon" data-app="${glyph}">${symbol(glyph)}</span><strong>${esc(name)}</strong><small>${esc(description)}</small></a>`).join('')}</div></section>`).join('')}<p class="empty" data-cp-empty hidden>Keine passende Einstellung gefunden.</p></div>`;
  return `<section class="cp-window" data-control-panel><header class="cp-toolbar"><a href="#settings" class="button small" aria-label="Alle Einstellungen anzeigen">${symbol('control')}<span>Alle Einstellungen</span></a><span class="cp-current">${esc(selected?.[1]||'Übersicht')}</span><label class="cp-mobile-select"><span class="sr-only">Einstellungsbereich</span><select data-cp-select><option value="">Übersicht</option>${items.map(([id,name])=>`<option value="${id}" ${id===section?'selected':''}>${esc(name)}</option>`).join('')}</select></label><a class="button small cp-diagnostics" href="/api/diagnostics?download=1">Diagnose</a></header><div class="cp-layout">${nav}<div class="cp-content" tabindex="-1">${section?content:hub}</div></div></section>`;
 }
 function mount(scope){const root=scope?.querySelector('[data-control-panel]');if(!root)return;const search=root.querySelector('[data-cp-search]');search?.addEventListener('input',()=>{const words=search.value.toLocaleLowerCase('de-DE').trim().split(/\s+/);let count=0;root.querySelectorAll('[data-cp-item]').forEach(item=>{item.hidden=!words.every(word=>item.dataset.search.includes(word));if(!item.hidden)count++;});root.querySelectorAll('[data-cp-category]').forEach(group=>group.hidden=![...group.querySelectorAll('[data-cp-item]')].some(item=>!item.hidden));root.querySelector('[data-cp-empty]').hidden=count>0;});root.querySelector('[data-cp-select]')?.addEventListener('change',event=>{root.ownerDocument.defaultView.location.hash=link(event.target.value);});}
 return {groups,resolve,internal,render,mount};
});
