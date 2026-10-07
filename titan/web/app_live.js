'use strict';
(function(root){let current=null;const valid=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
 function render(metrics,{bytes}){const m=metrics||{};return `<div class="app-live-grid"><span>CPU <strong>${valid(m.cpu_percent)?m.cpu_percent.toLocaleString('de-DE',{maximumFractionDigits:1})+' %':'—'}</strong></span><span>RAM <strong>${valid(m.memory_bytes)?bytes(m.memory_bytes):'—'}</strong></span><span>Laufwerk-I/O gesamt <strong>${valid(m.disk_read_bytes)?bytes(m.disk_read_bytes):'—'} / ${valid(m.disk_write_bytes)?bytes(m.disk_write_bytes):'—'}</strong></span></div>`;}
 function dispose(){current?.();current=null;}
 function mount(main,{api,bytes}){dispose();if(!main.querySelector('[data-app-live],[data-app-web-status],[data-app-web-link]'))return;let alive=true,busy=false;const doc=main.ownerDocument;
  async function refresh(){if(!alive||busy||doc.hidden)return;busy=true;try{
   const [metrics,apps]=await Promise.allSettled([api('/api/app-metrics'),api('/api/apps')]);if(!alive)return;
   if(metrics.status==='fulfilled')for(const node of main.querySelectorAll('[data-app-live]'))node.innerHTML=render(metrics.value.apps[node.dataset.appLive],{bytes});
   else for(const node of main.querySelectorAll('[data-app-live]'))node.textContent='Messwerte momentan nicht erreichbar.';
   if(apps.status==='fulfilled'){const records=new Map((apps.value.installed||[]).map(app=>[app.id,app]));
    for(const node of main.querySelectorAll('[data-app-web-status]')){const app=records.get(node.dataset.appWebStatus);if(app)node.textContent=app.web_message||app.status||'';}
    for(const node of main.querySelectorAll('[data-app-web-link]')){const app=records.get(node.dataset.appWebLink);const url=app?.web_available===true?root?.TitanNetworks?.connection(app)||'':'';node.hidden=!url;if(url){node.href=url;node.setAttribute('aria-disabled','false');}else{node.removeAttribute('href');node.setAttribute('aria-disabled','true');}}
   }
  }finally{busy=false;}}
  const timer=setInterval(()=>void refresh(),5000),visible=()=>{if(!doc.hidden)void refresh();};doc.addEventListener('visibilitychange',visible);current=()=>{alive=false;clearInterval(timer);doc.removeEventListener('visibilitychange',visible);};void refresh();
 }

 const ui={render,mount,dispose};if(root)root.TitanAppLive=ui;if(typeof module==='object')module.exports=ui;
})(typeof window==='undefined'?null:window);
