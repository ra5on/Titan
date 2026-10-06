'use strict';
// Exercise the module's page and modal lifetimes without a host or network.
const assert = require('node:assert/strict');
const files = require('../titan/web/files_controls.js');
const camel = text => text.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
const record = (path, body) => ({path, method:body ? 'POST' : 'GET', body:body ? {...body} : {action:'list', ...Object.fromEntries(new URL(path, 'http://nas').searchParams)}});
const actionOf = body => body?.action || 'list';
class Element {
 constructor(tag = 'div', attributes = {}) {
  this.tagName = tag.toUpperCase(); this.attributes = {...attributes}; this.dataset = {}; this.children = []; this.parentElement = null;
  this.hidden = false; this.disabled = false; this.checked = false; this.indeterminate = false; this.textContent = ''; this.innerHTML = ''; this.events = new Map(); this.value = attributes.value || '';
  for (const [name, value] of Object.entries(attributes)) if (name.startsWith('data-')) this.dataset[camel(name.slice(5))] = value;
 }
 append(...children) {
  for (const child of children) { child.parentElement = this; child.ownerDocument = this.ownerDocument; this.children.push(child); if (child.children.length) { const adopt = node => { node.ownerDocument = this.ownerDocument; node.children.forEach(adopt); }; adopt(child); } }
 }
 matches(selector) {
  if (selector.startsWith('#')) return this.attributes.id === selector.slice(1);
  const tag = selector.match(/^[a-z]+/i)?.[0];
  if (tag && this.tagName !== tag.toUpperCase()) return false;
  const attrs = [...selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)];
  if (attrs.length) return attrs.every(([, name, value]) => name === 'hidden' ? this.hidden : name in this.attributes && (value === undefined || this.attributes[name] === value));
  return Boolean(tag);
 }
 querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
 querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
 closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
 contains(node) { return node === this || this.children.some(child => child.contains(node)); }
 getAttribute(name) { return this.attributes[name] ?? null; }
 setAttribute(name, value) { this.attributes[name] = value; }
 removeAttribute(name) { delete this.attributes[name]; }
 get isConnected() { return this.tagName === 'DOCUMENT' || Boolean(this.parentElement?.isConnected); }
 addEventListener(type, listener, options = {}) {
  const listeners = this.events.get(type) || new Set(); listeners.add(listener); this.events.set(type, listeners);
  options.signal?.addEventListener('abort', () => this.removeEventListener(type, listener), {once:true});
 }
 removeEventListener(type, listener) { const listeners = this.events.get(type); listeners?.delete(listener); if (!listeners?.size) this.events.delete(type); }
 dispatch(type, details = {}) {
  const event = {type, target:this, defaultPrevented:false, stopped:false, preventDefault(){this.defaultPrevented = true;}, stopPropagation(){this.stopped = true;}, stopImmediatePropagation(){this.immediateStopped = true;}, ...details};
  const pending = [];
  for (const listener of [...(this.events.get(type) || [])]) { pending.push(listener(event)); if (event.immediateStopped) break; }
  event.done = Promise.all(pending); return event;
 }
 showModal() { this.open = true; this.attributes.open = ''; }
 close() { this.open = false; delete this.attributes.open; return this.dispatch('close'); }
}
function fixture(entries, options = {}) {
 const doc = new Element('document'); doc.ownerDocument = doc;
 doc.defaultView = {FormData:class { constructor(form){this.values = new Map(form.values);} get(name){return this.values.get(name) ?? null;} }};
 const main = new Element('main'), modal = new Element('dialog', {id:'dialog'}); doc.append(main, modal);
 const all = new Element('input', {'data-file-select-all':''}), count = new Element('span', {'data-file-selection-count':''}), bar = new Element('div', {'data-file-selection-bar':''});
 const buttons = {};
 for (const action of ['copy','move','trash','delete','clear']) { buttons[action] = new Element('button', {'data-file-batch':action}); bar.append(buttons[action]); }
 const singles={}; for(const action of ['file-rename','file-edit','file-preview']){singles[action]=new Element('button',{'data-file-single':action});bar.append(singles[action]);}
 main.append(all, count, bar);
 const boxes = entries.map((entry, index) => { const label = new Element('label'); const box = new Element('input', {'data-file-select':'', value:String(index)}); label.append(box); main.append(label); return box; });
 const requests = [], notices = [], actions = []; let navigations = 0, dialogBody = '';
 const ctx = {entries, share:options.share || 'source', path:options.path ?? 'folder', writable:options.writable ?? true, targets:[{name:'source', label:'Quelle'}, {name:'destination', label:'Ziel'}], api:async (path, body) => {requests.push(record(path, body)); return {};}, toast:(message, error) => notices.push({message, error}), navigate:() => {navigations++;}, actions:{'file-delete':target => actions.push({action:'delete', path:target.dataset.path}), 'file-rename':target => actions.push({action:'rename', path:target.dataset.path})},
  dialog(title, html) {
   dialogBody = html; modal.children.forEach(node => node.parentElement = null); modal.children = [];
   const area = new Element('div', {'data-file-batch-content':''}), form = new Element('form', {'data-file-batch-form':''}), progress = new Element('section', {'data-file-batch-progress':''});
   form.values = new Map([['destination_share','destination'], ['destination','archive']]);
   form.append(new Element('p', {'data-file-batch-error':''}));
   progress.append(new Element('p', {'data-file-batch-status':''}), new Element('ol', {'data-file-batch-results':''}));
   const stopContainer = new Element('div'); stopContainer.append(new Element('button', {'data-file-batch-stop':''})); progress.append(stopContainer); area.append(form, progress); modal.append(area, new Element('button', {'data-action':'close'})); modal.showModal();
  }, ...options.ctx};
 const change = (index, checked = true) => {boxes[index].checked = checked; return main.dispatch('change', {target:boxes[index]});};
 const selectAll = (checked = true) => {all.checked = checked; return main.dispatch('change', {target:all});};
 const click = action => main.dispatch('click', {target:buttons[action]});
 const key = (key, extra = {}) => doc.dispatch('keydown', {target:main, key, ...extra});
 const submit = values => {const form = modal.querySelector('[data-file-batch-form]'); for (const [name, value] of Object.entries(values || {})) form.values.set(name, value); return form.dispatch('submit').done;};
 const result = () => modal.querySelector('[data-file-batch-results]').innerHTML;
 const status = () => modal.querySelector('[data-file-batch-status]').textContent;
 return {doc, main, modal, all, count, bar, boxes, buttons, singles, ctx, requests, notices, actions, change, selectAll, click, key, submit, result, status, navigations:() => navigations, dialogBody:() => dialogBody};
}
const entry = (name, extra = {}) => ({name, directory:false, readable:true, mutable:true, size:10, ...extra});
const turn = () => new Promise(resolve => setImmediate(resolve));
(async () => {
 assert.equal(files.normalizeFolder(''), '');
 assert.equal(files.normalizeFolder('./archive//2026/'), 'archive/2026');
 assert.equal(files.destinationPath('archive', 'name <&>.txt'), 'archive/name <&>.txt');
 assert.throws(() => files.normalizeFolder('/absolute'), /relativ/);
 assert.throws(() => files.normalizeFolder('archive/../escape'), /relativ/);
 assert.throws(() => files.destinationPath('archive', 'nested/file'), /Dateiname/);
 // Ordinary readable entries alone are selectable. A page cannot expand beyond 200.
 const many = fixture([...Array.from({length:205}, (_, index) => entry(`file-${index}`)), entry('link', {symlink:true}), entry('secret', {readable:false})]);
 files.mount(many.main, many.ctx); many.selectAll();
 assert.equal(many.count.textContent, '200 ausgewählt'); assert(many.all.checked); assert(!many.all.indeterminate);
 assert(many.boxes.slice(200).every(box => box.disabled && !box.checked));
 many.change(0, false); assert(many.all.indeterminate); assert(!many.all.checked);
 many.click('clear'); assert.equal(many.count.textContent, '0 ausgewählt'); assert(many.bar.hidden);
 many.key('a', {ctrlKey:true}); assert.equal(many.count.textContent, '200 ausgewählt');
 const eventsBefore = many.doc.events.size; files.dispose(); assert(eventsBefore > 0); assert.equal(many.doc.events.size, 0); assert.equal(many.main.events.size, 0);
 const filtered = fixture([entry('read-only', {mutable:false}), entry('link', {symlink:true}), entry('hidden'), entry('secret', {readable:false})]);
 filtered.boxes[2].hidden = true; files.mount(filtered.main, filtered.ctx); filtered.selectAll();
 assert.equal(filtered.count.textContent, '1 ausgewählt'); assert(!filtered.buttons.copy.disabled); assert(filtered.buttons.move.disabled); assert(filtered.buttons.trash.disabled);
 const topActions=fixture([entry('one.txt'),entry('two.txt'),entry('locked',{mutable:false})],{ctx:{admin:true}});files.mount(topActions.main,topActions.ctx);
 topActions.change(0);assert(!topActions.singles['file-rename'].disabled);assert(!topActions.singles['file-edit'].disabled);assert(!topActions.buttons.delete.disabled);
 topActions.main.dispatch('click',{target:topActions.singles['file-rename']});assert.deepEqual(topActions.actions.at(-1),{action:'rename',path:'folder/one.txt'});
 topActions.change(1);assert(topActions.singles['file-rename'].disabled);assert(topActions.singles['file-edit'].disabled);assert(!topActions.buttons.delete.disabled);
 topActions.change(2);assert(topActions.buttons.delete.disabled);topActions.click('clear');assert(topActions.singles['file-edit'].disabled);
 files.mount(filtered.main,filtered.ctx);
 // Inputs, editors, dialogs and the mobile modal drawer keep their own shortcuts.
 filtered.click('clear');
 for (const tag of ['input','textarea','select']) { const field = new Element(tag); filtered.main.append(field); assert(!filtered.key('a', {ctrlKey:true, target:field}).defaultPrevented); assert.equal(filtered.count.textContent, '0 ausgewählt'); }
 const editable = new Element('div', {contenteditable:'true'}), nested = new Element('span'); editable.append(nested); filtered.main.append(editable);
 assert(!filtered.key('a', {ctrlKey:true, target:nested}).defaultPrevented);
 filtered.modal.showModal(); assert(!filtered.key('a', {ctrlKey:true}).defaultPrevented); filtered.modal.close();
 const drawer = new Element('aside', {role:'dialog','aria-modal':'true'}); filtered.doc.append(drawer); assert(!filtered.key('a', {ctrlKey:true}).defaultPrevented); drawer.removeAttribute('aria-modal');
 assert(filtered.key('a', {metaKey:true}).defaultPrevented); assert.equal(filtered.count.textContent, '1 ausgewählt');
 assert(!filtered.key('F2').defaultPrevented); assert.equal(filtered.actions.length, 0);
 assert(filtered.key('Delete').defaultPrevented); assert.match(filtered.notices.at(-1).message, /schreibgeschützte/);
 assert(filtered.key('Escape').defaultPrevented); assert.equal(filtered.count.textContent, '0 ausgewählt');
 // F2 renames one mutable entry. System Delete always uses the existing exact-path dialog.
 const system = fixture([entry('one'), entry('two')], {share:'@system', path:'etc', ctx:{admin:true}}); files.mount(system.main, system.ctx);
 system.change(0); assert(system.key('F2').defaultPrevented); assert.deepEqual(system.actions.at(-1), {action:'rename', path:'etc/one'});
 assert(system.key('Delete').defaultPrevented); assert.deepEqual(system.actions.at(-1), {action:'delete', path:'etc/one'}); assert(system.buttons.trash.disabled);
 system.change(1); const numberOfActions = system.actions.length; system.key('Delete'); assert.equal(system.actions.length, numberOfActions); assert.match(system.dialogBody(), /dauerhaft gelöscht/);
 assert(!system.key('s', {ctrlKey:true}).defaultPrevented);
 // Delete on a normal share opens a confirmation form and performs no operation until submit.
 const trash = fixture([entry('one'), entry('two')]); files.mount(trash.main, trash.ctx); trash.selectAll(); trash.key('Delete');
 assert.equal(trash.requests.length, 0); assert.match(trash.dialogBody(), /\.titan-trash/); await trash.submit();
 assert.deepEqual(trash.requests.map(request => request.body), [{share:'source', path:'folder/one', action:'trash'}, {share:'source', path:'folder/two', action:'trash'}]);
 assert.match(trash.status(), /2 abgeschlossen · 0 fehlgeschlagen/); assert.equal(trash.navigations(), 1);
 // Recursive results can include a folder and its children. The parent operation
 // already handles those children, even if the search lists them first.
 for (const action of ['copy','move','trash','delete']) {
  const nested = fixture([
   entry('notes.txt', {path:'projects/reports/notes.txt'}),
   entry('reports', {path:'projects/reports', directory:true}),
   entry('budget.csv', {path:'projects/reports/2026/budget.csv'}),
   entry('reports-archive.txt', {path:'projects/reports-archive.txt'})
  ], {ctx:{admin:true}});
  files.mount(nested.main, nested.ctx); nested.selectAll(); nested.click(action); await nested.submit();
  const mutations = nested.requests.filter(request => request.method === 'POST');
  assert.deepEqual(mutations.map(request => request.body.path), ['projects/reports','projects/reports-archive.txt']);
  assert(mutations.every(request => request.body.action === action));
  assert.match(nested.status(), /2 abgeschlossen · 0 fehlgeschlagen/);
 }
 // Identical basenames in different search folders must never cause a partial
 // flat transfer. Reject the selection before even inspecting the destination.
 for (const action of ['copy','move']) {
  const duplicate = fixture([
   entry('report.txt', {path:'a/report.txt'}),
   entry('report.txt', {path:'b/report.txt'})
  ]);
  files.mount(duplicate.main, duplicate.ctx); duplicate.selectAll(); duplicate.click(action);
  assert.equal(duplicate.requests.length, 0);
  assert.equal(duplicate.modal.open, undefined);
  assert(duplicate.notices.at(-1).error);
  assert.match(duplicate.notices.at(-1).message, /report\.txt.*einzeln/);
 }
 let directCalls = 0;
 await assert.rejects(files.serialBatch(async () => {directCalls++;}, {
  action:'copy', share:'source', destinationShare:'destination', destinationFolder:'archive',
  entries:[entry('same.txt',{path:'first/same.txt'}),entry('same.txt',{path:'second/same.txt'})]
 }), /Mehrere ausgewählte/);
 assert.equal(directCalls, 0);
 // One destination conflict is recorded while subsequent files still complete.
 let inFlight = 0, maximum = 0;
 const transfer = fixture([entry('one'), entry('<bad&>.txt'), entry('three')], {ctx:{api:async (path, body) => {
  transfer.requests.push(record(path, body)); inFlight++; maximum = Math.max(maximum, inFlight); await turn(); inFlight--;
  if (actionOf(body) === 'copy' && body.path.includes('<bad&>')) throw new Error('Ziel <bestehend> & geschützt'); return {};
 }}});
 files.mount(transfer.main, transfer.ctx); transfer.selectAll(); transfer.click('copy'); await transfer.submit();
 assert.equal(maximum, 1); assert.equal(transfer.requests[0].method, 'GET'); assert.match(transfer.requests[0].path, /^\/api\/files\?/); assert.equal(transfer.requests[0].body.action, 'list'); assert.equal(transfer.requests[0].body.path, 'archive');
 assert.deepEqual(transfer.requests.slice(1).map(request => request.body.destination), ['archive/one', 'archive/<bad&>.txt', 'archive/three']);
 assert(transfer.requests.every(request => !('overwrite' in request.body)));
 assert.match(transfer.status(), /2 abgeschlossen · 1 fehlgeschlagen · 0 nicht begonnen/);
 assert.match(transfer.result(), /&lt;bad&amp;&gt;\.txt/); assert.match(transfer.result(), /Ziel &lt;bestehend&gt; &amp; geschützt/); assert(!transfer.result().includes('<bestehend>'));
 assert.equal(transfer.count.textContent, '1 ausgewählt'); assert(transfer.notices.at(-1).error);
 // The optional browser picker replaces manual folder entry without changing
 // the frozen source, destination, serial processing or no-overwrite contract.
 const pickerCalls = [], pickerView = fixture([entry('one')]);
 pickerView.doc.defaultView.TitanFolderPicker = {
  render(options){pickerCalls.push({kind:'render',options});return '<section data-folder-picker><input type="hidden" name="destination"></section>';},
  mount(area,options){pickerCalls.push({kind:'mount',options});},
  disposeWithin(area){pickerCalls.push({kind:'dispose'});}
 };
 files.mount(pickerView.main,pickerView.ctx);pickerView.change(0);pickerView.click('copy');
 assert.match(pickerView.dialogBody(),/data-folder-picker/);assert(!pickerView.dialogBody().includes('Vorhandener Zielordner'));
 assert.equal(pickerCalls.find(item=>item.kind==='render').options.initialPath,'folder');
 assert.equal(pickerCalls.find(item=>item.kind==='mount').options.api,pickerView.ctx.api);
 await pickerView.submit({destination_share:'destination',destination:'chosen/folder'});
 assert.deepEqual(pickerView.requests.at(-1).body,{share:'source',path:'folder/one',action:'copy',destination_share:'destination',destination:'chosen/folder/one'});
 assert(pickerCalls.some(item=>item.kind==='dispose'));
 // Folder validation occurs before mutation and leaves a useful inline error for retry.
 const missing = fixture([entry('one')], {ctx:{api:async (path, body) => {missing.requests.push(record(path, body)); throw new Error('Zielordner nicht vorhanden.');}}});
 files.mount(missing.main, missing.ctx); missing.change(0); missing.click('move'); await missing.submit();
 assert.equal(missing.requests.length, 1); assert.equal(missing.requests[0].body.action, 'list'); assert.match(missing.modal.querySelector('[data-file-batch-error]').textContent, /nicht vorhanden/);
 assert(!missing.modal.querySelector('[data-file-batch-form]').hidden); assert.equal(missing.navigations(), 0);
 await missing.submit({destination:'../escape'}); assert.equal(missing.requests.length, 1); assert.match(missing.modal.querySelector('[data-file-batch-error]').textContent, /relativ/);
 // Escape / the close button request cancellation after the current request.
 for (const cancellation of ['cancel','close-button','stop','closed']) {
  let release;
  const cancel = fixture([entry('one'), entry('two'), entry('three')], {ctx:{api:async (path, body) => {cancel.requests.push(record(path, body)); if (actionOf(body) === 'copy') await new Promise(resolve => {release = resolve;}); return {};}}});
  files.mount(cancel.main, cancel.ctx); cancel.selectAll(); cancel.click('copy'); const submitted = cancel.submit(); await turn();
  assert.equal(cancel.requests.length, 2);
  if (cancellation === 'cancel') assert(cancel.modal.dispatch('cancel').defaultPrevented);
  else if (cancellation === 'close-button') assert(cancel.modal.dispatch('click', {target:cancel.modal.querySelector('[data-action="close"]')}).defaultPrevented);
  else if (cancellation === 'stop') cancel.modal.querySelector('[data-file-batch-stop]').dispatch('click');
  else cancel.modal.close();
  release(); await submitted;
  assert.equal(cancel.requests.length, 2); assert.match(cancel.status(), /1 abgeschlossen · 0 fehlgeschlagen · 2 nicht begonnen/); assert.match(cancel.result(), /Nicht begonnen · abgebrochen/);
  if (cancellation === 'closed') assert.equal(cancel.modal.open, false);
 }
 // Navigating while an operation is pending preserves both source and destination.
 let finishFirst;
 const original = fixture([entry('first'), entry('second')], {path:'original', ctx:{api:async (path, body) => {
  original.requests.push(record(path, body)); if (actionOf(body) === 'move' && body.path === 'original/first') await new Promise(resolve => {finishFirst = resolve;}); return {};
 }}});
 files.mount(original.main, original.ctx); original.selectAll(); original.click('move'); const submitted = original.submit({destination_share:'destination', destination:'saved'}); await turn();
 original.ctx.share = 'different'; original.ctx.path = 'elsewhere'; original.ctx.entries[1].name = 'changed'; original.ctx.targets[1].name = 'changed-destination';
 files.dispose(); assert.equal(original.doc.events.size, 0); assert.equal(original.main.events.size, 0);
 const next = fixture([entry('new')], {share:'different', path:'elsewhere'}); files.mount(next.main, next.ctx); assert.equal(next.count.textContent, '0 ausgewählt');
 finishFirst(); await submitted;
 assert.deepEqual(original.requests.slice(1).map(request => request.body), [{share:'source', path:'original/first', action:'move', destination_share:'destination', destination:'saved/first'}, {share:'source', path:'original/second', action:'move', destination_share:'destination', destination:'saved/second'}]);
 assert.equal(original.navigations(), 0); assert.equal(next.navigations(), 0); assert.equal(next.count.textContent, '0 ausgewählt'); assert.match(original.result(), /Abgeschlossen/);
 // Replacing the modal stops the orphaned batch; completion cannot change a newer dialog.
 let releaseOrphan;
 const orphan = fixture([entry('one'), entry('two')], {ctx:{api:async (path, body) => {orphan.requests.push(record(path, body)); if (actionOf(body) === 'copy') await new Promise(resolve => {releaseOrphan = resolve;}); return {};}}});
 files.mount(orphan.main, orphan.ctx); orphan.selectAll(); orphan.click('copy'); const orphaned = orphan.submit(); await turn();
 const oldArea = orphan.modal.querySelector('[data-file-batch-content]'); oldArea.parentElement = null; orphan.modal.children = [new Element('p')]; orphan.modal.children[0].textContent = 'new dialog';
 releaseOrphan(); await orphaned; assert.equal(orphan.requests.length, 2); assert.equal(orphan.modal.children[0].textContent, 'new dialog');
 files.dispose();
 console.log('File controls UI: bounded page selection, modal guards, serial failures, cancellation, frozen navigation targets and escaped results passed.');
})().catch(error => {files.dispose(); console.error(error); process.exitCode = 1;});
