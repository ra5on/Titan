'use strict';
// Keep layout changes local to the existing cards; persistence is per signed-in user.
(function (root, factory) {
 const dashboard = factory();
 if (typeof module === 'object' && module.exports) module.exports = dashboard;
 if (root) root.TitanDashboard = dashboard;
})(typeof window === 'undefined' ? null : window, function () {
 const ids = Object.freeze(['tools','storage','resources','health','apps','shares','vms']);
 const saved = new Map();
 const choices = new Map();
 let current = null;
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
  return `<div class="resource-metrics"><div class="resource-metric"><div class="metric-label"><span><span class="metric-key cpu-key" aria-hidden="true"></span>CPU-Auslastung</span><strong>${values.cpu === null ? 'Messung läuft' : number(values.cpu)+' %'}</strong></div>${meter(values.cpu,'CPU-Auslastung')}<p class="metric-note">Lastdurchschnitt (1 Min.): ${load} · ${esc(status.cpus || '—')} logische CPUs</p></div><div class="resource-metric"><div class="metric-label"><span><span class="metric-key memory-key" aria-hidden="true"></span>RAM belegt · inklusive Cache</span><strong>${values.memory === null ? '—' : number(values.memory)+' %'}</strong></div>${meter(values.memory,'Arbeitsspeicher belegt','teal')}<p class="metric-note">${memory}</p><dl class="memory-breakdown"><div><dt>Bedarf (geschätzt)</dt><dd>${esc(bytes(status.memory_demand ?? (measured(status.memory_total)&&measured(status.memory_available)?status.memory_total-status.memory_available:null)))}</dd></div><div><dt>Verfügbar für Anwendungen</dt><dd>${esc(bytes(status.memory_available))}</dd></div><div><dt>Vollständig frei</dt><dd>${esc(bytes(status.memory_free))}</dd></div><div><dt>Dateicache / rückgewinnbarer Cache</dt><dd>${esc(bytes(status.memory_cached))}</dd></div><div><dt>Kernel-Puffer</dt><dd>${esc(bytes(status.memory_buffers))}</dd></div></dl></div>${metricChart(status.status_history,{demo:Boolean(format.demo)})}<div class="sensor-summary"><span class="sensor-label">CPU-Temperatur</span><strong class="${values.temperature === null?'muted':''}">${temperature}</strong></div>${sensors.length ? `<div class="sensor-readings" aria-label="Erkannte Temperatursensoren">${sensors.slice(0,6).map(sensor => `<span title="${esc(sensor.label)}">${esc(sensor.label)} <strong>${number(sensor.current)} °C</strong></span>`).join('')}${sensors.length>6?`<span>+ ${sensors.length-6} weitere Sensoren</span>`:''}</div>` : '<p class="metric-note">Der Host meldet keine Temperatursensoren.</p>'}<div class="resource-summary"><div><small>Laufzeit</small><strong>${uptime}</strong></div><div><small>Letzte Messung</small><strong data-metrics-updated>${measured(status.telemetry_sampled_at)?escape(time(status.telemetry_sampled_at)):'Noch keine'}</strong></div></div>${errors.length?`<details class="telemetry-details"><summary>Messhinweise (${errors.length})</summary>${errors.map(message=>`<p class="hint">${esc(message)}</p>`).join('')}</details>`:''}</div>`;
 }
 const normalize = order => [...new Set((Array.isArray(order) ? order : []).filter(id => ids.includes(id))), ...ids.filter(id => !(Array.isArray(order) ? order : []).includes(id))];
 function move(order, id, position) {
  const result = normalize(order), index = result.indexOf(id);
  if (index === -1) return result;
  result.splice(index, 1);
  result.splice(Math.max(0, Math.min(result.length, position)), 0, id);
  return result;
 }
 async function load(api, owner) {
  if (saved.has(owner)) return {order: saved.get(owner).slice(), available:true};
  try {
   const result = await api('/api/dashboard-layout');
   const order = normalize(result.order);
   saved.set(owner, order);
   choices.set(owner,{hidden:Array.isArray(result.hidden)?result.hidden:[],wide:Array.isArray(result.wide)?result.wide:["tools","resources"],sizes:result.sizes||{}});
   return {order:order.slice(), available:true};
  } catch (error) {
   // A layout failure must never prevent access to the NAS status and tools.
   return {order:ids.slice(), available:false};
  }
 }
 const readOrder = grid => [...grid.querySelectorAll('[data-dashboard-tile]')].map(tile => tile.dataset.dashboardTile);
 function applyOrder(grid, order) {
  const tiles = new Map([...grid.querySelectorAll('[data-dashboard-tile]')].map(tile => [tile.dataset.dashboardTile, tile]));
  normalize(order).forEach(id => { if (tiles.has(id)) grid.append(tiles.get(id)); });
 }
 function toolbar() {
  return '<div class="dashboard-toolbar" aria-label="Übersicht anpassen"><p id="dashboard-layout-hint" class="hint">Deine Übersicht · Kacheln nach deinen Wünschen anordnen.</p><div class="dashboard-layout-actions"><button type="button" class="button small" data-layout-edit>Übersicht anpassen <span aria-hidden="true">↕</span></button><button type="button" class="button small" data-layout-reset hidden>Standard</button><button type="button" class="button small" data-layout-cancel hidden>Abbrechen</button><button type="button" class="button small primary" data-layout-save hidden>Speichern</button></div><span class="sr-only" id="dashboard-layout-announcement" role="status" aria-live="polite" aria-atomic="true"></span></div>';
 }
 function controls(id, title) {
  return `<div class="tile-controls" hidden><button type="button" class="tile-handle" data-layout-handle="${id}" aria-label="${title}: ziehen oder mit Pfeiltasten verschieben" aria-describedby="dashboard-layout-hint" title="Ziehen · Pfeil hoch / runter"><span aria-hidden="true">⠿</span></button><button type="button" class="tile-step" data-layout-move="-1" aria-label="${title}: nach vorne verschieben" title="Nach vorne">↑</button><button type="button" class="tile-step" data-layout-move="1" aria-label="${title}: nach hinten verschieben" title="Nach hinten">↓</button><button type="button" class="tile-step" data-layout-width aria-label="${title}: Breite ändern">↔</button><button type="button" class="tile-step" data-layout-hide aria-label="${title}: entfernen">×</button><button type="button" class="tile-resize" data-layout-resize="${id}" aria-label="${title}: Größe durch Ziehen ändern" title="Größe ändern">◢</button></div>`;
 }
 function dispose() {
  if (current) current.destroy();
  current = null;
 }
 function clear() { dispose(); saved.clear(); choices.clear(); }
 function mount(main, {api, owner, toast, metricsFormat}) {
  dispose();
  const grid = main?.querySelector('#dashboard-grid');
  if (!grid) return;
  const edit = main.querySelector('[data-layout-edit]'), reset = main.querySelector('[data-layout-reset]');
  const cancel = main.querySelector('[data-layout-cancel]'), save = main.querySelector('[data-layout-save]');
  const hint = main.querySelector('#dashboard-layout-hint'), announcement = main.querySelector('#dashboard-layout-announcement');
  const doc = grid.ownerDocument;
  let options=JSON.parse(JSON.stringify(choices.get(owner)||{hidden:[],wide:["tools","resources"]})), originalOptions=JSON.parse(JSON.stringify(options));
  const picker=doc.createElement("details");picker.className="tile-picker";picker.hidden=true;main.querySelector(".dashboard-toolbar")?.after(picker);
  function applyChoices(){for(const tile of grid.querySelectorAll("[data-dashboard-tile]")){tile.hidden=options.hidden.includes(tile.dataset.dashboardTile);tile.classList.toggle("tile-wide",options.wide.includes(tile.dataset.dashboardTile));const size=options.sizes?.[tile.dataset.dashboardTile];tile.style.setProperty?.("--tile-columns",size?.columns||(options.wide.includes(tile.dataset.dashboardTile)?2:1));if(size?.height)tile.style.setProperty?.("--tile-height",size.height+"px");else tile.style.removeProperty?.("--tile-height");}picker.innerHTML='<summary>Kacheln hinzufügen oder ausblenden</summary><div class="tile-picker-options">'+[...grid.querySelectorAll("[data-dashboard-tile]")].map(tile=>`<label><input type="checkbox" data-layout-choice="${tile.dataset.dashboardTile}" ${tile.hidden?"":"checked"}>${escape(tile.querySelector("h2")?.textContent||tile.dataset.dashboardTile)}</label>`).join("")+"</div>";}
  for(const tile of grid.querySelectorAll("[data-dashboard-tile]")){const grip=tile.querySelector("[data-layout-resize]");if(grip){tile.append(grip);grip.hidden=true;}}
  applyChoices();
  let original = readOrder(grid), editing = false, busy = false, drag = null, metricsBusy = false;
  const liveResources = main.querySelector('[data-live-resources]');
  async function refreshMetrics() {
   if (!liveResources || editing || metricsBusy || doc.hidden || liveResources.contains?.(doc.activeElement) || current?.grid !== grid) return;
   metricsBusy = true;
   try {
    const status = await api('/api/status');
    if (current?.grid !== grid || editing) return;
    const expanded = Boolean(liveResources.querySelector('.telemetry-details')?.open);
    liveResources.innerHTML = resourceMetrics(status,metricsFormat);
    const details = liveResources.querySelector('.telemetry-details');
    if (details) details.open = expanded;
    liveResources.querySelectorAll('[data-percent]').forEach(item => { item.querySelector('span').style.width = `${item.dataset.percent}%`; });
   } catch (error) {
    if (current?.grid !== grid) return;
    const updated = liveResources.querySelector('[data-metrics-updated]');
    if (updated) updated.textContent = 'Verbindung unterbrochen';
   } finally { metricsBusy = false; }
  }
  let sortable=null,resize=null;
  const Sortable=doc.defaultView?.Sortable;
  if(Sortable)sortable=new Sortable(grid,{draggable:'[data-dashboard-tile]:not([hidden])',handle:'[data-layout-handle]',disabled:true,animation:doc.defaultView?.matchMedia?.("(prefers-reduced-motion: reduce)").matches?0:220,easing:'cubic-bezier(.2,.8,.2,1)',forceFallback:true,fallbackOnBody:true,fallbackTolerance:5,ghostClass:'layout-placeholder',fallbackClass:'layout-floating',scroll:true,scrollSensitivity:70,scrollSpeed:12,onStart(){grid.classList.add('layout-dragging');},onEnd(){grid.classList.remove('layout-dragging');updateButtons();announce('Kachel verschoben. Zum Übernehmen speichern.');}});
  const metricsTimer = liveResources && doc.defaultView?.setInterval ? doc.defaultView.setInterval(refreshMetrics,10000) : null;
  function visibility() { if (!doc.hidden) void refreshMetrics(); }
  if (liveResources) doc.addEventListener('visibilitychange',visibility);
  const announce = text => { announcement.textContent = text; };
  const title = tile => tile.querySelector('h2')?.textContent || tile.dataset.dashboardTile;
  function state(value) {
   editing = value;sortable?.option('disabled',!value);
   grid.classList.toggle('layout-editing', editing);
   picker.hidden=!editing;
   edit.hidden = editing;
   for (const item of [reset, cancel, save]) item.hidden = !editing;
   grid.querySelectorAll('.tile-controls').forEach(item => item.hidden = !editing);grid.querySelectorAll('[data-layout-resize]').forEach(item=>item.hidden=!editing);
   hint.textContent = editing ? 'Am Griff ziehen, unten rechts die Größe ändern. Am Handy bleiben Kacheln einspaltig. Danach speichern.' : 'Deine Übersicht · Kacheln nach deinen Wünschen anordnen.';
  }
  function updateButtons() {
   const tiles = [...grid.querySelectorAll('[data-dashboard-tile]')];
   tiles.forEach((tile, index) => {
    tile.querySelector('[data-layout-move="-1"]').disabled = busy || index === 0;
    tile.querySelector('[data-layout-move="1"]').disabled = busy || index === tiles.length - 1;
    tile.querySelector('[data-layout-handle]').disabled = busy;
   });
  }
  function reorder(tile, position, focus = false) {
   const order = move(readOrder(grid), tile.dataset.dashboardTile, position);
   applyOrder(grid, order);
   updateButtons();
   announce(`${title(tile)}: Position ${order.indexOf(tile.dataset.dashboardTile) + 1} von ${order.length}.`);
   if (focus) tile.querySelector('[data-layout-handle]').focus({preventScroll:true});
  }
  function finishDrag(restore = false) {
   if (!drag) return;
   const item = drag;
   drag = null;
   item.ghost?.remove();
   item.tile.classList.remove('tile-dragging');
   grid.classList.remove('layout-dragging');
   if (restore) applyOrder(grid, item.before);
   try { item.handle.releasePointerCapture(item.pointerId); } catch (_) { /* May already be released. */ }
   updateButtons();
   item.handle.focus({preventScroll:true});
  }
  function onClick(event) {
   if (busy) return;
   if (event.target.closest('[data-layout-edit]')) {
    original = readOrder(grid); originalOptions=JSON.parse(JSON.stringify(options)); state(true); updateButtons();
    grid.querySelector('[data-layout-handle]')?.focus({preventScroll:true});
   } else if (event.target.closest('[data-layout-reset]')) {
    finishDrag(); options={hidden:[],wide:["tools","resources"],sizes:{}};applyChoices();applyOrder(grid, ids); updateButtons(); announce('Standardreihenfolge. Zum Übernehmen speichern.');
   } else if (event.target.closest('[data-layout-cancel]')) {
    finishDrag();options=JSON.parse(JSON.stringify(originalOptions));applyChoices(); applyOrder(grid, original); state(false); announce('Änderungen verworfen.'); edit.focus({preventScroll:true});
   } else if (event.target.closest('[data-layout-save]')) {
    finishDrag(); void persist();
   } else if(editing && event.target.closest("[data-layout-hide],[data-layout-width]")){
    const control=event.target.closest("[data-layout-hide],[data-layout-width]"),id=control.closest("[data-dashboard-tile]").dataset.dashboardTile;const key=control.hasAttribute("data-layout-hide")?"hidden":"wide";if(key==="wide"&&options.sizes)delete options.sizes[id];options[key]=options[key].includes(id)?options[key].filter(value=>value!==id):[...options[key],id];applyChoices();
   } else {
    const control = event.target.closest('[data-layout-move]');
    if (!editing || !control || control.disabled || !grid.contains(control)) return;
    const tile = control.closest('[data-dashboard-tile]');
    reorder(tile, readOrder(grid).indexOf(tile.dataset.dashboardTile) + Number(control.dataset.layoutMove), true);
   }
  }
  async function persist() {
   busy = true;
   save.textContent = 'Wird gespeichert …';
   for (const item of [save, cancel, reset]) item.disabled = true;
   updateButtons();
   const order = readOrder(grid);
   try {
    const result = await api('/api/dashboard-layout', {order,...options});
    saved.set(owner, normalize(result.order || order));
    if (current?.grid !== grid) return;
    choices.set(owner,JSON.parse(JSON.stringify(options)));original = order.slice(); state(false); main.querySelector('.layout-load-hint')?.remove(); announce('Deine Übersicht wurde gespeichert.');
    toast('Deine Übersicht wurde gespeichert.'); edit.focus({preventScroll:true});
   } catch (error) {
    if (current?.grid !== grid) return;
    announce('Speichern fehlgeschlagen. Deine Anordnung bleibt zur erneuten Speicherung erhalten.');
    toast(error.message || 'Die Anordnung konnte nicht gespeichert werden.', true);
   } finally {
    busy = false;
    save.textContent = 'Speichern';
    for (const item of [save, cancel, reset]) item.disabled = false;
    updateButtons();
   }
  }
  function onChoice(event){const choice=event.target.closest("[data-layout-choice]");if(!editing||busy||!choice)return;options.hidden=options.hidden.filter(id=>id!==choice.dataset.layoutChoice);if(!choice.checked)options.hidden.push(choice.dataset.layoutChoice);applyChoices();}
  main.addEventListener("change",onChoice);
  function onKey(event) {
   if (!editing || busy) return;
   if (event.key === 'Escape' && drag) { event.preventDefault(); finishDrag(true); announce('Verschieben abgebrochen.'); return; }
   const handle = event.target.closest('[data-layout-handle]');
   if (!handle || !grid.contains(handle)) return;
   const tile = handle.closest('[data-dashboard-tile]'), order = readOrder(grid);
   const positions = {ArrowUp:order.indexOf(tile.dataset.dashboardTile)-1, ArrowLeft:order.indexOf(tile.dataset.dashboardTile)-1, ArrowDown:order.indexOf(tile.dataset.dashboardTile)+1, ArrowRight:order.indexOf(tile.dataset.dashboardTile)+1, Home:0, End:order.length-1};
   if (!(event.key in positions)) return;
   event.preventDefault(); reorder(tile, positions[event.key], true);
  }
  function onPointerDown(event) {
   const grip=event.target.closest('[data-layout-resize]');
   if(editing&&!busy&&grip&&event.button===0){event.preventDefault();const tile=grip.closest('[data-dashboard-tile]');resize={tile,grip,id:event.pointerId,x:event.clientX,y:event.clientY,height:tile.getBoundingClientRect().height,width:tile.getBoundingClientRect().width,prior:JSON.parse(JSON.stringify(options.sizes||{}))};grip.setPointerCapture?.(event.pointerId);return;}
   if(sortable)return;
   const handle = event.target.closest('[data-layout-handle]');
   if (!editing || busy || !handle || !grid.contains(handle) || event.button !== 0 || event.isPrimary === false) return;
   event.preventDefault();
   const tile = handle.closest('[data-dashboard-tile]');
   drag = {handle, tile, pointerId:event.pointerId, startX:event.clientX, startY:event.clientY, before:readOrder(grid), ghost:null};
   try { handle.setPointerCapture(event.pointerId); } catch (_) { /* Document listeners also cover pointer movement. */ }
  }
  function onPointerMove(event) {
   if(resize&&event.pointerId===resize.id){event.preventDefault();const columns=Number(doc.defaultView?.getComputedStyle(grid).getPropertyValue('--dashboard-columns'))||1,unit=(grid.getBoundingClientRect().width+16)/columns;const width=Math.max(1,Math.min(columns,Math.round((resize.width+event.clientX-resize.x+16)/unit)));options.sizes||={};options.sizes[resize.tile.dataset.dashboardTile]={columns:width,height:Math.max(180,Math.min(1600,Math.round(resize.height+event.clientY-resize.y)))};applyChoices();return;}
   if (!drag || event.pointerId !== drag.pointerId) return;
   if (!drag.ghost && Math.hypot(event.clientX-drag.startX, event.clientY-drag.startY) < 8) return;
   event.preventDefault();
   if (!drag.ghost) {
    drag.ghost = doc.createElement('div');
    drag.ghost.className = 'tile-drag-ghost'; drag.ghost.textContent = title(drag.tile); drag.ghost.setAttribute('aria-hidden', 'true');
    doc.body.append(drag.ghost); drag.tile.classList.add('tile-dragging'); grid.classList.add('layout-dragging');
   }
   drag.ghost.style.left = `${event.clientX + 14}px`; drag.ghost.style.top = `${event.clientY + 14}px`;
   const target = doc.elementFromPoint(event.clientX, event.clientY)?.closest('[data-dashboard-tile]');
   if (target && target !== drag.tile && grid.contains(target)) {
    const rect = target.getBoundingClientRect(), order = readOrder(grid);
    const from = order.indexOf(drag.tile.dataset.dashboardTile), to = order.indexOf(target.dataset.dashboardTile);
    const after = event.clientY > rect.top + rect.height / 2;
    reorder(drag.tile, to + (after ? 1 : 0) - (from < to ? 1 : 0));
   }
   // Dragging a handle on a small screen can reach cards outside the viewport.
   const view = doc.defaultView;
   if (view && event.clientY < 72) view.scrollBy(0, -12);
   else if (view && event.clientY > view.innerHeight - 72) view.scrollBy(0, 12);
  }
  function onPointerEnd(event) { if(resize&&event.pointerId===resize.id){if(event.type==='pointercancel')options.sizes=resize.prior;resize.grip.releasePointerCapture?.(event.pointerId);resize=null;applyChoices();announce('Kachelgröße geändert. Zum Übernehmen speichern.');} if (drag && event.pointerId === drag.pointerId) finishDrag(event.type === 'pointercancel'); }
  main.addEventListener('click', onClick);
  main.addEventListener('keydown', onKey);
  grid.addEventListener('pointerdown', onPointerDown);
  doc.addEventListener('pointermove', onPointerMove, {passive:false});
  doc.addEventListener('pointerup', onPointerEnd);
  doc.addEventListener('pointercancel', onPointerEnd);
  current = {grid, editing:() => editing, destroy() {
   sortable?.destroy();resize=null;picker.remove?.();
   if (metricsTimer !== null) doc.defaultView.clearInterval(metricsTimer);
   if (liveResources) doc.removeEventListener('visibilitychange',visibility);
   finishDrag(); main.removeEventListener('click', onClick);main.removeEventListener("change",onChoice); main.removeEventListener('keydown', onKey);
   grid.removeEventListener('pointerdown', onPointerDown); doc.removeEventListener('pointermove', onPointerMove);
   doc.removeEventListener('pointerup', onPointerEnd); doc.removeEventListener('pointercancel', onPointerEnd);
  }};
 }
 return {ids, normalize, move, load, applyOrder, toolbar, controls, mount, dispose, clear, metricValues, historySamples, metricChart, resourceMetrics, editing:() => Boolean(current?.editing())};
});
