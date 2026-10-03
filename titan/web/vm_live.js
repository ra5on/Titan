'use strict';
(function(root){
 let current=null;const histories=new Map();
 const finite=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
 function render(vm,{bytes,esc}){
  const m=vm.metrics||{},number=value=>Number(value).toLocaleString('de-DE',{maximumFractionDigits:1}),rate=value=>finite(value)?bytes(value)+'/s':'—';
  const cpu=!['running','paused','blocked','in shutdown','pmsuspended'].includes(vm.state)?'0 %':finite(m.cpu_percent)?number(m.cpu_percent)+' %':vm.state==='running'?'Messung läuft':'0 %';
  const active=['running','paused','blocked','in shutdown','pmsuspended'].includes(vm.state);
  const ram=active?m.memory_resident_bytes:0,ramLabel='RAM-Verbrauch auf dem NAS';
  const history=histories.get(vm.id)||[],line=history.map((value,index)=>`${index*100/Math.max(1,history.length-1)},${30-value*.3}`).join(' ');
  return `<div class="vm-live-grid"><div><small>CPU live · ${esc(vm.cpus)} vCPU</small><strong>${cpu}</strong>${history.length>1?`<svg class="vm-sparkline" viewBox="0 0 100 30" role="img" aria-label="CPU-Verlauf"><polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`:''}</div><div><small>${ramLabel}</small><strong>${finite(ram)?bytes(ram):'—'}</strong><span>${active?bytes(Number(vm.memory_mb)*1024**2)+' Maximum':'VM ausgeschaltet'}</span></div><div><small>Laufwerk belegt</small><strong>${finite(m.disk_allocated_bytes)?bytes(m.disk_allocated_bytes):'—'}</strong><span>${bytes(vm.virtual_size||Number(vm.disk_gb)*1024**3)} Kapazität</span></div><div><small>Laufwerk lesen / schreiben</small><strong>${rate(m.disk_read_bps)} / ${rate(m.disk_write_bps)}</strong><span>Netzwerk ↓ ${rate(m.network_rx_bps)} ↑ ${rate(m.network_tx_bps)}</span></div></div>`;
 }
 function dispose(){current?.destroy();current=null;}
 function mount(main,{api,bytes,esc,onStateChange}){dispose();if(!main.querySelector('[data-vm-live]'))return;let alive=true,busy=false;const doc=main.ownerDocument;
  async function refresh(){if(!alive||busy||doc.hidden)return;busy=true;try{const data=await api('/api/vms');if(!alive)return;for(const vm of data.vms||[]){if(!['running','paused','blocked','in shutdown','pmsuspended'].includes(vm.state))histories.delete(vm.id);if(finite(vm.metrics?.cpu_percent)){const history=histories.get(vm.id)||[];history.push(vm.metrics.cpu_percent);histories.set(vm.id,history.slice(-30));}for(const node of main.querySelectorAll('[data-vm-live]'))if(node.dataset.vmLive===vm.id){if(node.dataset.vmState&&node.dataset.vmState!==vm.state){onStateChange?.();return;}node.dataset.vmState=vm.state;node.innerHTML=render(vm,{bytes,esc});}}const active=(data.vms||[]).filter(vm=>['running','paused','blocked','in shutdown','pmsuspended'].includes(vm.state)),known=active.every(vm=>finite(vm.metrics?.memory_resident_bytes)),total=active.reduce((sum,vm)=>sum+(vm.metrics?.memory_resident_bytes||0),0);main.querySelectorAll('[data-vm-total-memory]').forEach(node=>node.textContent=known?bytes(total):'Nicht ermittelt');}catch{if(alive)for(const node of main.querySelectorAll('[data-vm-live]'))node.textContent='Messwerte momentan nicht erreichbar.';}finally{busy=false;}}
  const timer=setInterval(refresh,5000);const visibility=()=>{if(!doc.hidden)refresh();};doc.addEventListener('visibilitychange',visibility);current={destroy(){alive=false;clearInterval(timer);doc.removeEventListener('visibilitychange',visibility);}};refresh();
 }
 const ui={render,mount,dispose};if(root)root.TitanVMLive=ui;if(typeof module==='object')module.exports=ui;
})(typeof window==='undefined'?null:window);
