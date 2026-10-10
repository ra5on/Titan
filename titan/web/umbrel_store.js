'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanUmbrelStore=ui;})(typeof window==='undefined'?null:window,function(){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let cleanup=null;
 const category=value=>({media:'media',networking:'network',network:'network',privacy:'privacy',passwords:'privacy',files:'files',file_management:'files',automation:'automation',finance:'finance',bitcoin:'finance',crypto:'finance',developer:'developer',ai:'ai',social:'social',photography:'photos',photos:'photos'}[String(value||'').toLowerCase()]||'productivity');
 function render({catalog={},installed={},admin=false,demo=false,integrated=false}={}){
  const source=catalog.umbrel||{},rows=Array.isArray(installed)?installed:installed.installed||[],ids=new Set(rows.map(row=>row.id));
  const apps=(catalog.apps||[]).filter(row=>row.umbrel_catalog),blocked=Array.isArray(source.blocked)?source.blocked:[];
  return `<section class="apps-center umbrel-store" data-umbrel-store data-umbrel-loaded="${source.loaded===true}" aria-label="Umbrel Appkatalog"><header class="ac-heading"><div><h2>Umbrel-Katalog</h2><p>Deine Apps auf deinem Titan.</p></div><button class="button" data-umbrel-refresh ${!admin||demo?'disabled':''}>${source.loaded?'Katalog aktualisieren':'Katalog laden'}</button></header><p data-umbrel-status role="status">${source.loaded?`${apps.length} integrierte Apps · ${esc(source.total)} Pakete im Katalog`:'Lade den offiziellen Katalog, um verfügbare Anwendungen zu entdecken.'}</p>${integrated?'':'<label class="ac-search">Im Umbrel-Katalog suchen<input type="search" data-umbrel-search aria-label="Im Umbrel-Katalog suchen" autocomplete="off"></label>'}<div class="ac-app-grid">${apps.map(app=>`<article class="ac-app-card" data-umbrel-card ${integrated?`data-store-card="${esc(app.id)}" data-store-installed="${ids.has(app.id)}" data-store-app-category="${esc(category(app.category))}" data-store-search-text="${esc([app.name,app.description,app.category].join(' '))}"`:''} data-search="${esc([app.name,app.description,app.category].join(' ').toLocaleLowerCase('de'))}"><span class="ac-app-icon" aria-hidden="true">${esc((app.name||'?').slice(0,1))}</span><div class="ac-app-copy"><span class="ac-eyebrow">${esc(app.category)}</span><h3>${esc(app.name)}</h3><p>${esc(app.description)}</p><small>${esc(app.version||'')} · ${esc(app.containers||1)} ${(app.containers||1)===1?'Dienst':'Dienste'}${ids.has(app.id)?' · Installiert':''}</small></div><button class="button" data-umbrel-app="${esc(app.id)}" ${!admin||demo?'disabled':''}>${ids.has(app.id)?'Verwalten':'Installieren'}</button></article>`).join('')}</div><p data-umbrel-empty ${apps.length?'hidden':''}>Keine integrierte App gefunden.</p>${blocked.length?`<details><summary>${blocked.length} weitere Pakete benötigen noch Integration</summary><p>Diese Pakete sind noch nicht installierbar. Fehlende Voraussetzungen werden nicht übersprungen.</p><ul>${blocked.map(row=>`<li><strong>${esc(row.name)}</strong> · ${esc(row.reason)}</li>`).join('')}</ul></details>`:''}<p class="hint">Apps behalten ihre eigenen Lizenzen. Katalogquelle: <a href="https://github.com/getumbrel/umbrel-apps" target="_blank" rel="noopener noreferrer">Umbrel App Store</a></p></section>`;
 }
 function mount(scope,ctx){
  dispose();const panel=scope.querySelector('[data-umbrel-store]');if(!panel)return()=>{};
  const controller=new AbortController();let alive=true,busy=false;
  const state=()=>panel.querySelector('[data-umbrel-status]');
  const request=path=>ctx.api(path,undefined,{signal:controller.signal});
  const locked=value=>{busy=value;for(const button of panel.querySelectorAll('button'))button.disabled=value||!ctx.admin||ctx.demo;};
  const fail=error=>{if(alive)state().textContent=error?.message||'Die App-Aktion ist fehlgeschlagen.';};
  const filter=()=>{const query=(panel.querySelector('[data-umbrel-search]')?.value||'').trim().toLocaleLowerCase('de');let visible=0;for(const card of panel.querySelectorAll('[data-umbrel-card]')){card.hidden=!card.dataset.search.includes(query);if(!card.hidden)visible++;}panel.querySelector('[data-umbrel-empty]').hidden=visible>0;};
  async function install(id){
   const [catalog,installed,storage]=await Promise.all([request('/api/catalog'),request('/api/apps'),request('/api/storage-locations')]);if(!alive)return;
   const app=(catalog.apps||[]).find(row=>row.id===id&&row.umbrel_catalog);if(!app)throw Error('Diese App ist nicht mehr im aktuellen Katalog verfügbar.');
   if((installed.installed||[]).some(row=>row.id===id)){ctx.openPackage(id);return;}
   const locations=(storage.storage||[]).filter(row=>(!app.retained_storage_id||row.id===app.retained_storage_id)&&row.available!==false&&!row.blocked&&row.writable!==false&&(!Array.isArray(row.capabilities)||row.capabilities.includes('apps')));
   if(!locations.length)throw Error(app.retained_storage_id?'Der bisherige App-Speicher ist nicht verfügbar. Verbinde ihn, um die vorhandenen Daten wiederzuverwenden.':'Zuerst einen beschreibbaren App-Speicher einrichten.');
   const fields=app.install_schema||[];
   if(fields.some(field=>field.type!=='number'))throw Error('Diese App benötigt eine zusätzliche Einrichtung.');
   const html=`${app.retained_installation?'<p>Deine vorhandenen Daten werden mit der zuletzt installierten App-Version wieder geöffnet. Ein Versionswechsel erfolgt anschließend über die App-Verwaltung.</p>':''}<p>${esc(app.description)}</p><p>${esc(app.first_login?.instructions||app.note||'')}</p><form><label>Speicher<select name="storage_id">${locations.map(row=>`<option value="${esc(row.id)}" ${row.id===storage.default_storage?'selected':''}>${esc(row.label||row.id)}</option>`).join('')}</select></label><label>Webport<input name="port" type="number" required min="1024" max="65535" value="${esc(app.default_port)}"></label>${fields.map(field=>`<label>${esc(field.label)}<input name="${esc(field.key)}" type="number" required min="${esc(field.min)}" max="${esc(field.max)}" value="${esc(field.default)}"></label>`).join('')}<p>Die App speichert ihre Daten auf dem gewählten Speicher. Beim Deinstallieren bleiben sie erhalten.</p><button class="button primary" type="submit">Installieren</button></form>`;
   ctx.dialog(app.name+' installieren',html,async values=>{const options=Object.fromEntries(fields.map(field=>[field.key,Number(values.get(field.key))]));await ctx.action('app_install',{app:id,port:Number(values.get('port')),storage_id:values.get('storage_id'),options},{wait:true,signal:controller.signal});if(alive){ctx.toast?.('App installiert. Die Ersteinrichtung erfolgt in der App.');ctx.reload();}});
  }
  const click=async event=>{const node=event.target.closest?.('[data-umbrel-refresh],[data-umbrel-app]');if(!node||!panel.contains(node)||node.disabled||busy||!ctx.admin||ctx.demo)return;locked(true);try{if(node.hasAttribute('data-umbrel-refresh')){state().textContent='Katalog wird geladen und geprüft …';await ctx.action('app_store_refresh',{store:'umbrel'},{wait:true,signal:controller.signal});if(alive)ctx.reload();}else await install(node.dataset.umbrelApp);}catch(error){if(error?.name!=='AbortError')fail(error);}finally{if(alive)locked(false);}};
  panel.addEventListener('click',click);panel.addEventListener('input',filter);
  // A first visit loads the official catalog; failed/offline loads keep a
  // visible retry button and do not silently loop. Existing caches stay usable.
  if(panel.dataset.umbrelLoaded==='false'&&ctx.admin&&!ctx.demo){
   const button=panel.querySelector('[data-umbrel-refresh]');void click({target:button});
  }
  cleanup=()=>{alive=false;controller.abort();panel.removeEventListener('click',click);panel.removeEventListener('input',filter);};return cleanup;
 }
 function dispose(){cleanup?.();cleanup=null;}
 return {render,mount,dispose};
});
