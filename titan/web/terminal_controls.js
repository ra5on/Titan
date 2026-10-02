'use strict';
// A terminal session belongs to the mounted page, never to a reconnecting SSE.
(function (root, factory) {
 const terminal = factory(root || globalThis);
 if (typeof module === 'object' && module.exports) module.exports = terminal;
 if (root) root.TitanTerminal = terminal;
})(typeof window === 'undefined' ? null : window, function (env) {
 const inputLimit = 64 * 1024, chunkLimit = 16 * 1024, outputLimit = 1024 * 1024;
 let current = null;
 const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
 const dimensions = (cols, rows) => ({cols:Math.max(20, Math.min(500, Math.floor(Number(cols) || 80))), rows:Math.max(5, Math.min(200, Math.floor(Number(rows) || 24)))});
 const utf8 = text => new (env.TextEncoder || globalThis.TextEncoder)().encode(text);
 function bytesToBase64(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return (env.btoa || globalThis.btoa)(binary);
 }
 function base64ToBytes(text) {
  if (typeof text !== 'string' || text.length > outputLimit * 4 / 3 + 8 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(text)) throw new Error('Ungültige Terminal-Ausgabe.');
  const binary = (env.atob || globalThis.atob)(text);
  return Uint8Array.from(binary, character => character.charCodeAt(0));
 }
 function binaryBytes(text) {
  if (typeof text !== 'string' || Array.from(text).some(character => character.charCodeAt(0) > 255)) throw new Error('Ungültige binäre Terminal-Eingabe.');
  return Uint8Array.from(text, character => character.charCodeAt(0));
 }
 function dispose() { current?.dispose(); current = null; }
 function mount(main, ctx) {
  dispose();
  if (!main || !ctx?.api) return null;
  const screen = main.querySelector('#terminal-screen'), stateNode = main.querySelector('#terminal-state');
  if (!screen || !stateNode) return null;
  const doc = main.ownerDocument, view = doc?.defaultView || env, esc = ctx.esc || escape;
  const notice = (text, error = false) => ctx.toast?.(text, error);
  const buttons = Array.from(main.querySelectorAll('[data-terminal-action]'));
  let term, fit, stream = null, id = null, generation = 0, destroyed = false, creating = false, phase = 'closed';
  let pendingBytes = 0, inputs = [], drainingToken = null, outputBytes = 0, outputs = [], writing = false, writingBytes = 0;
  let observer = null, resizeTimer = null, lastSize = null, resizeToken = null, wantedSize = null;
  const listeners = [], subscriptions = [];
  function listen(node, type, callback, options) {
   node?.addEventListener?.(type, callback, options);
   listeners.push(() => node?.removeEventListener?.(type, callback, options));
  }
  function update(message) {
   if (destroyed) return;
   if (message) stateNode.textContent = message;
   stateNode.dataset.state = phase;
   for (const button of buttons) {
    const action = button.dataset.terminalAction;
    button.disabled = action === 'open' ? creating || phase === 'connected' : action === 'close' ? !creating && !id : ['paste','interrupt'].includes(action) ? !id || phase !== 'connected' : false;
   }
   if (term?.options) term.options.disableStdin = phase !== 'connected';
  }
  function closeBackend(session, keepalive = false) {
   if (!session) return;
   const body = {action:'close', id:session};
   try {
    if (keepalive && typeof view.fetch === 'function') {
     const csrf = typeof ctx.csrf === 'function' ? ctx.csrf() : ctx.csrf;
     Promise.resolve(view.fetch('/api/terminal', {method:'POST', credentials:'same-origin', keepalive:true, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf || ''}, body:JSON.stringify(body)})).catch(() => {});
    } else Promise.resolve(ctx.api('/api/terminal', body)).catch(() => {});
   } catch (_) { /* The server also expires orphaned terminal sessions. */ }
  }
  function disconnect(message, error = false, keepalive = false) {
   const session = id;
   id = null; generation++; phase = error ? 'failed' : 'closed';
   stream?.close(); stream = null;
   inputs = []; pendingBytes = 0; wantedSize = null; lastSize = null;
   outputs = []; outputBytes = writingBytes;
   closeBackend(session, keepalive);
   update(message);
   if (error) notice(message, true);
  }
  function live(session, token) { return !destroyed && id === session && generation === token && phase === 'connected'; }
  async function drainInput() {
   const token = generation;
   if (drainingToken === token) return;
   drainingToken = token;
   try {
    while (inputs.length && generation === token && !destroyed) {
     const item = inputs.shift();
     if (!live(item.session, item.token)) continue;
     try {
      await ctx.api('/api/terminal', {action:'write', id:item.session, data:bytesToBase64(item.bytes)});
      if (live(item.session, item.token)) pendingBytes -= item.bytes.length;
     } catch (error) {
      if (live(item.session, item.token)) disconnect(error?.message || 'Terminal-Eingabe fehlgeschlagen. Bitte neu verbinden.', true);
     }
    }
   } finally { if (drainingToken === token) drainingToken = null; }
  }
  function send(bytes) {
   if (!id || destroyed || phase !== 'connected' || !bytes.length) return false;
   if (bytes.length > inputLimit - pendingBytes) {
    notice('Eingabe nicht gesendet: Es können höchstens 64 KiB warten. Bitte nach dem Übertragen erneut versuchen oder einen kleineren Abschnitt einfügen.', true);
    return false;
   }
   pendingBytes += bytes.length;
   for (let offset = 0; offset < bytes.length; offset += chunkLimit) inputs.push({session:id, token:generation, bytes:bytes.slice(offset, offset + chunkLimit)});
   void drainInput();
   return true;
  }
  function drainOutput() {
   if (writing || destroyed || !outputs.length) return;
   const item = outputs.shift();
   if (item.token !== generation) { outputBytes -= item.bytes.length; drainOutput(); return; }
   writing = true; writingBytes = item.bytes.length;
   term.write(item.bytes, () => {
    writing = false; writingBytes = 0; outputBytes = Math.max(0, outputBytes - item.bytes.length);
    // Avoid recursive synchronous writes with a fake/very fast parser, and let
    // the browser process navigation between queued terminal packets.
    if (!destroyed) Promise.resolve().then(drainOutput);
   });
  }
  function output(event, session, token) {
   if (!live(session, token)) return;
   try {
    const bytes = base64ToBytes(JSON.parse(event.data).data);
    if (!bytes.length) return;
    if (bytes.length + outputBytes > outputLimit || outputs.length >= 2048) throw new Error('Terminal-Ausgabe ist zu schnell. Bitte neu verbinden.');
    outputBytes += bytes.length; outputs.push({bytes, token}); drainOutput();
   } catch (error) { disconnect(error?.message || 'Terminal-Ausgabe konnte nicht gelesen werden.', true); }
  }
  function fitScreen() {
   if (destroyed) return dimensions(80, 24);
   try { fit?.fit(); } catch (_) { /* A hidden panel cannot be measured yet. */ }
   const size = dimensions(term.cols, term.rows);
   if (term.cols !== size.cols || term.rows !== size.rows) term.resize(size.cols, size.rows);
   return size;
  }
  async function resizeSession() {
   const resizeGeneration = generation;
   if (resizeToken === resizeGeneration) return;
   resizeToken = resizeGeneration;
   try {
    while (wantedSize && id && !destroyed && generation === resizeGeneration) {
     const session = id, token = generation, size = wantedSize;
     wantedSize = null;
     if (lastSize?.cols === size.cols && lastSize?.rows === size.rows) continue;
     try {
      await ctx.api('/api/terminal', {action:'resize', id:session, ...size});
      if (live(session, token)) lastSize = size;
     } catch (error) { if (live(session, token)) disconnect(error?.message || 'Terminal-Größe konnte nicht angepasst werden.', true); }
    }
   } finally { if (resizeToken === resizeGeneration) resizeToken = null; }
  }
  function scheduleResize() {
   if (destroyed) return;
   if (resizeTimer !== null) view.clearTimeout(resizeTimer);
   resizeTimer = view.setTimeout(() => {
    resizeTimer = null;
    const size = fitScreen();
    if (id && phase === 'connected') { wantedSize = size; void resizeSession(); }
   }, 100);
  }
  async function open() {
   if (destroyed || creating || id) return;
   const token = ++generation, size = fitScreen();
   creating = true; phase = 'connecting'; update('Terminal wird verbunden …');
   try {
    const result = await ctx.api('/api/terminal', {action:'create', ...size});
    if (typeof result?.id !== 'string' || !result.id || result.id.length > 256) throw new Error('Der Server lieferte keine gültige Terminal-Sitzung.');
    if (destroyed || token !== generation) { closeBackend(result.id); return; }
    id = result.id; lastSize = dimensions(result.cols, result.rows);
    term.resize(lastSize.cols, lastSize.rows); phase = 'connected';
    const EventStream = ctx.EventSource || view.EventSource;
    stream = new EventStream('/api/terminal/output?id=' + encodeURIComponent(id));
    const session = id;
    stream.addEventListener('output', event => output(event, session, token));
    stream.addEventListener('exit', event => {
     if (!live(session, token)) return;
     let result;
     try { result = JSON.parse(event.data); } catch (_) { result = {error:'Ungültige Abschlussmeldung.'}; }
     // Keep already received output in xterm's write queue, but stop all input.
     stream?.close(); stream = null; id = null; inputs = []; pendingBytes = 0; wantedSize = null;
     closeBackend(session); phase = 'ended';
     update(result.error ? 'Terminal beendet: ' + result.error : 'Terminal beendet' + (Number.isInteger(result.exit_code) ? ' · Exit ' + result.exit_code : '') + '.');
    });
    stream.onerror = () => { if (live(session, token)) disconnect('Terminal-Verbindung unterbrochen. Bitte bewusst neu verbinden.', true); };
    update('Terminal verbunden.'); term.focus(); scheduleResize();
   } catch (error) {
    if (!destroyed && token === generation) disconnect(error?.message || 'Terminal konnte nicht verbunden werden.', true);
   } finally { creating = false; update(); }
  }
  async function copy() {
   const text = term.getSelection();
   if (!text) { notice('Markiere zuerst den Text, den du kopieren möchtest.'); return; }
   try {
    const clipboard = (ctx.navigator || view.navigator)?.clipboard;
    if (!clipboard?.writeText) throw new Error('Zwischenablage nicht verfügbar.');
    await clipboard.writeText(text);
    if (!destroyed) notice('Markierten Text kopiert.');
   } catch (_) {
    if (destroyed) return;
    ctx.dialog?.('Terminal-Auswahl kopieren', '<p>Die Browser-Zwischenablage ist hier nicht verfügbar. Kopiere den markierten Text mit Strg+C oder dem Kopieren-Menü deines Geräts.</p><textarea class="terminal-clipboard" data-terminal-copy readonly aria-label="Markierter Terminal-Text">' + esc(text) + '</textarea>');
    const field = doc?.querySelector('[data-terminal-copy]'); field?.focus(); field?.select();
   }
  }
  function pasteText(text) {
   if (destroyed || !id || phase !== 'connected') throw new Error('Bitte zuerst das Terminal verbinden.');
   if (typeof text !== 'string') throw new Error('Nur Text kann eingefügt werden.');
   // Reserve xterm's bracketed-paste delimiters before emitting any input.
   if (text.length > inputLimit || utf8(text).length + 12 > inputLimit - pendingBytes) throw new Error('Text nicht eingefügt: Bitte höchstens 64 KiB in kleineren Abschnitten übertragen.');
   term.paste(text); term.focus();
  }
  async function paste() {
   const session = id, token = generation;
   if (!live(session, token)) { notice('Bitte zuerst das Terminal verbinden.'); return; }
   let text;
   try {
    const clipboard = (ctx.navigator || view.navigator)?.clipboard;
    if (!clipboard?.readText) throw new Error('Zwischenablage nicht verfügbar.');
    text = await clipboard.readText();
   } catch (_) {
    if (!live(session, token)) return;
    ctx.dialog?.('Text ins Terminal einfügen', '<p>Füge den Text hier mit Strg+V oder dem Einfügen-Menü deines Geräts ein.</p><form><label for="terminal-paste-text">Text</label><textarea id="terminal-paste-text" class="terminal-clipboard" name="text" aria-label="Text zum Einfügen" required></textarea><div class="form-actions"><button type="button" class="button" data-action="close">Abbrechen</button><button class="button primary" type="submit">Einfügen</button></div></form>', async form => {
     if (!live(session, token)) throw new Error('Die Terminal-Sitzung wurde inzwischen beendet.');
     pasteText(String(form.get('text') || ''));
    });
    doc?.querySelector('#terminal-paste-text')?.focus();
    return;
   }
   if (live(session, token)) { try { pasteText(text); } catch (error) { notice(error.message, true); } }
  }
  function key(event) {
   if (event.type !== 'keydown') return true;
   const control = event.ctrlKey || event.metaKey, letter = String(event.key || '').toLowerCase();
   if (control && !event.altKey && letter === 'c' && (event.shiftKey || term.hasSelection())) {
    event.preventDefault(); void copy(); return false;
   }
   if (control && !event.altKey && letter === 'v') {
    if (event.shiftKey) { event.preventDefault(); void paste(); }
    // Ctrl+V stays a native paste event, even on HTTP without Clipboard API.
    return false;
   }
   return true;
  }
  function nativePaste(event) {
   if (!id || phase !== 'connected') return;
   const text = event.clipboardData?.getData('text/plain');
   if (typeof text !== 'string') return;
   event.preventDefault(); event.stopImmediatePropagation?.();
   try { pasteText(text); } catch (error) { notice(error.message, true); }
  }
  const controller = {
   open, close:() => disconnect('Terminal geschlossen.'), copy, paste,
   interrupt:() => { if (send(utf8('\x03'))) term.focus(); }, clear:() => { term.clear(); term.focus(); },
   dispose(keepalive = false) {
    if (destroyed) return;
    disconnect('Terminal geschlossen.', false, keepalive); destroyed = true;
    if (resizeTimer !== null) view.clearTimeout(resizeTimer);
    observer?.disconnect(); listeners.splice(0).forEach(remove => remove());
    subscriptions.splice(0).forEach(subscription => subscription?.dispose());
    outputs = []; outputBytes = 0; term?.dispose();
    if (current === controller) current = null;
   }
  };
  try {
   const options = {cols:80, rows:24, cursorBlink:true, scrollback:5000, fontFamily:'ui-monospace, SFMono-Regular, Consolas, monospace', fontSize:14, disableStdin:true, allowProposedApi:false, theme:{background:'#101820', foreground:'#d9e5ea', cursor:'#83d1c4', selectionBackground:'#426a7780'}};
   term = ctx.terminalFactory ? ctx.terminalFactory(options) : new view.Terminal(options);
   fit = ctx.fitFactory ? ctx.fitFactory() : view.FitAddon?.FitAddon ? new view.FitAddon.FitAddon() : null;
   if (fit) term.loadAddon(fit);
   term.open(screen); term.attachCustomKeyEventHandler(key);
   subscriptions.push(term.onData(data => send(utf8(data))), term.onBinary(data => {
    try { send(binaryBytes(data)); } catch (error) { notice(error.message, true); }
   }));
   listen(main, 'click', event => {
    const button = event.target.closest?.('[data-terminal-action]');
    if (!button || !main.contains(button) || button.disabled) return;
    const action = controller[button.dataset.terminalAction];
    if (action) Promise.resolve(action()).catch(error => notice(error?.message || 'Terminal-Aktion fehlgeschlagen.', true));
   });
   listen(screen, 'paste', nativePaste, true);
   listen(view, 'pagehide', () => controller.dispose(true));
   if (view.ResizeObserver) { observer = new view.ResizeObserver(scheduleResize); observer.observe(screen); }
   else listen(view, 'resize', scheduleResize);
   current = controller; update('Terminal ist geschlossen. Mit Verbinden starten.'); fitScreen();
   return controller;
  } catch (error) {
   controller.dispose(); stateNode.textContent = 'Terminal-Oberfläche konnte nicht geladen werden.';
   notice(error?.message || 'Terminal-Oberfläche konnte nicht geladen werden.', true);
   return null;
  }
 }
 return {mount, dispose, dimensions, bytesToBase64, base64ToBytes, binaryBytes, inputLimit, chunkLimit};
});
