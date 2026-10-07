'use strict';
// Page selection is short lived; submitted transfers retain their original paths.
(function (root, factory) {
 const files = factory();
 if (typeof module === 'object' && module.exports) module.exports = files;
 if (root) root.TitanFiles = files;
})(typeof window === 'undefined' ? null : window, function () {
 const limit = 200;
 let current = null;
 let clipboard=null,clipboardOwner=null;
 const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
 const eligible = entry => Boolean(entry && typeof entry.name === 'string' && entry.name && !entry.name.includes('/') && !entry.name.includes('\0') && !['.','..'].includes(entry.name) && !entry.symlink && entry.readable !== false);
 function normalizeFolder(value) {
  const path = String(value ?? '');
  if (path.startsWith('/') || path.includes('\0') || path.split('/').includes('..')) throw new Error('Der Zielordner muss relativ zur Zielfreigabe sein und darf kein .. enthalten.');
  const normalized = path.split('/').filter(part => part && part !== '.').join('/');
  if (normalized.length > 4096) throw new Error('Der Zielordner ist zu lang.');
  return normalized;
 }
 function destinationPath(folder, name) {
  if (!eligible({name})) throw new Error('Ungültiger Dateiname.');
  const path = [normalizeFolder(folder), name].filter(Boolean).join('/');
  if (path.length > 4096) throw new Error('Der Zielpfad ist zu lang.');
  return path;
 }
 function keyBlocked(target, doc) {
  if (doc?.querySelector('dialog[open]') || doc?.querySelector('[role="dialog"][aria-modal="true"]')) return true;
  for (let node = target; node; node = node.parentElement) {
   if (['INPUT','TEXTAREA','SELECT'].includes(String(node.tagName || '').toUpperCase()) || node.isContentEditable) return true;
   const editable = node.getAttribute?.('contenteditable');
   if (editable !== null && editable !== undefined && editable !== 'false') return true;
  }
  return false;
 }
 // Recursive search can show both a selected folder and its descendants. The
 // folder already carries those descendants; processing them twice can turn a
 // successful move into partial errors. Validate flat destination names before
 // the first operation rather than discovering a duplicate after a copy.
 function batchEntries(action, entries) {
  const unique = [], seen = new Set();
  for (const entry of entries.slice(0, limit)) {
   const path = normalizeFolder(entry.path);
   if (!path || !eligible(entry) || path.split('/').at(-1) !== entry.name) throw new Error('Die Dateiauswahl ist ungültig. Bitte erneut auswählen.');
   if (seen.has(path)) continue;
   seen.add(path); unique.push({...entry, path});
  }
  const directories = unique.filter(entry => entry.directory).map(entry => entry.path + '/');
  const selected = unique.filter(entry => !directories.some(parent => entry.path.startsWith(parent)));
  if (['copy','move'].includes(action)) {
   const names = new Set();
   for (const entry of selected) {
    if (names.has(entry.name)) throw new Error(`Mehrere ausgewählte Einträge heißen „${entry.name}“. Wähle sie einzeln aus oder verwende verschiedene Zielordner.`);
    names.add(entry.name);
   }
  }
  return selected;
 }
 // The worker rejects existing destinations. Never retry a failure with overwrite.
 async function serialBatch(api, snapshot, progress = () => {}, stopped = () => false) {
  const results = batchEntries(snapshot.action, snapshot.entries).map(entry => ({...entry, status:'pending', error:''}));
  for (let index = 0; index < results.length; index++) {
   const item = results[index];
   if (stopped()) { item.status = 'skipped'; continue; }
   item.status = 'running'; progress(results, index);
   try {
    const body = {share:snapshot.share, path:item.path, action:snapshot.action};
    if (!['trash','delete'].includes(snapshot.action)) {
     body.destination_share = snapshot.destinationShare;
     body.destination = destinationPath(snapshot.destinationFolder, item.name);
    }
    if(snapshot.action==='delete')body.confirmation_path=snapshot.share==='@system'?'/'+item.path:snapshot.share+'/'+item.path;
    await api('/api/files', body);
    item.status = 'completed';
   } catch (error) {
    item.status = 'failed'; item.error = error?.message || 'Anfrage fehlgeschlagen.';
   }
   progress(results, index);
  }
  progress(results, results.length);
  return results;
 }
 function dispose() {
  current?.destroy();
  current = null;
 }
 function mount(main, ctx) {
  dispose();
  if (!main || !ctx) return;
  const doc = main.ownerDocument;
  const esc = ctx.esc || escape;
  const notice = (message, error = false) => ctx.toast?.(message, error);
  if(clipboardOwner!==ctx.owner){clipboard=null;clipboardOwner=ctx.owner;}
  const origin = {share:String(ctx.share || ''), path:String(ctx.path || '')};
  const targets = (Array.isArray(ctx.targets) ? ctx.targets : []).map(item => ({name:String(item.name), label:String(item.label || item.name)}));
  const entries = (Array.isArray(ctx.entries) ? ctx.entries : []).map(entry => ({...entry}));
  const boxes = [...main.querySelectorAll('[data-file-select]')];
  const allowed = new Map();
  const selected = new Set();
  let mounted = true, busy = false, operation = null;
  const controller = new AbortController();
  const removers = [];
  function listen(node, type, listener, options = {}) {
   if (!node) return;
   node.addEventListener(type, listener, {...options, signal:controller.signal});
   removers.push(() => node.removeEventListener(type, listener, options));
  }
  for (const box of boxes) {
   box.checked = false;
   const index = Number(box.value);
   const entry = entries[index];
   if (!box.disabled && !box.hidden && !box.closest('[hidden]') && Number.isInteger(index) && index >= 0 && eligible(entry) && allowed.size < limit && !allowed.has(index)) allowed.set(index, {box, entry});
   else box.disabled = true;
  }
  const selectedEntries = () => [...allowed].filter(([index]) => selected.has(index)).map(([index, {entry}]) => ({...entry, index, path:entry.path||[origin.path, entry.name].filter(Boolean).join('/')}));
  function update() {
   if (!mounted) return;
   for(const index of [...selected])if(allowed.get(index)?.box.closest?.("[hidden]"))selected.delete(index);
   for(const button of main.querySelectorAll("[data-file-clipboard]"))button.disabled=button.dataset.fileClipboard==="paste"?!clipboard||!ctx.writable:!selected.size;
   const count = selected.size;
   const mutable = count > 0 && ctx.writable && selectedEntries().every(entry => entry.mutable === true);
   for (const node of main.querySelectorAll('[data-file-selection-count]')) node.textContent = `${count} ausgewählt`;
   for (const node of main.querySelectorAll('[data-file-selection-bar]')) node.hidden = count === 0;
   for (const [index, {box}] of allowed) { box.checked = selected.has(index); box.disabled = busy; }
   for (const box of main.querySelectorAll('[data-file-select-all]')) {
    box.checked = allowed.size > 0 && count === allowed.size;
    box.indeterminate = count > 0 && count < allowed.size;
    box.disabled = busy || allowed.size === 0;
   }
   const single = count === 1 ? selectedEntries()[0] : null;
   for (const button of main.querySelectorAll('[data-file-single]')) {
    const action = button.dataset.fileSingle;
    const editable = single && ctx.writable && !single.directory && single.readable !== false && single.editable !== false && single.mutable === true && Number(single.size || 0) <= 1048576;
    button.disabled = busy || !single || (action === 'file-rename' && !mutable) || (action === 'file-edit' && !editable);
   }
   for (const button of main.querySelectorAll('[data-file-batch]')) {
    const action = button.dataset.fileBatch;
    button.disabled = busy || !count || (action === 'copy' && !targets.length) || (action === 'move' && (!mutable || !targets.length)) || (action === 'trash' && (!mutable || origin.share === '@system')) || (action === 'delete' && (!mutable || !ctx.admin));
   }
  }
  function change(event) {
   if (!mounted || busy) return;
   const box = event.target.closest?.('[data-file-select]');
   if (box && main.contains(box)) {
    const index = Number(box.value);
    if (allowed.get(index)?.box === box) box.checked ? selected.add(index) : selected.delete(index);
    else box.checked = false;
    update();
   } else if (event.target.closest?.('[data-file-select-all]') && main.contains(event.target)) {
    selected.clear();
    if (event.target.checked) for (const index of allowed.keys()) selected.add(index);
    update();
   }
  }
  function clear() { selected.clear(); update(); }
  function click(event) {
   // Clicking a checkbox label must not also open its file row.
   const checkbox = event.target.closest?.('[data-file-select]') || event.target.closest?.('[data-file-select-all]');
   const label = event.target.closest?.('label');
   if (checkbox || label?.querySelector('[data-file-select]') || label?.querySelector('[data-file-select-all]')) { event.stopPropagation?.(); return; }
   const singleButton=event.target.closest?.('[data-file-single]');
   if(singleButton&&!singleButton.disabled){const items=selectedEntries();if(items.length===1&&!busy){event.preventDefault();event.stopPropagation?.();invoke(singleButton.dataset.fileSingle==='file-preview'&&items[0].directory?'folder-open':singleButton.dataset.fileSingle,items[0]);}return;}
   const clipButton=event.target.closest?.("[data-file-clipboard]");if(clipButton&&!clipButton.disabled){event.preventDefault();event.stopPropagation?.();clip(clipButton.dataset.fileClipboard);return;}
   const button = event.target.closest?.('[data-file-batch]');
   if (!button || !main.contains(button) || button.disabled || busy || !mounted) return;
   event.preventDefault(); event.stopPropagation?.();
   if (button.dataset.fileBatch === 'clear') clear();
   else openBatch(button.dataset.fileBatch);
  }
  function clip(command){if(command==="paste"){if(clipboard&&ctx.writable)openBatch(clipboard.action,clipboard);return;}const items=selectedEntries();if(!items.length)return;if(command==="cut"&&(!ctx.writable||items.some(item=>item.mutable!==true))){notice("Auswahl ist schreibgeschützt.",true);return;}clipboard={...origin,action:command==="cut"?"move":"copy",entries:items};notice(items.length+(command==="cut"?" Einträge ausgeschnitten.":" Einträge kopiert."));update();}
  function invoke(name, entry) {
   try {
    Promise.resolve(ctx.actions?.[name]?.({dataset:{path:entry.path, share:origin.share}})).catch(error => notice(error.message, true));
   } catch (error) { notice(error.message, true); }
  }
  function key(event) {
   if (!mounted || busy || event.defaultPrevented || event.isComposing || main.hidden || main.inert || keyBlocked(event.target, doc)) return;
   if ((event.ctrlKey || event.metaKey) && !event.altKey && String(event.key).toLowerCase() === 'a') {
    event.preventDefault(); selected.clear(); for (const index of allowed.keys()) selected.add(index); update(); return;
   }
   if((event.ctrlKey||event.metaKey)&&!event.altKey&&['c','x','v'].includes(event.key.toLowerCase())&&!doc.defaultView?.getSelection?.()?.toString()){event.preventDefault();clip({c:'copy',x:'cut',v:'paste'}[event.key.toLowerCase()]);return;}
   if (event.ctrlKey || event.metaKey || event.altKey) return;
   const items = selectedEntries();
   if (event.key === 'Escape' && items.length) { event.preventDefault(); clear(); return; }
   if (event.key === 'F2' && items.length === 1 && ctx.writable && items[0].mutable === true) { event.preventDefault(); invoke('file-rename', items[0]); return; }
   if (event.key !== 'Delete' || !items.length) return;
   event.preventDefault();
   if (!ctx.writable || items.some(entry => entry.mutable !== true)) { notice('Die Auswahl enthält schreibgeschützte Einträge.', true); return; }
   if (origin.share === '@system') {
    if(items.length===1)invoke('file-delete',items[0]);else openBatch('delete');
   } else openBatch('trash');
  }
  function openBatch(action, sourceClipboard=null) {
   if (!['copy','move','trash','delete'].includes(action) || busy || !mounted) return;
   let items;
   try { items = batchEntries(action, sourceClipboard?.entries || selectedEntries()); }
   catch (error) { notice(error.message, true); return; }
   const source = sourceClipboard || origin;
   if (!items.length) return;
   if (action !== 'copy' && (!ctx.writable || items.some(entry => entry.mutable !== true))) { notice('Die Auswahl enthält schreibgeschützte Einträge.', true); return; }
   if (action === 'delete' && !ctx.admin) { notice('Dauerhaftes Löschen benötigt Administratorrechte.', true); return; }
   if (action === 'trash' && origin.share === '@system') { notice('Systemeinträge bitte einzeln löschen und den jeweiligen Pfad bestätigen.', true); return; }
   if (!['trash','delete'].includes(action) && !targets.length) { notice('Es gibt keine beschreibbare Zielfreigabe.', true); return; }
   operation?.cleanup();
   const title = {copy:'Auswahl kopieren', move:'Auswahl verschieben', trash:'Auswahl in den Papierkorb',delete:'Auswahl dauerhaft löschen'}[action];
   const selectField = ctx.selectField || ((label, name, options, value) => `<label class="field">${esc(label)}<select name="${name}">${options.map(([key, text]) => `<option value="${esc(key)}" ${key === value ? 'selected' : ''}>${esc(text)}</option>`).join('')}</select></label>`);
   const field = ctx.field || ((label, name, type, value, attributes, hint) => `<label class="field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${attributes}><small>${esc(hint)}</small></label>`);
   const formEnd = ctx.formEnd || (label => `<div class="form-actions"><button type="submit" class="button primary">${esc(label)}</button><button type="button" class="button" data-action="close" ${label.startsWith('Ja')?'autofocus':''}>${label.startsWith('Ja')?'Nein':'Abbrechen'}</button></div></form>`);
   const folderPicker = doc.defaultView?.TitanFolderPicker || (typeof window !== 'undefined' ? window.TitanFolderPicker : null);
   const initialDestination = targets.some(item => item.name === origin.share) ? origin.path : '';
   const destination = action==='delete'?'<p>Die ausgewählten Dateien und Ordner werden dauerhaft gelöscht. Möchtest du fortfahren?</p>':action === 'trash' ? '<p>Die Auswahl wird in .titan-trash auf dieser Freigabe verschoben.</p>' : `${selectField('Zielfreigabe','destination_share',targets.map(item => [item.name,item.label]),targets.some(item => item.name === origin.share) ? origin.share : targets[0].name)}${folderPicker ? folderPicker.render({initialPath:initialDestination,pathField:'destination',shareField:'destination_share'}) : field('Vorhandener Zielordner','destination','text',origin.path,'maxlength="4096"','Relativ zur Zielfreigabe, z. B. Archiv. Leer bedeutet Hauptordner. Die Namen bleiben erhalten; vorhandene Ziele werden nicht überschrieben.')}`;
   ctx.dialog(title, `<div data-file-batch-content><p class="subtitle">${items.length} Einträge aus ${esc(source.share)} / ${esc(source.path || 'Hauptordner')}</p><form data-file-batch-form>${destination}<p class="hint">Einträge werden nacheinander verarbeitet. Abbrechen stoppt nach dem laufenden Eintrag.</p><p class="error-text" role="alert" data-file-batch-error></p>${formEnd(['trash','delete'].includes(action) ? 'Ja, löschen' : action === 'copy' ? 'Kopieren' : 'Verschieben')}<section data-file-batch-progress hidden><p role="status" aria-live="polite" data-file-batch-status></p><ol class="file-batch-results" data-file-batch-results></ol><div class="form-actions"><button type="button" class="button" data-file-batch-stop>Nach diesem Eintrag abbrechen</button></div></section></div>`);
   const modal = doc.querySelector('#dialog');
   const area = modal?.querySelector('[data-file-batch-content]');
   const form = area?.querySelector('[data-file-batch-form]');
   if (!modal || !form) { notice('Der Auswahldialog konnte nicht geöffnet werden.', true); return; }
   const progress = area.querySelector('[data-file-batch-progress]'), status = area.querySelector('[data-file-batch-status]'), resultsNode = area.querySelector('[data-file-batch-results]'), stopButton = area.querySelector('[data-file-batch-stop]'), errorNode = area.querySelector('[data-file-batch-error]');
   const listeners = [], modalController = new AbortController();
   const op = {running:false, stop:false, cleanup(){folderPicker?.disposeWithin?.(area);modalController.abort();listeners.splice(0).forEach(remove => remove());}};
   operation = op;
   if (!['trash','delete'].includes(action)) folderPicker?.mount?.(area, {api:ctx.api,toast:ctx.toast,initialPath:initialDestination,pathField:'destination',shareField:'destination_share'});
   const own = () => area.isConnected !== false && modal.querySelector('[data-file-batch-content]') === area;
   function bind(node, type, listener, options = {}) {
    node.addEventListener(type, listener, {...options, signal:modalController.signal});
    listeners.push(() => node.removeEventListener(type, listener, options));
   }
   function requestStop() {
    if (!op.running) return;
    op.stop = true;
    if (own()) { status.textContent = 'Abbruch angefordert. Der laufende Eintrag wird noch abgeschlossen.'; stopButton.disabled = true; }
   }
   const stateLabels = {pending:'Noch offen', running:'Läuft …', completed:'Abgeschlossen', failed:'Fehlgeschlagen', skipped:'Nicht begonnen · abgebrochen'};
   function render(results, index) {
    if (!own()) { op.stop = true; return; }
    if (!op.stop) status.textContent = index < results.length ? `${Math.min(index + 1, results.length)} von ${results.length}: ${results[index].name}` : 'Verarbeitung abgeschlossen.';
    resultsNode.innerHTML = results.map(item => `<li class="file-batch-result ${item.status === 'failed' ? 'error-text' : ''}"><strong>${esc(item.name)}</strong> · ${stateLabels[item.status]}${item.error ? `<div>${esc(item.error)}</div>` : ''}</li>`).join('');
   }
   async function submit(event) {
    event.preventDefault();
    if (op.running) return;
    if (!mounted) { notice('Diese Dateiansicht ist nicht mehr geöffnet. Wähle die Einträge erneut aus.', true); return; }
    let snapshot;
    try {
     const data = new doc.defaultView.FormData(form);
     const destinationShare = String(data.get('destination_share') || '');
     if (!['trash','delete'].includes(action) && !targets.some(item => item.name === destinationShare)) throw new Error('Wähle eine beschreibbare Zielfreigabe.');
     snapshot = Object.freeze({share:source.share,path:source.path, action, entries:items.map(item => Object.freeze({...item})), destinationShare, destinationFolder:['trash','delete'].includes(action) ? '' : normalizeFolder(data.get('destination'))});
    } catch (error) { errorNode.textContent = error.message; return; }
    op.running = true; op.stop = false; busy = true; update(); form.hidden = true; progress.hidden = false; errorNode.textContent = '';
    try {
     // Verify the entered folder before the first mutation, including an empty root path.
     if (!['trash','delete'].includes(action)) { status.textContent = 'Zielordner wird geprüft …'; await ctx.api(`/api/files?${new URLSearchParams({share:snapshot.destinationShare, path:snapshot.destinationFolder, limit:'1'})}`); }
     const results = await serialBatch(ctx.api, snapshot, render, () => op.stop);
     const completed = results.filter(item => item.status === 'completed').length;
     const failed = results.filter(item => item.status === 'failed').length;
     const skipped = results.filter(item => item.status === 'skipped').length;
     if(sourceClipboard&&action==="move"&&completed===items.length)clipboard=null;
     const summary = `${completed} abgeschlossen · ${failed} fehlgeschlagen · ${skipped} nicht begonnen.`;
     if (own()) {
      status.textContent = summary;
      stopButton.parentElement.innerHTML = '<button type="button" class="button primary" data-action="close">Schließen</button>';
     }
     if (mounted) for (const item of results) if (item.status === 'completed') selected.delete(item.index);
     notice(summary, failed > 0);
     op.running = false; busy = false; update(); op.cleanup();
     if (mounted && completed && ctx.navigate) Promise.resolve(ctx.navigate()).catch(error => notice(error.message, true));
    } catch (error) {
     notice(error.message || 'Verarbeitung fehlgeschlagen.', true);
     if (own()) { errorNode.textContent = error.message || 'Verarbeitung fehlgeschlagen.'; form.hidden = false; progress.hidden = true; }
     op.running = false; busy = false; update();
     if (!mounted || op.stop) op.cleanup();
    }
   }
   bind(form, 'submit', submit);
   bind(stopButton, 'click', requestStop);
   bind(modal, 'cancel', event => { if (op.running) { event.preventDefault(); requestStop(); } });
   bind(modal, 'close', () => { requestStop(); if (!op.running) op.cleanup(); });
   bind(modal, 'click', event => {
    if (op.running && event.target.closest?.('[data-action="close"]')) {
     event.preventDefault(); event.stopImmediatePropagation?.(); event.stopPropagation?.(); requestStop();
    }
   }, {capture:true});
  }
  listen(main, 'change', change);
  listen(main, 'click', click);
  listen(doc, 'keydown', key);
  current = {destroy(){
   mounted = false; controller.abort(); removers.splice(0).forEach(remove => remove()); selected.clear();
   // A submitted batch owns its modal until completion, allowing cancellation
   // while its frozen requests finish independently of page navigation.
   if (!operation?.running) operation?.cleanup();
  }};
  update();
 }
 return {mount, dispose, limit, eligible, normalizeFolder, destinationPath, keyBlocked, serialBatch};
});
