/* Titan session UI. Guacamole is an independently licensed upstream component. */
(() => {
  const query = new URLSearchParams(location.search);
  const kind = query.get('kind'), target = query.get('target');
  const screen = document.querySelector('#screen'), status = document.querySelector('#status');
  const notice = document.querySelector('#notice'), text = document.querySelector('#clipboard-text');
  const retry = document.querySelector('#retry');
  let client = null, id = null, csrf = '', closed = false, busy = false, timer = null, attempts = 0;
  const keyboard = new Guacamole.Keyboard(screen);
  const show = value => { notice.textContent = value; notice.hidden = !value; };
  async function post(path, body) {
    const response = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Sitzungsdienst nicht erreichbar.');
    return result;
  }
  function fit() {
    if (!client) return;
    const display = client.getDisplay(), width = display.getWidth(), height = display.getHeight();
    if (width && height && screen.clientWidth && screen.clientHeight)
      display.scale(Math.min(screen.clientWidth / width, screen.clientHeight / height));
  }
  function disconnect() {
    const previous = client; client = null;
    keyboard.reset(); keyboard.onkeydown = keyboard.onkeyup = null;
    previous?.disconnect(); screen.replaceChildren();
  }
  async function connect() {
    if (busy || closed) return;
    busy = true; retry.disabled = true; clearTimeout(timer); disconnect(); show('');
    status.textContent = 'Verbindung wird hergestellt …';
    try {
      const login = await fetch('/api/session', {cache:'no-store'}).then(response => response.json());
      if (!login.user) throw new Error('Bitte erneut in Titan anmelden.');
      csrf = login.user.csrf;
      const session = await post('/api/desktops', {kind, target,
        width: Math.max(640, Math.min(2560, screen.clientWidth)), height: Math.max(480, Math.min(1600, screen.clientHeight))});
      if (closed) return;
      id = session.id;
      const tunnel = new Guacamole.WebSocketTunnel(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/desktops/stream`);
      const active = new Guacamole.Client(tunnel); client = active;
      const display = active.getDisplay(); screen.append(display.getElement()); display.onresize = fit;
      const mouse = new Guacamole.Mouse(display.getElement());
      mouse.onEach(['mousedown','mousemove','mouseup'], event => { if (client === active) { screen.focus(); active.sendMouseState(event.state, true); } });
      const touch = new Guacamole.Mouse.Touchscreen(display.getElement());
      touch.onEach(['mousedown','mousemove','mouseup'], event => { if (client === active) active.sendMouseState(event.state, true); });
      keyboard.onkeydown = keysym => { active.sendKeyEvent(1, keysym); return false; };
      keyboard.onkeyup = keysym => active.sendKeyEvent(0, keysym);
      active.onclipboard = (stream, mimetype) => {
        if (mimetype !== 'text/plain') { stream.sendAck('Nur Text', 0x030F); return; }
        const reader = new Guacamole.StringReader(stream); let value = '';
        reader.ontext = chunk => { value = (value + chunk).slice(0, 65536); stream.sendAck('OK', 0); };
        reader.onend = () => { text.value = value; };
        stream.sendAck('OK', 0);
      };
      active.onerror = () => { if (client === active) { show('Die Verbindung wurde unterbrochen. Erneut verbinden oder die Sitzung beenden und neu öffnen.'); active.disconnect(); } };
      // Guacamole.Client handles protocol instructions; the application must
      // also propagate closure/errors of the underlying transport.
      tunnel.onerror = active.onerror;
      tunnel.onstatechange = state => { if (state === Guacamole.Tunnel.State.CLOSED && client === active) active.disconnect(); };
      active.onstatechange = state => {
        if (client !== active || closed) return;
        if (state === 3) { status.textContent = 'Verbunden'; attempts = 0; show(''); fit(); screen.focus(); }
        if (state === 5) {
          status.textContent = 'Verbindung getrennt';
          screen.replaceChildren();
          if (attempts++ < 4) timer = setTimeout(connect, Math.min(15000, 1500 * 2 ** attempts));
        }
      };
      active.connect('id=' + encodeURIComponent(id));
    } catch (error) { status.textContent = 'Sitzung nicht bereit'; show(error.message); }
    finally { busy = false; retry.disabled = false; }
  }
  screen.addEventListener('blur', () => keyboard?.reset());
  const observer = new ResizeObserver(fit); observer.observe(screen);
  retry.addEventListener('click', () => { attempts = 0; connect(); });
  document.querySelector('#fullscreen').addEventListener('click', () => document.documentElement.requestFullscreen?.());
  document.querySelector('#clipboard-toggle').addEventListener('click', () => { const panel = document.querySelector('#clipboard'); panel.hidden = !panel.hidden; });
  document.querySelector('#clipboard-send').addEventListener('click', () => {
    if (!client) return;
    const writer = new Guacamole.StringWriter(client.createClipboardStream('text/plain'));
    writer.sendText(text.value); writer.sendEnd(); screen.focus();
  });
  document.querySelector('#clipboard-copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(text.value); } catch { text.focus(); text.select(); show('Text markieren und mit Strg+C kopieren.'); }
  });
  const filesPanel = document.querySelector('#files'), fileStatus = document.querySelector('#files-status');
  const upload = document.querySelector('#upload');
  let transferring = false;
  document.querySelector('#files-toggle').hidden = kind !== 'app';
  document.querySelector('#files-toggle').addEventListener('click', () => { filesPanel.hidden = !filesPanel.hidden; });
  async function transfer(value) {
    if (!id) throw new Error('Zuerst eine Sitzung öffnen.');
    return post('/api/desktops/files', {id, transfer:value});
  }
  upload.addEventListener('change', async () => {
    const file = upload.files?.[0];
    if (!file || transferring) return;
    if (file.size > 256 * 1024 * 1024) { fileStatus.textContent = 'Maximal 256 MB pro Datei.'; return; }
    transferring = true; upload.disabled = true;
    try {
      // Unique names avoid overwriting a download or an earlier upload.
      const name = Date.now() + '-' + file.name.replace(/[\\/\x00-\x1f]/g, '_').slice(0, 170);
      let offset = 0;
      do {
        const bytes = new Uint8Array(await file.slice(offset, offset + 256 * 1024).arrayBuffer());
        let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
        const result = await transfer({action:'write', name, offset, data:btoa(binary)});
        offset = result.offset; fileStatus.textContent = `${Math.round(offset / Math.max(1, file.size) * 100)} % übertragen`;
      } while (offset < file.size);
      fileStatus.textContent = `Im Downloads-Ordner der Sitzung: ${name}`;
    } catch (error) { fileStatus.textContent = error.message; }
    finally { transferring = false; upload.disabled = false; upload.value = ''; }
  });
  document.querySelector('#files-refresh').addEventListener('click', async () => {
    if (transferring) return;
    try {
      const result = await transfer({action:'list'}), list = document.querySelector('#downloads');
      list.replaceChildren();
      for (const file of result.files) {
        const button = document.createElement('button'); button.textContent = file.name;
        button.addEventListener('click', async () => {
          if (transferring) return;
          transferring = true; button.disabled = true;
          try {
            const chunks = []; let offset = 0, total;
            do {
              const part = await transfer({action:'read', name:file.name, offset});
              if (total !== undefined && total !== part.total) throw new Error('Datei hat sich verändert. Erneut herunterladen.');
              total = part.total;
              const bytes = Uint8Array.from(atob(part.data), char => char.charCodeAt(0));
              if (!bytes.length && offset < total) throw new Error('Datei konnte nicht vollständig gelesen werden.');
              chunks.push(bytes); offset += bytes.length;
            } while (offset < total);
            const url = URL.createObjectURL(new Blob(chunks, {type:'application/octet-stream'}));
            const link = document.createElement('a'); link.href = url; link.download = file.name; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 60000);
          } catch (error) { fileStatus.textContent = error.message; }
          finally { transferring = false; button.disabled = false; }
        });
        list.append(button);
      }
      if (!result.files.length) fileStatus.textContent = 'Noch keine Dateien im Downloads-Ordner.';
    } catch (error) { fileStatus.textContent = error.message; }
  });
  document.querySelector('#end').addEventListener('click', async () => {
    clearTimeout(timer); disconnect();
    try { if (id) await post('/api/desktops/close', {id}); id = null; status.textContent = 'Sitzung beendet'; show('Mit „Neu verbinden“ eine neue Sitzung starten.'); }
    catch (error) { show(error.message); }
  });
  window.addEventListener('pagehide', () => { closed = true; clearTimeout(timer); observer.disconnect(); disconnect(); });
  connect();
})();
