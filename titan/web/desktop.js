'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanDesktop=ui;})(typeof window==='undefined'?null:window,function(){
 const tools=[['files','Dateimanager','Dateien und Ordner'],['vms','Virtuelle Maschinen','Gastsysteme und Konsole'],['docker','Docker','Container und Netzwerke'],['apps','App Store','Apps entdecken'],['storage','Speicher','Laufwerke und Volumes'],['shares','Freigaben','Zugriff im Netzwerk'],['settings','Systemsteuerung','Dein NAS einrichten'],['backups','Backups','Sichern und wiederherstellen'],['services','Dienste','Status und Steuerung'],['terminal','Terminal','Server-Konsole'],['updates','Updates','System und Rollback'],['control','Alle Werkzeuge','Verwaltung öffnen']];
 function launcher({esc,icon,user,apps=[]}){
  const visible=user?.role==='admin'?tools:tools.filter(([key])=>key==='files');
  return `<section class="desktop-launcher" data-launcher aria-labelledby="desktop-apps-title"><h2 class="desktop-section-heading" id="desktop-apps-title">Deine Anwendungen</h2><div class="desktop-apps">${visible.map(([key,name,detail])=>`<a class="desktop-app-link" data-app="${key}" href="#${key}"><span class="desktop-app-icon" data-app="${key}">${icon(key)}</span><span class="desktop-app-name">${esc(name)}</span><span class="desktop-app-detail">${esc(detail)}</span></a>`).join('')}</div></section>`;
 }
 function application({page,title,icon,user}){
  return `<div class="nas-window-bar"><div class="nas-window-title"><span class="nas-window-icon">${icon(page)}</span><span>${title}</span></div><div class="nas-window-actions"><button class="window-control" type="button" data-window-size aria-pressed="false" title="Fenster maximieren"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg><span data-window-size-label>Maximieren</span></button><a class="window-control" href="${user?.role==='admin'?'#dashboard':'#files'}" title="Zurück zum Hauptmenü"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg><span>Schließen</span></a></div></div>`;
 }
 let mounted=null;
 const windowSizes=new Map();
 const storageKey=(user,page)=>'titan-window:'+encodeURIComponent(String(user?.name||'local'))+':'+page;
 function dispose(){mounted?.destroy();mounted=null;}
 function mount({root:doc=globalThis.document,user,page,storage}={}){
  dispose();const shell=doc?.querySelector('#shell'),button=doc?.querySelector('[data-window-size]');
  if(!shell)return null;
  if(!button){delete shell.dataset.windowExpanded;return null;}
  const label=doc.querySelector('[data-window-size-label]'),frame=doc.querySelector('.nas-window');
  try{if(storage===undefined)storage=doc.defaultView?.localStorage;}catch{}
  const key=storageKey(user,page),size=windowSizes.get(key);let expanded=false,alive=true;
  // Native resize dimensions survive content refreshes (folder changes, jobs,
  // filters). CSS still clamps them to the viewport and fills mobile screens.
  if(frame?.style&&size){frame.style.width=size.width;frame.style.height=size.height;}
  try{expanded=storage?.getItem(key)==='maximized';}catch{}
  function apply(){shell.dataset.windowExpanded=String(expanded);button.setAttribute('aria-pressed',String(expanded));button.setAttribute('title',expanded?'Standardgröße wiederherstellen':'Fenster maximieren');if(label)label.textContent=expanded?'Wiederherstellen':'Maximieren';}
  function toggle(){if(!alive)return;expanded=!expanded;try{storage?.setItem(key,expanded?'maximized':'normal');}catch{}apply();}
  button.addEventListener('click',toggle);apply();
  mounted={toggle,get expanded(){return expanded;},destroy(){alive=false;if(frame?.style?.width&&frame?.style?.height)windowSizes.set(key,{width:frame.style.width,height:frame.style.height});button.removeEventListener('click',toggle);delete shell.dataset.windowExpanded;}};
  return mounted;
 }
 return{launcher,application,mount,dispose,storageKey,tools};
});
