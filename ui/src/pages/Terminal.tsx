import { useEffect, useRef, useState } from 'react';
import { RotateCw } from 'lucide-react';
import { post } from '../api';
import { message } from '../lib';
import { Button, Notice } from '../ui';
import { RootAccess } from './RootAccess';

// The terminal renderer is the locally vendored xterm build that the previous
// interface ships; it is loaded on demand and never bundled into the app.
type Xterm = {
  cols: number; rows: number;
  open(element: HTMLElement): void; write(data: Uint8Array | string): void; focus(): void; dispose(): void;
  loadAddon(addon: unknown): void;
  onData(handler: (data: string) => void): void;
  onResize(handler: (size: { cols: number; rows: number }) => void): void;
};
type XtermGlobals = { Terminal?: new (options: Record<string, unknown>) => Xterm; FitAddon?: { FitAddon: new () => { fit(): void } } };

let assets: Promise<void> | null = null;
function loadAssets() {
  assets ??= new Promise<void>((resolve, reject) => {
    const style = document.createElement('link');
    style.rel = 'stylesheet';
    style.href = '/vendor/terminal/xterm.css';
    document.head.append(style);
    const load = (source: string) =>
      new Promise<void>((done, failed) => {
        const script = document.createElement('script');
        script.src = source;
        script.onload = () => done();
        script.onerror = () => failed(new Error('Terminal-Dateien konnten nicht geladen werden.'));
        document.head.append(script);
      });
    load('/vendor/terminal/xterm.js').then(() => load('/vendor/terminal/addon-fit.js')).then(resolve, reject);
  });
  return assets;
}

const encode = (text: string) => {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return btoa(binary);
};
const decode = (data: string) => Uint8Array.from(atob(data), char => char.charCodeAt(0));

export function TerminalSection() {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const [ended, setEnded] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [root, setRoot] = useState(false);

  useEffect(() => {
    setError(''); setEnded('');
    const endpoint = root ? '/api/root-terminal' : '/api/terminal';
    let disposed = false;
    let session = '';
    let stream: EventSource | null = null;
    let terminal: Xterm | null = null;
    let observer: ResizeObserver | null = null;
    // Keystrokes are sent in order; a failed write ends the session visibly.
    let queue = Promise.resolve();
    const send = (body: Record<string, unknown>) => {
      queue = queue.then(() => post(endpoint, body)).then(() => undefined, reason => { if (!disposed) setEnded(message(reason)); });
    };

    (async () => {
      try {
        await loadAssets();
        const globals = window as unknown as XtermGlobals;
        if (disposed || !host.current || !globals.Terminal) return;
        terminal = new globals.Terminal({ cursorBlink: true, fontSize: 13, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', theme: { background: '#0a0e19', foreground: '#e6e9f2' } });
        const fit = globals.FitAddon ? new globals.FitAddon.FitAddon() : null;
        if (fit) terminal.loadAddon(fit);
        terminal.open(host.current);
        fit?.fit();
        const created = await post<{ id: string }>(endpoint, { action: 'create', cols: terminal.cols, rows: terminal.rows });
        session = created.id;
        if (disposed) return void post(endpoint, { action: 'close', id: session }).catch(() => undefined);
        stream = new EventSource(`${endpoint}/output?id=${session}`);
        stream.addEventListener('output', event => terminal?.write(decode(JSON.parse((event as MessageEvent).data).data)));
        stream.addEventListener('exit', event => {
          const result = JSON.parse((event as MessageEvent).data) as { error?: string };
          stream?.close();
          if (!disposed) setEnded(result.error || 'Die Sitzung wurde beendet.');
        });
        terminal.onData(data => send({ action: 'write', id: session, data: encode(data) }));
        terminal.onResize(size => send({ action: 'resize', id: session, cols: size.cols, rows: size.rows }));
        observer = new ResizeObserver(() => fit?.fit());
        observer.observe(host.current);
        terminal.focus();
      } catch (reason) {
        if (!disposed) setError(message(reason));
      }
    })();

    return () => {
      disposed = true;
      observer?.disconnect();
      stream?.close();
      terminal?.dispose();
      if (session) post(endpoint, { action: 'close', id: session }).catch(() => undefined);
    };
  }, [attempt, root]);

  const restart = () => {
    setError('');
    setEnded('');
    setAttempt(value => value + 1);
  };

  return (
    <div className="space-y-3">
      <RootAccess onChange={setRoot} />
      {error && <Notice>{error}</Notice>}
      {ended && <Notice tone="info">{ended}</Notice>}
      <div key={`${attempt}-${root}`} ref={host} aria-label="Terminal" className="h-[58dvh] min-h-72 overflow-hidden rounded-2xl border border-white/10 bg-[#0a0e19] p-3" />
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={restart}>
          <RotateCw className="size-4" /> Neue Sitzung
        </Button>
        <span className="text-xs text-white/45">{root ? 'Root-Terminal · endet mit dem Root-Modus.' : 'Das Terminal läuft ohne Root-Rechte im Datenbereich des NAS.'}</span>
      </div>
    </div>
  );
}
