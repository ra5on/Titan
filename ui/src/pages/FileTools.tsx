import { useEffect, useState } from 'react';
import { post } from '../api';
import type { FileEntry, FileListing, Share } from '../api';
import { bytes, dateTime, message } from '../lib';
import { Button, Field, Input, Loading, Modal, Notice, Select } from '../ui';

export type FileTool = { kind: 'create' | 'edit' | 'copy' | 'move' | 'details' | 'trash' | 'delete' | 'office'; entry?: FileEntry };
const join = (...parts: string[]) => parts.filter(Boolean).join('/');
const textBase64 = (text: string) => {
  const bytes = new TextEncoder().encode(text);
  if (bytes.length > 1048576) throw new Error('Der Texteditor unterstützt bis zu 1 MiB.');
  let binary = ''; for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
};

export function FileTools({ tool, share, path, shares, onClose, onDone }: { tool: FileTool; share: string; path: string; shares: Share[]; onClose: () => void; onDone: () => Promise<void> }) {
  const titles = { create: 'Neue Datei', edit: 'Text bearbeiten', copy: 'Kopieren', move: 'Verschieben', details: 'Dateidetails', trash: 'Papierkorb', delete: 'Dauerhaft löschen', office: 'Dokument bearbeiten' };
  const [name, setName] = useState(tool.entry?.name || '');
  const [content, setContent] = useState('');
  const [revision, setRevision] = useState('');
  const [crlf, setCrlf] = useState(false);
  const [type, setType] = useState('text');
  const [destinationShare, setDestinationShare] = useState(share);
  const [destination, setDestination] = useState('');
  const [trash, setTrash] = useState<FileListing | null>(null);
  const [restore, setRestore] = useState('');
  const [offset, setOffset] = useState(0);
  const [office, setOffice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(['edit', 'trash', 'office'].includes(tool.kind));
  const [error, setError] = useState('');
  const source = join(path, tool.entry?.name || '');
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (tool.kind === 'edit') {
          const file = await post<{ data: string; revision: string; total: number }>('/api/files', { share, path: source, action: 'read', size: 1048577 });
          if (!alive) return;
          if (file.total > 1048576) throw new Error('Der Texteditor unterstützt bis zu 1 MiB.');
          const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(Uint8Array.from(atob(file.data), value => value.charCodeAt(0)));
          if (text.includes('\0')) throw new Error('Binärdateien können nicht im Texteditor bearbeitet werden.');
          setContent(text); setRevision(file.revision); setCrlf(text.includes('\r\n') && !/(^|[^\r])\n/.test(text));
        } else if (tool.kind === 'trash') {
          const result = await post<FileListing>('/api/files', { share, action: 'trash_list', offset, limit: 200 });
          if (alive) setTrash(result);
        } else if (tool.kind === 'office') {
          const result = await post<{ url: string }>('/api/office/session', { share, path: source });
          if (alive) setOffice(result.url);
        }
      } catch (reason) { if (alive) setError(message(reason)); }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [share, source, tool.kind, offset]);
  const run = async () => {
    setBusy(true); setError('');
    try {
      const args: Record<string, unknown> = { share, path: source, action: tool.kind };
      if (tool.kind === 'create' || tool.kind === 'trash') {
        if (!name || name.includes('/') || name === '.' || name === '..') throw new Error('Einen Dateinamen ohne Schrägstrich eingeben.');
      }
      if (tool.kind === 'create') {
        args.path = join(path, name);
        if (type === 'text') args.data = textBase64(content);
        else { args.action = 'create_document'; args.document_type = type; }
      } else if (tool.kind === 'edit') {
        args.action = 'write'; args.revision = revision;
        args.data = textBase64(crlf ? content.replace(/\r?\n/g, '\r\n') : content);
      } else if (tool.kind === 'copy' || tool.kind === 'move') {
        args.destination_share = destinationShare; args.destination = join(destination, tool.entry!.name);
      } else if (tool.kind === 'trash') {
        args.action = 'restore'; delete args.path; args.trash_name = restore; args.destination = join(path, name);
      } else if (tool.kind === 'delete') {
        args.confirmation_path = share === '@system' ? '/' + source : join(share, source);
      }
      await post('/api/files', args); await onDone(); onClose();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  return <Modal title={titles[tool.kind]} wide={['edit', 'office'].includes(tool.kind)} onClose={() => { if (!busy) onClose(); }}>
    {loading ? <Loading /> : <form className="space-y-4" onSubmit={event => { event.preventDefault(); void run(); }}>
      {tool.entry && <p className="break-all text-sm text-white/65">{share}/{source}</p>}
      {tool.kind === 'details' && <dl className="grid grid-cols-2 gap-3 text-sm"><dt>Typ</dt><dd>{tool.entry?.symlink ? 'Symbolischer Link' : tool.entry?.directory ? 'Ordner' : 'Datei'}</dd><dt>Größe</dt><dd>{bytes(tool.entry?.size || 0)}</dd><dt>Geändert</dt><dd>{dateTime(tool.entry?.modified || 0)}</dd></dl>}
      {tool.kind === 'office' && office && <iframe src={office} title="Dokumenteditor" className="h-[65dvh] w-full rounded-xl bg-white" />}
      {tool.kind === 'create' && <><Field label="Dateiname"><Input value={name} onChange={event => setName(event.target.value)} required /></Field><Field label="Dateityp"><Select value={type} onChange={event => setType(event.target.value)}><option value="text">Textdatei</option>{['docx', 'xlsx', 'odt', 'ods'].map(value => <option key={value} value={value}>{value.toUpperCase()} · Dateiname mit .{value}</option>)}</Select></Field></>}
      {(tool.kind === 'edit' || tool.kind === 'create' && type === 'text') && <Field label="Dateiinhalt" help="UTF-8 · bis 1 MiB. Gleichzeitige Änderungen werden vor dem Speichern geprüft."><textarea className="h-72 w-full rounded-xl border border-white/15 bg-black/25 p-3 font-mono text-sm" value={content} onChange={event => setContent(event.target.value)} spellCheck={false} /></Field>}
      {['copy', 'move'].includes(tool.kind) && <><Field label="Zielfreigabe"><Select value={destinationShare} onChange={event => { setDestinationShare(event.target.value); setDestination(''); }}>{share === '@system' && <option value="@system">Systemspeicher</option>}{shares.map(item => <option key={item.name} value={item.name}>{item.label || item.name}</option>)}</Select></Field><Field label="Zielordner" help="Pfad relativ zur Zielfreigabe; leer bedeutet Hauptordner. Vorhandene Dateien werden nicht überschrieben."><Input value={destination} onChange={event => setDestination(event.target.value)} placeholder="z. B. Archiv/2026" /></Field></>}
      {tool.kind === 'trash' && <><p className="text-sm text-white/65">Wiederherstellen im aktuell geöffneten Ordner: {share}/{path}</p>{!trash?.entries.length ? <p>Der Papierkorb ist leer.</p> : <Field label="Eintrag wiederherstellen"><Select value={restore} onChange={event => { setRestore(event.target.value); setName(event.target.value.replace(/^\d+-/, '')); }}><option value="">Eintrag auswählen</option>{trash.entries.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</Select></Field>}{restore && <Field label="Dateiname"><Input required value={name} onChange={event => setName(event.target.value)} /></Field>}<div className="flex gap-2">{offset > 0 && <Button onClick={() => setOffset(offset - 200)}>Zurück</Button>}{trash?.has_more && <Button onClick={() => setOffset(offset + 200)}>Weitere Einträge</Button>}</div></>}
      {tool.kind === 'delete' && <Notice tone="warn">Dieser Eintrag und sein Ordnerinhalt werden dauerhaft gelöscht. Die Aktion lässt sich nicht rückgängig machen.</Notice>}
      {error && <Notice>{error}</Notice>}
      <div className="flex justify-end gap-2"><Button disabled={busy} onClick={onClose}>Schließen</Button>{!['details', 'office'].includes(tool.kind) && <Button type="submit" variant={tool.kind === 'delete' ? 'danger' : 'primary'} busy={busy} disabled={tool.kind === 'edit' && !revision || tool.kind === 'trash' && !restore}>{tool.kind === 'trash' ? 'Wiederherstellen' : tool.kind === 'copy' ? 'Kopieren' : tool.kind === 'move' ? 'Verschieben' : tool.kind === 'delete' ? 'Endgültig löschen' : 'Speichern'}</Button>}</div>
    </form>}
    {loading && error && <Notice>{error}</Notice>}
  </Modal>;
}
