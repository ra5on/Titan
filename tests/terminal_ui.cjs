'use strict';
// No shell is started: xterm, SSE, HTTP, clipboard and page lifecycle are fakes.
const assert = require('node:assert/strict');
const terminal = require('../titan/web/terminal_controls.js');
const turns = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
class Node {
 constructor(id = '') { this.id = id; this.dataset = {}; this.disabled = false; this.children = []; this.listeners = new Map(); this.textContent = ''; }
 addEventListener(type, callback) { const listeners = this.listeners.get(type) || new Set(); listeners.add(callback); this.listeners.set(type, listeners); }
 removeEventListener(type, callback) { this.listeners.get(type)?.delete(callback); }
 dispatch(type, event = {}) { event.type = type; event.preventDefault ||= () => { event.prevented = true; }; for (const callback of this.listeners.get(type) || []) callback(event); return event; }
 querySelector(selector) { return this.children.find(child => '#' + child.id === selector) || null; }
 querySelectorAll(selector) { return selector === '[data-terminal-action]' ? this.children.filter(child => child.dataset.terminalAction) : []; }
 closest(selector) { return selector === '[data-terminal-action]' && this.dataset.terminalAction ? this : null; }
 contains(node) { return node === this || this.children.includes(node); }
 focus() { this.focused = true; }
 select() { this.selected = true; }
}
class FakeTerminal {
 constructor(options) { this.options = {...options}; this.cols = options.cols; this.rows = options.rows; this.selection = ''; this.sent = []; this.writes = []; this.callbacks = []; this.bracketed = false; this.autoWrite = true; this.disposed = false; }
 open(screen) { this.screen = screen; }
 loadAddon(addon) { this.addon = addon; addon.term = this; }
 attachCustomKeyEventHandler(callback) { this.key = callback; }
 onData(callback) { this.data = callback; return {dispose:() => { this.data = null; }}; }
 onBinary(callback) { this.binary = callback; return {dispose:() => { this.binary = null; }}; }
 resize(cols, rows) { this.cols = cols; this.rows = rows; }
 write(bytes, callback) { assert(bytes instanceof Uint8Array); this.writes.push(bytes); if (this.autoWrite) callback(); else this.callbacks.push(callback); }
 completeWrite() { this.callbacks.shift()?.(); }
 getSelection() { return this.selection; }
 hasSelection() { return Boolean(this.selection); }
 paste(text) { this.sent.push(text); const data = text.replace(/\r?\n/g, '\r'); this.data?.(this.bracketed ? '\x1b[200~' + data + '\x1b[201~' : data); }
 focus() { this.focused = true; }
 clear() { this.clears = (this.clears || 0) + 1; }
 dispose() { this.disposed = true; }
}
function fixture(overrides = {}) {
 const main = new Node('main'), screen = new Node('terminal-screen'), state = new Node('terminal-state');
 const buttons = Object.fromEntries(['open','close','copy','paste','interrupt','clear'].map(action => { const button = new Node(); button.dataset.terminalAction = action; return [action,button]; }));
 main.children = [screen,state,...Object.values(buttons)];
 const requests = [], streams = [], notices = [], dialogs = [], clipboardWrites = [], copyField = new Node(), pasteField = new Node();
 const timers = new Map(); let nextTimer = 0, resizeObserver;
 const view = new Node(); view.fetches = []; view.navigator = {clipboard:{writeText:async text => clipboardWrites.push(text), readText:async () => 'from clipboard\n'}};
 view.setTimeout = callback => { const id = ++nextTimer; timers.set(id,callback); return id; }; view.clearTimeout = id => timers.delete(id);
 view.flushTimers = () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(callback => callback()); };
 view.fetch = async (path, args) => { view.fetches.push({path,...args}); return {ok:true}; };
 view.ResizeObserver = class { constructor(callback) { this.callback = callback; resizeObserver = this; } observe(target) { this.target = target; } disconnect() { this.disconnected = true; } };
 view.EventSource = class {
  constructor(url) { this.url = url; this.listeners = new Map(); this.closed = false; streams.push(this); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  emit(name, value) { this.listeners.get(name)?.({data:JSON.stringify(value)}); }
  close() { this.closed = true; }
 };
 const doc = {defaultView:view, querySelector:selector => selector === '[data-terminal-copy]' ? copyField : selector === '#terminal-paste-text' ? pasteField : null};
 main.ownerDocument = doc;
 const term = new FakeTerminal({cols:80,rows:24}), fit = {fit() { if (fit.size) term.resize(fit.size.cols,fit.size.rows); }};
 const api = async (path, body) => { requests.push({path,body}); return overrides.api ? overrides.api(path,body) : body.action === 'create' ? {id:'session-' + requests.filter(item => item.body.action === 'create').length,cols:body.cols,rows:body.rows} : {ok:true}; };
 const ctx = {api, csrf:'test-csrf', toast:(text,error) => notices.push({text,error}), dialog:(title,html,submit) => dialogs.push({title,html,submit}), terminalFactory:() => term, fitFactory:() => fit};
 const controller = terminal.mount(main,ctx);
 const writes = () => requests.filter(item => item.body.action === 'write').map(item => Buffer.from(item.body.data,'base64'));
 const click = action => main.dispatch('click',{target:buttons[action]});
 return {main,screen,state,buttons,view,term,fit,ctx,controller,requests,streams,notices,dialogs,clipboardWrites,copyField,pasteField,writes,click,observer:() => resizeObserver};
}
(async () => {
 assert.deepEqual(terminal.dimensions(999,-1),{cols:500,rows:5});
 assert.deepEqual(terminal.dimensions('bad',0),{cols:80,rows:24});
 const bytes = Uint8Array.from([0,127,128,255]);
 assert.deepEqual(terminal.base64ToBytes(terminal.bytesToBase64(bytes)),bytes);
 assert.deepEqual(terminal.binaryBytes('\x00\xff'),Uint8Array.from([0,255]));
 assert.throws(() => terminal.binaryBytes('€'),/binäre/);
 assert.throws(() => terminal.base64ToBytes('<script>'),/Ungültige/);

 // Mounting creates no shell; repeated connection clicks create one session.
 let v = fixture();
 assert.equal(v.requests.length,0); assert.equal(v.buttons.open.disabled,false); assert.equal(v.buttons.paste.disabled,true);
 const opening = v.controller.open(); await v.controller.open(); await opening;
 assert.equal(v.requests.filter(item => item.body.action === 'create').length,1);
 assert.equal(v.streams[0].url,'/api/terminal/output?id=session-1'); assert.equal(v.term.options.disableStdin,false);
 assert.equal(v.buttons.open.disabled,true); assert.equal(v.buttons.close.disabled,false);

 // Arrow keys and UTF-8 are serialized with binary mouse bytes without coercion.
 v.term.data('ä😀'); v.term.data('\x1b[A'); v.term.binary('\x00\xff'); await turns();
 assert.deepEqual(Buffer.concat(v.writes()),Buffer.concat([Buffer.from('ä😀\x1b[A','utf8'),Buffer.from([0,255])]));
 assert(v.requests.every(item => item.path === '/api/terminal'));
 let key = {type:'keydown',key:'c',ctrlKey:true,shiftKey:false,preventDefault(){this.prevented=true;}};
 assert.equal(v.term.key(key),true); v.term.data('\x03'); await turns(); assert.equal(v.writes().at(-1)[0],3);
 v.term.selection = 'selected text'; key = {...key}; assert.equal(v.term.key(key),false); await turns();
 assert.equal(v.clipboardWrites.at(-1),'selected text'); assert.equal(v.writes().at(-1)[0],3);
 v.click('interrupt'); await turns(); assert.equal(v.writes().at(-1)[0],3);
 const beforeClear = v.requests.length; v.click('clear'); assert.equal(v.term.clears,1); assert.equal(v.requests.length,beforeClear);

 // Ordinary Ctrl+V uses native paste; explicit paste honors xterm modes.
 const nativeKey = {...key,key:'v',prevented:false}; assert.equal(v.term.key(nativeKey),false); assert.equal(nativeKey.prevented,false);
 v.term.bracketed = true;
 const native = v.screen.dispatch('paste',{clipboardData:{getData:type => type === 'text/plain' ? 'native ä\n' : ''},stopImmediatePropagation(){this.stopped=true;}});
 await turns(); assert(native.prevented && native.stopped); assert.equal(v.term.sent.at(-1),'native ä\n');
 assert.equal(v.writes().at(-1).toString(),'\x1b[200~native ä\r\x1b[201~');
 await v.controller.paste(); await turns(); assert.equal(v.term.sent.at(-1),'from clipboard\n');
 const shortcut = {...key,key:'V',shiftKey:true}; assert.equal(v.term.key(shortcut),false); await turns(); assert(shortcut.prevented);

 // Shell output is bytes, with escape sequences, never HTML inserted into DOM.
 const output = Buffer.from('<img src=x onerror=evil()>\x1b[31mä\x1b[0m');
 v.streams[0].emit('output',{data:output.toString('base64')});
 assert.deepEqual(Buffer.from(v.term.writes.at(-1)),output); assert.equal(v.screen.innerHTML,undefined);
 v.term.autoWrite = false;
 v.streams[0].emit('output',{data:Buffer.from('first').toString('base64')});
 v.streams[0].emit('output',{data:Buffer.from('second').toString('base64')});
 assert.equal(Buffer.from(v.term.writes.at(-1)).toString(),'first');
 v.streams[0].emit('exit',{exit_code:0}); assert(v.streams[0].closed); assert.equal(v.state.dataset.state,'ended');
 v.term.completeWrite(); await turns(); assert.equal(Buffer.from(v.term.writes.at(-1)).toString(),'second'); v.term.completeWrite();
 v.term.data('after exit'); await turns(); assert(!v.writes().some(item => item.toString() === 'after exit'));
 terminal.dispose(); assert(v.term.disposed); assert(v.observer().disconnected);

 // Denied/HTTP clipboard permissions offer escaped selection and a paste form.
 v = fixture(); await v.controller.open();
 v.view.navigator.clipboard.writeText = async () => { throw Error('denied'); };
 v.view.navigator.clipboard.readText = async () => { throw Error('denied'); };
 v.term.selection = '</textarea><script>secret()</script>'; await v.controller.copy();
 assert(v.dialogs.at(-1).html.includes('&lt;/textarea&gt;&lt;script&gt;')); assert(!v.dialogs.at(-1).html.includes('<script>'));
 assert(v.copyField.focused && v.copyField.selected); assert(v.dialogs.at(-1).html.includes('Strg+C'));
 await v.controller.paste(); assert(v.pasteField.focused); const form = v.dialogs.at(-1);
 assert(form.html.includes('name="text"')); await form.submit(new Map([['text','manual ä\n']])); await turns();
 assert.equal(v.term.sent.at(-1),'manual ä\n');
 v.controller.close(); await assert.rejects(form.submit(new Map([['text','stale paste']])),/inzwischen beendet/);
 terminal.dispose();

 // A multi-byte character crossing the 16 KiB boundary arrives byte-for-byte.
 const held = deferred(); let first = true;
 v = fixture({api:async (path,body) => body.action === 'create' ? {id:'bytes',cols:80,rows:24} : body.action === 'write' && first ? (first=false,held.promise) : {ok:true}});
 await v.controller.open(); v.view.navigator.clipboard.readText = async () => 'a'.repeat(16383) + '😀ä'.repeat(3000);
 await v.controller.paste(); v.term.data('\x1b[D');
 assert.equal(v.writes().length,1); assert.equal(v.writes()[0].length,16384);
 held.resolve({ok:true}); await turns();
 assert(v.writes().every(item => item.length <= terminal.chunkLimit));
 assert.deepEqual(Buffer.concat(v.writes()),Buffer.from('a'.repeat(16383) + '😀ä'.repeat(3000) + '\x1b[D'));
 terminal.dispose();

 // The bounded queue rejects a whole input instead of sending a truncated half.
 const blocked = deferred();
 v = fixture({api:async (path,body) => body.action === 'create' ? {id:'bounded',cols:80,rows:24} : body.action === 'write' ? blocked.promise : {ok:true}});
 await v.controller.open(); v.term.data('x'.repeat(terminal.inputLimit)); v.term.data('do not truncate');
 assert.equal(v.writes().length,1); assert(v.notices.at(-1).text.includes('64 KiB'));
 v.view.navigator.clipboard.readText = async () => 'y'.repeat(terminal.inputLimit + 1); await v.controller.paste();
 assert.equal(v.term.sent.length,0); assert(v.notices.at(-1).text.includes('Text nicht eingefügt'));
 v.controller.close(); blocked.resolve({ok:true}); await turns(); assert.equal(v.writes().length,1);
 terminal.dispose();

 // A stale HTTP write cannot block input or kill an explicitly opened new shell.
 const staleWrite = deferred(); let created = 0;
 v = fixture({api:async (path,body) => body.action === 'create' ? {id:'race-' + (++created),cols:80,rows:24} : body.action === 'write' && body.id === 'race-1' ? staleWrite.promise : {ok:true}});
 await v.controller.open(); v.term.data('old session'); v.controller.close();
 await v.controller.open(); v.term.data('new session'); await turns();
 assert(v.requests.some(item => item.body.action === 'write' && item.body.id === 'race-2'));
 staleWrite.reject(Error('old request failed')); await turns(); assert.equal(v.state.dataset.state,'connected');
 assert.equal(v.streams[1].closed,false); terminal.dispose();

 // Fit dimensions are clamped, resizing is debounced and stale responses stop.
 v = fixture(); await v.controller.open(); v.view.flushTimers(); await turns();
 v.fit.size = {cols:700,rows:2}; v.observer().callback(); v.observer().callback();
 v.view.flushTimers(); await turns();
 assert.equal(v.term.cols,500); assert.equal(v.term.rows,5);
 assert.deepEqual(v.requests.filter(item => item.body.action === 'resize').at(-1).body,{action:'resize',id:'session-1',cols:500,rows:5});
 const stream = v.streams[0], beforeFailure = v.requests.length;
 stream.onerror(); await turns(); assert(stream.closed); assert.equal(v.state.dataset.state,'failed'); assert.equal(v.buttons.open.disabled,false);
 stream.emit('output',{data:Buffer.from('stale output').toString('base64')});
 assert(!v.term.writes.some(item => Buffer.from(item).toString() === 'stale output'));
 assert.equal(v.requests.slice(beforeFailure).filter(item => item.body.action === 'create').length,0);
 terminal.dispose();

 // Session cleanup uses the captured ID even after disposal, including late create.
 const late = deferred();
 v = fixture({api:async (path,body) => body.action === 'create' ? late.promise : {ok:true}});
 const pendingOpen = v.controller.open(); terminal.dispose(); late.resolve({id:'orphan',cols:80,rows:24}); await pendingOpen;
 assert(v.requests.some(item => item.body.action === 'close' && item.body.id === 'orphan')); assert.equal(v.streams.length,0);
 v = fixture(); await v.controller.open();
 v.view.dispatch('pagehide'); await turns();
 assert.equal(v.view.fetches.length,1); assert.equal(v.view.fetches[0].keepalive,true); assert.equal(v.view.fetches[0].headers['X-CSRF-Token'],'test-csrf');
 assert.deepEqual(JSON.parse(v.view.fetches[0].body),{action:'close',id:'session-1'});
 assert(v.term.disposed); assert(v.streams[0].closed); v.term.data?.('should not write');

 console.log('Terminal UI: explicit session lifecycle, ordered UTF-8/binary input, paste/copy fallbacks, SIGINT, safe SSE output, resize and cleanup passed.');
})().catch(error => { terminal.dispose(); console.error(error); process.exitCode = 1; });
