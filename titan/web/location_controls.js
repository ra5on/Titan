'use strict';
// Directory selection reuses the administrator's existing file browser API.
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const clean=value=>'/'+String(value||'').split('/').filter(Boolean).join('/');
 const within=(path,root)=>root==='/'||path===root||path.startsWith(root+'/');
 const states=new Map();
 function field(label,name,value='',{purpose='directory',required=false,hint=''}={}) {
  return `<div class="field location-field" data-location-picker data-purpose="${esc(purpose)}"><label for="location-${esc(name)}">${esc(label)}</label><select id="location-${esc(name)}" data-location-root ${required?'required':''} aria-label="${esc(label)} auswählen"><option value="">Speicherorte werden geladen …</option></select><input name="${esc(name)}" value="${esc(value)}" data-location-value ${required?'required':''} readonly aria-label="Ausgewählter Ordner"><details data-location-browser><summary>Unterordner auswählen</summary><div class="location-toolbar"><button type="button" class="button small" data-location-up>↑ Übergeordneter Ordner</button><span data-location-current></span></div><div class="location-entries" data-location-entries></div><button type="button" class="button small" data-location-next hidden>Weitere Einträge</button></details><small data-location-status role="status"></small>${hint?`<small>${esc(hint)}</small>`:''}</div>`;
 }
 function disposeWithin(root) {for(const [widget,state] of states)if(root===widget||root?.contains?.(widget)){state.dispose();states.delete(widget);}}
 async function mount(root,ctx) {
  const widgets=[...root.querySelectorAll('[data-location-picker]')];if(!widgets.length)return;
  let data;
  try{data=await ctx.api('/api/storage-locations');}catch(error){for(const widget of widgets){const status=widget.querySelector('[data-location-status]');if(status)status.textContent='Speicherorte nicht erreichbar: '+error.message;}return;}
  for(const widget of widgets){
   if(widget.isConnected===false)continue;
   states.get(widget)?.dispose();
   const select=widget.querySelector('[data-location-root]'),value=widget.querySelector('[data-location-value]'),browser=widget.querySelector('[data-location-browser]'),entries=widget.querySelector('[data-location-entries]'),up=widget.querySelector('[data-location-up]'),current=widget.querySelector('[data-location-current]'),status=widget.querySelector('[data-location-status]'),next=widget.querySelector('[data-location-next]');
   const locations=(data.items||[]).filter(item=>widget.dataset.purpose!=='backup'||item.backup_eligible);
   let disposed=false,revision=0,offset=0,currentRoot='',path=clean(value.value);
   const chosen=locations.filter(item=>value.value&&within(path,clean(item.path))).sort((a,b)=>b.path.length-a.path.length)[0];
   select.innerHTML='<option value="">'+(widget.dataset.purpose==='backup'?'Sicherungslaufwerk auswählen':'Kein Arbeitsverzeichnis')+'</option>'+locations.map(item=>`<option value="${esc(clean(item.path))}">${esc(item.label)}</option>`).join('');
   if(chosen){select.value=clean(chosen.path);currentRoot=select.value;}else{select.value='';if(value.value)status.textContent='Der bisherige Ordner ist aktuell keinem verfügbaren Speicherort zugeordnet. Wähle ein erreichbares Ziel.';}
   if(!locations.length)status.textContent=widget.dataset.purpose==='backup'?'Kein geeignetes externes Laufwerk gefunden. Ein separates beschreibbares Laufwerk zuerst einhängen.':'Keine Speicherorte gefunden.';
   if(data.warnings?.length)status.textContent+=' '+data.warnings.join(' ');
   current.setAttribute?.('aria-live','polite');current.setAttribute?.('aria-atomic','true');
   const reflect=()=>{current.textContent=path;up.disabled=!currentRoot||path===currentRoot;browser.hidden=!currentRoot;};reflect();
   async function load(append=false){
    if(!currentRoot||disposed)return;
    const request=++revision;status.textContent='Ordner werden geladen …';if(!append){offset=0;entries.innerHTML='';}
    try{const result=await ctx.api('/api/files?'+new URLSearchParams({share:'@system',path:path.slice(1),offset:String(offset),limit:'200'}));if(disposed||request!==revision||widget.isConnected===false)return;
     const folders=(result.entries||[]).filter(item=>item.directory&&item.readable!==false&&!item.symlink);
     const html=folders.map(item=>`<button type="button" class="location-folder" data-location-folder="${esc(item.name)}"><span aria-hidden="true">▱</span>${esc(item.name)}<span aria-hidden="true">→</span></button>`).join('');
     if(append)entries.insertAdjacentHTML('beforeend',html);else entries.innerHTML=html;
     offset=Number(result.offset||0)+Number(result.limit||200);next.hidden=offset>=Number(result.total||0);
     status.textContent=!entries.children.length&&next.hidden?'Keine weiteren Unterordner. Dieser Ordner ist ausgewählt.':'Der angezeigte Ordner ist ausgewählt.';
    }catch(error){if(!disposed&&request===revision)status.textContent='Ordner nicht erreichbar: '+error.message;}
   }
   const onRoot=()=>{revision++;currentRoot=select.value;path=currentRoot||'/';value.value=currentRoot;reflect();status.textContent=currentRoot?'Der Ordner ist ausgewählt. Unterordner kannst du darunter öffnen.':'';if(browser.open)load();};
   const onToggle=()=>{if(browser.open)return load();};
   const onUp=()=>{if(path===currentRoot)return;path=clean(path.split('/').slice(0,-1).join('/'));if(!within(path,currentRoot))path=currentRoot;value.value=path;reflect();load();};
   const onFolder=event=>{const button=event.target.closest?.('[data-location-folder]');if(!button)return;const name=button.dataset.locationFolder;if(!name||name==='.'||name==='..'||name.includes('/'))return;path=clean(path+'/'+name);value.value=path;reflect();value.focus?.({preventScroll:true});load();};
   const onNext=()=>load(true);
   select.addEventListener('change',onRoot);browser.addEventListener('toggle',onToggle);up.addEventListener('click',onUp);entries.addEventListener('click',onFolder);next.addEventListener('click',onNext);
   const state={dispose(){disposed=true;revision++;select.removeEventListener('change',onRoot);browser.removeEventListener('toggle',onToggle);up.removeEventListener('click',onUp);entries.removeEventListener('click',onFolder);next.removeEventListener('click',onNext);}};states.set(widget,state);
  }
 }
 window.TitanLocations={field,mount,disposeWithin,clean,within};
})();
