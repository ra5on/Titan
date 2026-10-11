import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ChevronRight, Download, ArrowUpFromLine, Copy, Info, File as FileIcon, Folder, FolderPlus, HardDrive, Pencil, Trash2, Upload, Usb, X } from 'lucide-react';
import { action, get, post, uploadFile } from '../api';
import type { FileEntry, FileListing, Share } from '../api';
import { bytes, cx, dateTime, message, useApi } from '../lib';
import { Button, Confirm, Empty, Field, IconButton, Input, Loading, Menu, Meter, Modal, Notice, Sheet, useToast } from '../ui';
import { FileTools } from './FileTools';
import type { FileTool } from './FileTools';
import { RootAccess } from './RootAccess';

const PAGE = 200;
const join = (...parts: string[]) => parts.filter(Boolean).join('/');

function NameDialog({ title, label, initial, confirmLabel, onSubmit, onClose }: { title: string; label: string; initial: string; confirmLabel: string; onSubmit: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = name.trim();
    if (!value || value.includes('/')) return setError('Einen Namen ohne Schrägstrich eingeben.');
    setBusy(true);
    try {
      await onSubmit(value);
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={label}>
          <Input value={name} onChange={event => setName(event.target.value)} required />
        </Field>
        {error && <Notice>{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" busy={busy}>{confirmLabel}</Button>
        </div>
      </form>
    </Modal>
  );
}

type UploadState = { name: string; index: number; count: number; fraction: number };

export function Files({ initialShare = '', admin = false }: { initialShare?: string; admin?: boolean }) {
  const toast = useToast();
  const shares = useApi<Share[]>('/api/shares');
  const locations = useApi<{ resources: { id: string; label: string; path: string; available: boolean }[] }>(admin ? '/api/storage-locations' : null);
  const [root, setRoot] = useState(false);
  const [tool, setTool] = useState<FileTool | null>(null);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [share, setShare] = useState(initialShare);
  const [path, setPath] = useState('');
  const [listing, setListing] = useState<FileListing | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState<{ kind: 'mkdir' } | { kind: 'rename' | 'trash'; entry: FileEntry } | null>(null);
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [dragging, setDragging] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const request = useRef(0);

  useEffect(() => {
    if (!share && shares.data?.length) setShare(shares.data[0].name);
  }, [share, shares.data]);

  const load = useCallback(
    async (offset = 0) => {
      if (!share) return;
      const id = ++request.current;
      setLoading(true);
      try {
        const query = new URLSearchParams({ share, path, search, offset: String(offset), limit: String(PAGE) });
        const value = await get<FileListing>(`/api/files?${query}`);
        if (id !== request.current) return;
        setListing(value);
        setEntries(current => (offset ? [...current, ...value.entries] : value.entries));
        setError('');
      } catch (reason) {
        if (id === request.current) setError(message(reason));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [share, path, search, root],
  );

  useEffect(() => {
    setEntries([]);
    setListing(null);
    void load(0);
  }, [load]);

  const mutate = async (body: Record<string, unknown>, done: string) => {
    await post('/api/files', { share, ...body });
    toast(done);
    await load(0);
  };

  const startUpload = async (files: File[]) => {
    if (!files.length || upload) return;
    // Capture the destination now; navigating away must not redirect a running upload.
    const target = { share, path };
    const controller = new AbortController();
    abort.current = controller;
    let completed = 0;
    try {
      for (const [index, file] of files.entries()) {
        setUpload({ name: file.name, index: index + 1, count: files.length, fraction: 0 });
        await uploadFile(target.share, join(target.path, file.name), file, fraction => setUpload(current => current && { ...current, fraction }), controller.signal);
        completed++;
      }
      toast(completed === 1 ? `${files[0].name} hochgeladen.` : `${completed} Dateien hochgeladen.`);
    } catch (reason) {
      const text = controller.signal.aborted ? 'Upload abgebrochen.' : message(reason);
      toast(completed ? `${text} ${completed} von ${files.length} Dateien wurden übertragen.` : text, true);
    } finally {
      abort.current = null;
      setUpload(null);
      await load(0);
    }
  };

  const current = shares.data?.find(item => item.name === share);
  const title = (item: Share) => item.label || (item.external ? 'USB-Laufwerk' : item.name);

  const eject = async (item: Share) => {
    try {
      const result = await action('external_drive_eject', { name: item.name });
      toast(String(result.message || 'Das Laufwerk kann jetzt abgezogen werden.'));
      if (item.name === share) {
        setShare('');
        setPath('');
      }
      await shares.reload();
    } catch (reason) {
      toast(message(reason), true);
    }
  };

  const segments = path ? path.split('/') : [];
  const downloadUrl = (entry: FileEntry) => `/api/file?${new URLSearchParams({ share, path: join(path, entry.name) })}`;

  return (
    <Sheet
      title="Dateien"
      subtitle={current ? (current.external ? `USB-Laufwerk „${title(current)}“` : `Freigabe „${share}“`) : undefined}
      actions={
        share && (
          <>
            <Button size="sm" onClick={() => setTool({ kind: 'create' })}>Neue Datei</Button>
            {share !== '@system' && <Button size="sm" onClick={() => setTool({ kind: 'trash' })}>Papierkorb</Button>}
            <Button size="sm" onClick={() => setDialog({ kind: 'mkdir' })}>
              <FolderPlus className="size-4" /> Neuer Ordner
            </Button>
            <Button size="sm" variant="primary" onClick={() => picker.current?.click()} disabled={Boolean(upload)}>
              <Upload className="size-4" /> Hochladen
            </Button>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              onChange={event => {
                const files = Array.from(event.target.files || []);
                event.target.value = '';
                void startUpload(files);
              }}
            />
          </>
        )
      }
    >
      {admin && <RootAccess onChange={setRoot} />}
      {shares.loading ? (
        <Loading />
      ) : shares.error ? (
        <Notice>{shares.error}</Notice>
      ) : !shares.data?.length && !admin ? (
        <Empty title="Noch keine Freigabe">Lege in den Einstellungen unter „Speicher“ eine Freigabe an, um Dateien abzulegen.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-[13rem_minmax(0,1fr)]">
          <aside className="min-w-0">
            <div className="mb-2 px-2 text-xs font-medium uppercase tracking-wider text-white/40">Freigaben</div>
            <ul className="flex gap-1 overflow-x-auto md:block md:space-y-1">
              {(shares.data || []).map(item => (
                <li key={item.name} className="flex items-center gap-1">
                  <button
                    type="button"
                    aria-current={item.name === share}
                    onClick={() => {
                      setShare(item.name);
                      setPath('');
                    }}
                    className={cx('flex w-full items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-left text-sm transition-colors', item.name === share ? 'bg-white/14 font-medium text-white' : 'text-white/65 hover:bg-white/8')}
                  >
                    {item.external ? <Usb className="size-4 shrink-0" aria-hidden /> : <HardDrive className="size-4 shrink-0" aria-hidden />}
                    <span className="truncate">{title(item)}</span>
                  </button>
                  {item.external && (
                    <IconButton label={`${title(item)} auswerfen`} className="size-8 shrink-0" onClick={() => eject(item)}>
                      <ArrowUpFromLine className="size-4" />
                    </IconButton>
                  )}
                </li>
              ))}
            </ul>
            {admin && <div className="mt-5 space-y-1"><p className="px-2 text-xs uppercase text-white/40">Speicherbereiche</p>{(locations.data?.resources || []).map(item => <Button key={item.id} size="sm" variant="ghost" disabled={!item.available} onClick={() => { setShare('@system'); setPath(item.path.replace(/^\//, '')); }}>{item.label}</Button>)}{root && <Button size="sm" onClick={() => { setShare('@system'); setPath(''); }}>Systemdateien /</Button>}</div>}
          </aside>

          <div
            className={cx('min-w-0 rounded-2xl transition-shadow', dragging && 'ring-2 ring-brand')}
            onDragOver={event => {
              if (!event.dataTransfer.types.includes('Files')) return;
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={event => {
              event.preventDefault();
              setDragging(false);
              const items = Array.from(event.dataTransfer.items || []);
              if (items.some(item => item.webkitGetAsEntry?.()?.isDirectory)) return toast('Ordner können nicht per Drag-and-drop hochgeladen werden.', true);
              void startUpload(Array.from(event.dataTransfer.files));
            }}
          >
            <form className="mb-3 flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(searchInput); }}><Input aria-label="Dateien suchen" placeholder="In diesem Ordner suchen" value={searchInput} onChange={event => setSearchInput(event.target.value)} /><Button type="submit" size="sm">Suchen</Button></form>
            <nav aria-label="Pfad" className="mb-3 flex flex-wrap items-center gap-1 text-sm">
              <button type="button" onClick={() => setPath('')} className="rounded-lg px-2 py-1 text-white/70 hover:bg-white/10 hover:text-white">
                {current ? title(current) : share}
              </button>
              {segments.map((segment, index) => (
                <span key={index} className="flex items-center gap-1">
                  <ChevronRight className="size-3.5 text-white/30" aria-hidden />
                  <button type="button" onClick={() => setPath(segments.slice(0, index + 1).join('/'))} className={cx('rounded-lg px-2 py-1 hover:bg-white/10', index === segments.length - 1 ? 'font-medium text-white' : 'text-white/70')}>
                    {segment}
                  </button>
                </span>
              ))}
            </nav>

            {upload && (
              <div className="glass-soft mb-3 flex items-center gap-3 rounded-xl px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1.5 flex justify-between gap-3 text-xs text-white/70">
                    <span className="truncate">{upload.name}</span>
                    <span className="shrink-0 tabular-nums">
                      {upload.count > 1 && `${upload.index}/${upload.count} · `}
                      {Math.round(upload.fraction * 100)} %
                    </span>
                  </div>
                  <Meter value={upload.fraction * 100} tone="ok" />
                </div>
                <IconButton label="Upload abbrechen" onClick={() => abort.current?.abort()}>
                  <X className="size-4" />
                </IconButton>
              </div>
            )}

            {error ? (
              <Notice>{error}</Notice>
            ) : loading && !entries.length ? (
              <Loading />
            ) : !entries.length ? (
              <Empty title="Dieser Ordner ist leer">Dateien hierher ziehen oder über „Hochladen“ auswählen.</Empty>
            ) : (
              <>
                <ul className="divide-y divide-white/6 rounded-2xl border border-white/8">
                  {entries.map(entry => (
                    <li key={entry.name} className="group flex items-center gap-3 px-3 py-2 hover:bg-white/6 sm:px-4">
                      {entry.directory ? <Folder className="size-5 shrink-0 text-amber-300" aria-hidden /> : <FileIcon className="size-5 shrink-0 text-white/45" aria-hidden />}
                      {entry.directory ? (
                        <button type="button" onClick={() => setPath(join(path, entry.name))} className="min-w-0 flex-1 truncate text-left text-sm font-medium hover:underline">
                          {entry.name}
                        </button>
                      ) : (
                        <span className="min-w-0 flex-1 truncate text-sm">{entry.name}</span>
                      )}
                      <span className="hidden w-20 shrink-0 text-right text-xs tabular-nums text-white/45 sm:block">{entry.directory ? '' : bytes(entry.size)}</span>
                      <span className="hidden w-36 shrink-0 text-right text-xs text-white/45 lg:block">{dateTime(entry.modified)}</span>
                      <span className="flex shrink-0 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
                        {!entry.directory && (
                          <a href={downloadUrl(entry)} download={entry.name} aria-label={`${entry.name} herunterladen`} title="Herunterladen" className="inline-flex size-9 items-center justify-center rounded-full text-white/75 hover:bg-white/10 hover:text-white">
                            <Download className="size-4" />
                          </a>
                        )}
                        <IconButton label={`${entry.name} umbenennen`} onClick={() => setDialog({ kind: 'rename', entry })}>
                          <Pencil className="size-4" />
                        </IconButton>
                        {share !== '@system' && <IconButton label={`${entry.name} in den Papierkorb`} onClick={() => setDialog({ kind: 'trash', entry })}>
                          <Trash2 className="size-4" />
                        </IconButton>}
                        <Menu label={`Weitere Aktionen für ${entry.name}`} items={[
                          { label: 'Details', icon: Info, onClick: () => setTool({ kind: 'details', entry }) },
                          ...(!entry.directory && !entry.symlink ? [{ label: 'Text bearbeiten', icon: Pencil, onClick: () => setTool({ kind: 'edit', entry }) }, ...(/\.(docx|xlsx|odt|ods)$/i.test(entry.name) ? [{ label: 'Dokument bearbeiten', icon: FileIcon, onClick: () => setTool({ kind: 'office', entry }) }] : [])] : []),
                          ...(!entry.symlink ? [{ label: 'Kopieren', icon: Copy, onClick: () => setTool({ kind: 'copy', entry }) }, { label: 'Verschieben', icon: Folder, onClick: () => setTool({ kind: 'move', entry }) }] : []),
                          ...(admin ? [{ label: 'Dauerhaft löschen', icon: Trash2, danger: true, onClick: () => setTool({ kind: 'delete', entry }) }] : []),
                        ]} />
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="mt-3 flex items-center justify-between text-xs text-white/45">
                  <span>
                    {entries.length} von {listing?.total ?? entries.length} Einträgen
                  </span>
                  {listing?.has_more && (
                    <Button size="sm" busy={loading} onClick={() => load(entries.length)}>
                      Mehr laden
                    </Button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {dialog?.kind === 'mkdir' && (
        <NameDialog title="Neuer Ordner" label="Ordnername" initial="" confirmLabel="Anlegen" onClose={() => setDialog(null)} onSubmit={name => mutate({ action: 'mkdir', path: join(path, name) }, `Ordner „${name}“ angelegt.`)} />
      )}
      {tool && <FileTools key={`${share}/${path}/${tool.kind}/${tool.entry?.name}`} tool={tool} share={share} path={path} shares={shares.data || []} onClose={() => setTool(null)} onDone={() => load(0)} />}
      {dialog?.kind === 'rename' && (
        <NameDialog
          title="Umbenennen"
          label="Neuer Name"
          initial={dialog.entry.name}
          confirmLabel="Umbenennen"
          onClose={() => setDialog(null)}
          onSubmit={name => mutate({ action: 'rename', path: join(path, dialog.entry.name), destination: join(path, name) }, `In „${name}“ umbenannt.`)}
        />
      )}
      {dialog?.kind === 'trash' && (
        <Confirm
          title="In den Papierkorb verschieben?"
          text={<>„{dialog.entry.name}“ wird in den Papierkorb der Freigabe verschoben und kann dort wiederhergestellt werden.</>}
          confirmLabel="Verschieben"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            try {
              await mutate({ action: 'trash', path: join(path, dialog.entry.name) }, `„${dialog.entry.name}“ in den Papierkorb verschoben.`);
            } catch (reason) {
              toast(message(reason), true);
            }
          }}
        />
      )}
    </Sheet>
  );
}
