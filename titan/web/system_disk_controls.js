'use strict';
(function (factory) {
 const ui = factory();
 if (typeof module === 'object' && module.exports) module.exports = ui;
 else window.TitanSystemDisk = ui;
})(() => {
 const instances = new Map();
 const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const size = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
 function bytes(value) {
  value = size(value);
  if (value === null) return '—';
  if (!value) return '0 B';
  const units = ['B','KB','MB','GB','TB','PB'], index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return (value / 1024 ** index).toLocaleString('de-DE', {maximumFractionDigits:index > 2 ? 2 : 0}) + ' ' + units[index];
 }
 function canGrow(data) {
  return data?.supported === true && data?.available === true &&
   typeof data.revision === 'string' && /^[a-f0-9]{64}$/.test(data.revision) && size(data.growable_bytes) > 0;
 }
 function statistics(data) {
  return `<div class="stat-row system-disk-stats"><div class="stat-card"><small>Gesamte Systemplatte</small><strong>${bytes(data.disk_size)}</strong></div><div class="stat-card"><small>Systempartition</small><strong>${bytes(data.partition_size)}</strong></div><div class="stat-card"><small>Dateisystem</small><strong>${bytes(data.filesystem_size)}</strong></div><div class="stat-card"><small>Für Dateien verfügbar</small><strong>${bytes(data.filesystem_available)}</strong></div></div>`;
 }
 function details(data) {
  return `<div class="app-details system-disk-details"><div><small>Systemplatte</small><p>${esc(data.disk || 'Nicht erkannt')}</p></div><div><small>Systempartition</small><p>${esc(data.partition || 'Nicht erkannt')}</p></div><div><small>Dateisystem / Datenbereich</small><p>${esc((data.filesystem || 'Unbekannt').toUpperCase())} · ${esc(data.mountpoint || 'Nicht erkannt')}</p></div><div><small>Belegt</small><p>${bytes(data.filesystem_used)}</p></div></div>`;
 }
 function panel(data = {}, error = '', options = {}) {
  data = data && typeof data === 'object' ? data : {};
  const enabled = options.admin !== false && canGrow(data), total = size(data.filesystem_size), used = size(data.filesystem_used);
  return `<section class="panel system-disk-panel" data-system-disk-panel><div class="panel-heading"><h2>Systemplatte</h2><span class="pill ${enabled ? 'purple' : 'gray'}">${error ? 'Status nicht verfügbar' : enabled ? 'Erweiterung verfügbar' : data.supported ? 'Systemkapazität' : 'Status prüfen'}</span></div><p class="hint">Hier liegen Titan, deine Apps, virtuellen Festplatten und Dateien ohne eigenes Datenvolume.</p>${error ? `<div class="notice warning">${esc(error)}</div>` : `<div class="stat-row"><div class="stat-card"><small>Gesamter Datenbereich</small><strong>${bytes(data.filesystem_size)}</strong></div><div class="stat-card"><small>Belegt</small><strong>${bytes(data.filesystem_used)}</strong></div><div class="stat-card"><small>Verfügbar</small><strong>${bytes(data.filesystem_available)}</strong></div></div><details><summary>Laufwerk und Partitionen</summary>${statistics(data)}${details(data)}</details>`}${!error && total > 0 && used !== null ? `<meter class="system-disk-meter" min="0" max="${total}" value="${Math.min(total, used)}" aria-label="Belegter Platz im Systemdateisystem">${bytes(used)} von ${bytes(total)} belegt</meter>` : ''}${!error ? `<div class="notice ${enabled ? '' : 'warning'}"><strong>${size(data.growable_bytes) > 0 ? 'Zusätzlich nutzbare Kapazität: ' + bytes(data.growable_bytes) : data.supported ? 'Aktuell keine Erweiterung verfügbar.' : 'Systemlayout konnte nicht sicher für eine Erweiterung geprüft werden.'}</strong>${data.reason ? `<p>${esc(data.reason)}</p>` : ''}${enabled ? `<p>Freier Platz hinter der Systempartition: ${bytes(data.partition_growable_bytes)}. Innerhalb der Partition für das Dateisystem zusätzlich nutzbar: ${bytes(data.filesystem_growable_bytes)}.</p>` : ''}</div>` : ''}<div class="form-actions wrap"><button type="button" class="button primary" data-system-disk-open ${enabled && !error ? '' : 'disabled'}>Kapazität erweitern</button><button type="button" class="button small" data-system-disk-refresh>Status aktualisieren</button><button type="button" class="text-link" data-action="jobs">Aktivität öffnen →</button></div><p class="hint" data-system-disk-status role="status" aria-live="polite">${options.admin === false ? 'Eine Erweiterung kann ein Administrator starten.' : 'Nach einer Vergrößerung in Proxmox oder im Hypervisor den Status aktualisieren.'}</p><details><summary>Warum unterscheiden sich die Größen?</summary><p class="hint">Die gesamte Platte enthält auch Bootpartitionen und noch nicht zugeteilten Platz. Titan erweitert die vorhandene Systempartition und ihr XFS-Dateisystem. Mehrere System-Mountpunkte können denselben Speicherbereich zeigen und werden nicht als zusätzliche Kapazität gezählt.</p></details></section>`;
 }
 function confirmation(data) {
  return `<p class="subtitle">Die vorhandene Systempartition und ihr XFS-Dateisystem werden auf die jetzt geprüfte Kapazität erweitert. Vorhandene Daten bleiben erhalten.</p>${statistics(data)}${details(data)}<div class="notice"><strong>Erweiterung um bis zu ${bytes(data.growable_bytes)}</strong><p>Systemplatte ${esc(data.disk)} · Partition ${esc(data.partition)}. Titan prüft diesen Stand unmittelbar vor der Ausführung erneut.</p></div><form data-system-disk-form><p>Möchtest du die angezeigte Systemkapazität erweitern?</p><input type="hidden" value="ERWEITERN" data-system-disk-confirmation><p class="hint" data-system-disk-dialog-status role="status" aria-live="polite"></p><div class="form-actions wrap"><button type="button" class="button" data-action="close">Nein</button><button type="submit" class="button primary">Ja</button><a class="text-link" href="#jobs" data-action="close">Auftrag ansehen →</a></div></form>`;
 }
 function disposeWithin(root) {
  for (const state of instances.values()) if (state.dialogRoot && (root === state.dialogRoot || root?.contains?.(state.dialogRoot))) state.closeDialog();
 }
 function dispose() {
  for (const state of [...instances.values()]) state.destroy();
 }
 function mount(root, ctx) {
  instances.get(root)?.destroy();
  if (!root?.querySelector?.('[data-system-disk-panel]')) return null;
  let alive = true, busy = false, refreshing = false, queuedJob = null, current = null, dialogGeneration = 0, dialogCleanup = null;
  const state = {dialogRoot:null};
  const query = selector => root.querySelector(selector);
  const dialogRoot = () => typeof ctx.dialogRoot === 'function' ? ctx.dialogRoot() : ctx.dialogRoot || (typeof document === 'object' ? document.querySelector('#dialog-body') : null);
  const mainStatus = message => {const node = query('[data-system-disk-status]'); if (alive && node) node.textContent = message;};
  function controls() {const open = query('[data-system-disk-open]'); if (open && (current !== null || busy || queuedJob || ctx.admin === false)) open.disabled = Boolean(busy || queuedJob || ctx.admin === false || !canGrow(current));}
  function closeDialog() {
   dialogGeneration++; dialogCleanup?.(); dialogCleanup = null; state.dialogRoot = null;
  }
  function replace(data, error = '') {
   if (!alive) return;
   current = error ? {} : data;
   const node = query('[data-system-disk-panel]');
   if (!node) return;
   const active = typeof document === 'object' ? document.activeElement : null;
   const focus = node.contains?.(active) && (active?.hasAttribute?.('data-system-disk-refresh') ? '[data-system-disk-refresh]' : active?.hasAttribute?.('data-system-disk-open') ? '[data-system-disk-open]' : null);
   node.outerHTML = panel(data, error, {admin:ctx.admin !== false}); controls();
   if (focus) {const next = query(focus); if (next && !next.disabled) next.focus?.({preventScroll:true});}
  }
  async function readJobs(timeout = 30000) {
   let timer;
   try {
    // A hanging read must not bypass the bounded polling deadline. The job
    // itself keeps running on the NAS; this only limits waiting in the UI.
    return await Promise.race([ctx.api('/api/jobs'), new Promise((resolve, reject) => {
     timer = setTimeout(() => reject(new Error('Der Auftragsstatus antwortet nicht. Prüfe die Erweiterung unter Aktivität.')), timeout);
    })]);
   } finally {clearTimeout(timer);}
  }
  async function refresh() {
   if (!alive || refreshing) return;
   refreshing = true; mainStatus('Systemkapazität wird geprüft …');
   try {
    if (queuedJob) {
     const jobs = await readJobs();
     if (!alive) return;
     if (!Array.isArray(jobs)) throw new Error('Ungültiger Auftragsstatus.');
     const job = jobs.find(item => item.id === queuedJob);
     if (job && ['completed','failed'].includes(job.status)) queuedJob = null;
    }
    const data = await ctx.api('/api/system-disk'); if (!alive) return;
    replace(data); if (queuedJob) mainStatus('Die Erweiterung läuft noch. Den Fortschritt findest du unter Aktivität.');
   } catch (error) {if (alive) mainStatus('Status konnte nicht aktualisiert werden: ' + error.message);}
   finally {refreshing = false;}
  }
  async function waitJob(identifier, generation, status) {
   const deadline = Date.now() + 120000;
   for (let attempts = 0; attempts < 81; attempts++) {
    if (!alive || generation !== dialogGeneration) return null;
    if (Date.now() >= deadline) throw new Error('Die Erweiterung läuft noch. Prüfe den Auftrag; starte sie nicht erneut.');
    const jobs = await readJobs(Math.min(30000, deadline - Date.now()));
    if (!alive || generation !== dialogGeneration) return null;
    if (!Array.isArray(jobs)) throw new Error('Ungültiger Auftragsstatus. Prüfe die Erweiterung unter Aktivität.');
    const job = jobs.find(item => item.id === identifier);
    if (job?.status === 'failed') {queuedJob = null; throw new Error(job.result?.error || 'Die Erweiterung ist fehlgeschlagen.');}
    if (job?.status === 'completed') {queuedJob = null; return job.result || {};}
    status.textContent = job?.status === 'running' ? 'Systemkapazität wird erweitert …' : 'Erweiterung wartet auf Ausführung …';
    if (Date.now() >= deadline || attempts === 80) throw new Error('Die Erweiterung läuft noch. Prüfe den Auftrag; starte sie nicht erneut.');
    await new Promise(resolve => setTimeout(resolve, 1500));
   }
  }
  async function open() {
   if (!alive || busy || queuedJob) return;
   if (ctx.admin === false) {ctx.toast?.('Eine Erweiterung kann ein Administrator starten.', true); return;}
   busy = true; controls(); mainStatus('Aktuelle Systemkapazität wird geprüft …');
   try {
    const data = await ctx.api('/api/system-disk'); if (!alive) return;
    replace(data);
    if (!canGrow(data)) {mainStatus(data.reason || 'Aktuell keine sichere Erweiterung verfügbar.'); return;}
    closeDialog();
    // Revision is captured from this fresh response, never read from the DOM.
    const expected = data.revision, generation = dialogGeneration;
    ctx.dialog('Systemkapazität erweitern', confirmation(data));
    const scope = dialogRoot(), form = scope?.querySelector('[data-system-disk-form]');
    if (!form) throw new Error('Der Bestätigungsdialog konnte nicht geöffnet werden.');
    state.dialogRoot = scope;
    const input = form.querySelector('[data-system-disk-confirmation]'), status = form.querySelector('[data-system-disk-dialog-status]'), submit = form.querySelector('button[type="submit"]');
    let attempted = false, submitting = false;
    const onSubmit = async event => {
     event.preventDefault();
     if (!alive || generation !== dialogGeneration || submitting || attempted) return;
     if (input.value !== 'ERWEITERN') {status.textContent = 'Bitte ERWEITERN exakt eingeben.'; input.focus?.(); return;}
     submitting = true; attempted = true; busy = true; submit.disabled = true; input.disabled = true; controls(); status.textContent = 'Erweiterung wird beauftragt …';
     try {
      const result = await ctx.api('/api/actions', {operation:'system_disk_grow', arguments:{expected_revision:expected, confirmation:'ERWEITERN'}});
      if (!result || !['string','number'].includes(typeof result.job) || String(result.job).length > 128) throw new Error('Die Auftragskennung fehlt. Prüfe die Aktivität, bevor du erneut startest.');
      queuedJob = result.job;
      if (!alive || generation !== dialogGeneration) return;
      const completed = await waitJob(result.job, generation, status);
      if (!alive || generation !== dialogGeneration || completed === null) return;
      status.textContent = completed.message || (completed.changed === false ? 'Die Systemkapazität ist bereits vollständig nutzbar.' : 'Die Systemkapazität wurde erweitert.');
      ctx.toast?.(status.textContent); await refresh();
     } catch (error) {
      if (alive && generation === dialogGeneration) {status.textContent = error.message + (queuedJob ? '' : ' Schließe den Dialog und prüfe den aktuellen Status vor einem weiteren Versuch.'); ctx.toast?.(error.message, true); if (queuedJob) mainStatus('Die Erweiterung ist beauftragt. Prüfe den Auftrag, bevor du erneut startest.'); else await refresh();}
     } finally {submitting = false; busy = false; if (alive) controls();}
    };
    form.addEventListener('submit', onSubmit);
    dialogCleanup = () => form.removeEventListener('submit', onSubmit);
    input.focus?.();
   } catch (error) {if (alive) {mainStatus(error.message); ctx.toast?.(error.message, true);}}
   finally {busy = false; if (alive) controls();}
  }
  const onClick = event => {
   const refreshButton = event.target.closest?.('[data-system-disk-refresh]'), openButton = event.target.closest?.('[data-system-disk-open]');
   if (refreshButton && !refreshButton.disabled) {event.preventDefault(); refresh();}
   else if (openButton && !openButton.disabled) {event.preventDefault(); open();}
  };
  root.addEventListener('click', onClick);
  Object.assign(state, {open,refresh,closeDialog,destroy() {alive = false; closeDialog(); root.removeEventListener('click', onClick); instances.delete(root);}});
  instances.set(root, state);
  return state;
 }
 return {panel,mount,dispose,disposeWithin,bytes,canGrow};
});
