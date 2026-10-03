'use strict';
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root)root.TitanResources=ui;})(typeof window==='undefined'?null:window,function(){
 let current=null;
 const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
 const measured = value => typeof value === 'number' && Number.isFinite(value);
 const percentage = value => measured(value) && value >= 0 && value <= 100 ? value : null;
 const number = value => value.toLocaleString('de-DE', {maximumFractionDigits:1});
 const time = value => new Date(value * 1000).toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
 function metricValues(status) {
  const total = status.memory_total, used = status.memory_occupied ?? status.memory_used;
  return {
   cpu:percentage(status.cpu_percent),
   memory:measured(total) && total > 0 && measured(used) && used >= 0 && used <= total ? used / total * 100 : null,
   temperature:measured(status.cpu_temperature) ? status.cpu_temperature : null,
  };
 }
 function historySamples(history) {
  const samples = new Map();
  for (const item of Array.isArray(history) ? history : []) {
   if (!item || !measured(item.time) || item.time <= 0) continue;
   samples.set(item.time, {time:item.time,cpu_percent:percentage(item.cpu_percent),memory_percent:percentage(item.memory_occupied_percent ?? item.memory_percent)});
  }
  return [...samples.values()].sort((a,b) => a.time-b.time).slice(-180);
 }
 function metricChart(history, {demo = false} = {}) {
  const samples = historySamples(history);
  const measuredSamples = samples.filter(item => item.cpu_percent !== null || item.memory_percent !== null);
  if (measuredSamples.length < 2) return '<div class="metrics-chart-empty"><span aria-hidden="true">⌁</span><p>Der Verlauf baut sich mit den Messungen auf.</p></div>';
  const first = samples[0].time, last = samples.at(-1).time;
  const x = item => 32 + (item.time-first) / (last-first) * 318;
  const y = value => 15 + (100-value) / 100 * 75;
  const series = (field, className) => {
   const segments = [];
   let segment = [];
   for (const item of samples) {
    if (item[field] === null) { if(segment.length) segments.push(segment); segment = []; }
    else segment.push(item);
   }
   if (segment.length) segments.push(segment);
   return segments.map(points => points.length === 1
    ? `<circle class="${className}" cx="${x(points[0]).toFixed(2)}" cy="${y(points[0][field]).toFixed(2)}" r="2.5"/>`
    : `<path class="${className}" d="${points.map((item,index)=>`${index?'L':'M'}${x(item).toFixed(2)} ${y(item[field]).toFixed(2)}`).join(' ')}"/>`).join('');
  };
  const count = measuredSamples.length;
  const description = demo ? 'Demo · Beispielverlauf' : 'Echte Messungen seit dem Start der Verwaltung';
  return `<div class="metrics-history"><div class="metrics-chart-heading"><span>CPU und RAM im Verlauf</span><div class="metrics-chart-legend"><span class="cpu-key">CPU</span><span class="memory-key">RAM</span></div></div><svg class="metrics-chart" viewBox="0 0 360 112" role="img" aria-label="CPU- und RAM-Auslastung von ${escape(time(first))} bis ${escape(time(last))}. ${count} Messpunkte. Fehlende Messungen bleiben Lücken."><title>${demo?'Demo: Beispieldaten in Prozent':'Tatsächlich gemessene Auslastung in Prozent'}</title><path class="chart-grid" d="M32 15H350M32 52.5H350M32 90H350"/><text class="chart-axis" x="0" y="19">100</text><text class="chart-axis" x="12" y="94">0</text>${series('memory_percent','chart-memory')}${series('cpu_percent','chart-cpu')}<text class="chart-axis" x="32" y="109">${escape(time(first))}</text><text class="chart-axis" x="350" y="109" text-anchor="end">${escape(time(last))}</text></svg><p class="metric-note history-note">${description} · ${count} Messpunkte</p></div>`;
 }
 function resourceMetrics(status, format = {}) {
  const esc = format.esc || escape;
  const bytes = format.bytes || (value => measured(value) ? `${number(value / 1024 ** 3)} GiB` : 'Nicht ermittelt');
  const values = metricValues(status);
  const meter = (value, label, className = '') => value === null
   ? '<div class="meter unavailable" aria-hidden="true"></div>'
   : `<div class="meter ${className}" data-percent="${value}" role="meter" aria-label="${label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value.toFixed(1)}"><span></span></div>`;
  const sensors = (Array.isArray(status.temperatures) ? status.temperatures : []).filter(sensor => sensor && measured(sensor.current));
  const temperature = values.temperature === null ? 'Kein CPU-Sensor' : `${number(values.temperature)} °C`;
  const load = measured(status.load) ? number(status.load) : 'Nicht ermittelt';
  const uptime = measured(status.uptime) && status.uptime >= 0 ? `${Math.floor(status.uptime/86400)} Tage, ${Math.floor(status.uptime/3600)%24} Std.` : 'Nicht ermittelt';
  const memory = values.memory === null ? 'Nicht ermittelt' : `${esc(bytes(status.memory_occupied ?? status.memory_used))} von ${esc(bytes(status.memory_total))}`;
  const errors = status.telemetry_errors && typeof status.telemetry_errors === 'object' ? Object.values(status.telemetry_errors).filter(value => typeof value === 'string' && value) : [];
  return `<div class="resource-metrics"><div class="resource-metric"><div class="metric-label"><span><span class="metric-key cpu-key" aria-hidden="true"></span>CPU-Auslastung</span><strong>${values.cpu === null ? 'Messung läuft' : number(values.cpu)+' %'}</strong></div>${meter(values.cpu,'CPU-Auslastung')}<p class="metric-note">Lastdurchschnitt (1 Min.): ${load} · ${esc(status.cpus || '—')} logische CPUs</p></div><div class="resource-metric"><div class="metric-label"><span><span class="metric-key memory-key" aria-hidden="true"></span>RAM belegt · inklusive Cache</span><strong>${values.memory === null ? '—' : number(values.memory)+' %'}</strong></div>${meter(values.memory,'Arbeitsspeicher belegt','teal')}<p class="metric-note">${memory}</p><details class="resource-details"><summary>RAM-Details</summary><dl class="memory-breakdown"><div><dt>Bedarf (geschätzt)</dt><dd>${esc(bytes(status.memory_demand ?? (measured(status.memory_total)&&measured(status.memory_available)?status.memory_total-status.memory_available:null)))}</dd></div><div><dt>Verfügbar für Anwendungen</dt><dd>${esc(bytes(status.memory_available))}</dd></div><div><dt>Vollständig frei</dt><dd>${esc(bytes(status.memory_free))}</dd></div><div><dt>Dateicache / rückgewinnbarer Cache</dt><dd>${esc(bytes(status.memory_cached))}</dd></div><div><dt>Kernel-Puffer</dt><dd>${esc(bytes(status.memory_buffers))}</dd></div></dl></details></div>${metricChart(status.status_history,{demo:Boolean(format.demo)})}${values.temperature!==null?`<div class="sensor-summary"><span class="sensor-label">CPU-Temperatur</span><strong class="${values.temperature === null?'muted':''}">${temperature}</strong></div>`:''}${sensors.length ? `<div class="sensor-readings" aria-label="Erkannte Temperatursensoren">${sensors.slice(0,6).map(sensor => `<span title="${esc(sensor.label)}">${esc(sensor.label)} <strong>${number(sensor.current)} °C</strong></span>`).join('')}${sensors.length>6?`<span>+ ${sensors.length-6} weitere Sensoren</span>`:''}</div>` : ''}<div class="resource-summary"><div><small>Laufzeit</small><strong>${uptime}</strong></div><div><small>Letzte Messung</small><strong data-metrics-updated>${measured(status.telemetry_sampled_at)?escape(time(status.telemetry_sampled_at)):'Noch keine'}</strong></div></div>${errors.length?`<details class="telemetry-details"><summary>Messhinweise (${errors.length})</summary>${errors.map(message=>`<p class="hint">${esc(message)}</p>`).join('')}</details>`:''}</div>`;
 }

 function mount(main,{api,metricsFormat={}}){
  dispose();const live=main.querySelector('[data-live-resources]');if(!live)return;
  const doc=main.ownerDocument;let alive=true,busy=false;
  function paint(status){if(!alive)return;const expanded=live.querySelector('.resource-details')?.open;live.innerHTML=resourceMetrics(status,metricsFormat);if(expanded)live.querySelector('.resource-details').open=true;live.querySelectorAll('[data-percent]').forEach(e=>{const bar=e.querySelector('span');if(bar)bar.style.width=e.dataset.percent+'%';});}
  async function refresh(){if(!alive||busy||doc.hidden)return;busy=true;try{const status=await api('/api/status');paint(status);}catch{if(alive){const label=live.querySelector('[data-metrics-updated]');if(label)label.textContent='Verbindung unterbrochen';}}finally{busy=false;}}
  const timer=doc.defaultView.setInterval(refresh,10000);doc.addEventListener('visibilitychange',refresh);
  current={destroy(){alive=false;doc.defaultView.clearInterval(timer);doc.removeEventListener('visibilitychange',refresh);}};
  live.querySelectorAll('[data-percent]').forEach(e=>{const bar=e.querySelector('span');if(bar)bar.style.width=e.dataset.percent+'%';});return current;
 }
 function dispose(){current?.destroy();current=null;}
 return {metricValues,historySamples,metricChart,resourceMetrics,mount,dispose};
});
