import { ManagementPanel } from '../management/Panel';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { HardDrive, Maximize2, Plus, Replace } from 'lucide-react';
import { action } from '../api';
import { bytes, cx, go, message, percent, useApi } from '../lib';
import { Button, Card, Confirm, Field, Input, Loading, Meter, Modal, Notice, Select, useToast } from '../ui';

type Disk = { name: string; size: number; model: string; type?: string; fstype: string | null; mountpoints?: (string | null)[]; children?: unknown[]; ro?: boolean };
type Volume = {
  name: string; filesystem: string; mounted: boolean; state: string; total: number; used: number; free: number; error?: string | null;
  disks?: string[]; mirror?: boolean; degraded?: boolean; errors?: number; replacing?: { disk: string; percent: number | null } | null;
};
type Storage = {
  pools: { name: string; size: number; used: number; free: number; health: string }[];
  disks: Disk[];
  volumes: Volume[];
  filesystems: Record<string, { available: boolean }>;
};
type SystemDisk = {
  supported: boolean; available: boolean; reason: string; revision: string; disk: string;
  filesystem_size: number; filesystem_used: number; disk_size: number; growable_bytes: number;
};
type Locations = {
  resources: { id: string; available: boolean; total_bytes: number; free_bytes: number; used_bytes?: number; error?: string }[];
  default_storage: string;
};

const FS_LABEL: Record<string, string> = { ext4: 'Ext4 · bewährter Standard', xfs: 'XFS · für sehr große Dateien', btrfs: 'Btrfs · mit Prüfsummen und Snapshots' };
const LAYOUTS: Record<string, { label: string; minimum: number }> = {
  mirror: { label: 'Spiegel · jede Platte hält alle Daten', minimum: 2 },
  raidz1: { label: 'RAID-Z1 · eine Platte darf ausfallen', minimum: 3 },
  raidz2: { label: 'RAID-Z2 · zwei Platten dürfen ausfallen', minimum: 4 },
};

const isBlank = (disk: Disk) => (!disk.type || disk.type === 'disk') && !disk.fstype && !(disk.children || []).length && !(disk.mountpoints || []).some(Boolean) && !disk.ro;

function Usage({ used, total, free }: { used: number; total: number; free?: number }) {
  return (
    <>
      <div className="mb-2 mt-4 flex justify-between text-sm">
        <span className="text-white/55">{bytes(used)} belegt</span>
        <span className="tabular-nums text-white/55">{bytes(free ?? total - used)} frei von {bytes(total)}</span>
      </div>
      <Meter value={percent(used, total)} />
    </>
  );
}

function CreateDialog({ storage, onClose, onDone }: { storage: Storage; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const blank = storage.disks.filter(isBlank);
  const filesystems = Object.entries(storage.filesystems).filter(([, value]) => value.available).map(([name]) => name);
  const [kind, setKind] = useState<'single' | 'pool'>('single');
  const [name, setName] = useState('');
  const [disk, setDisk] = useState(blank[0]?.name || '');
  const [filesystem, setFilesystem] = useState(filesystems[0] || 'ext4');
  const [mirror, setMirror] = useState('');
  const [layout, setLayout] = useState('mirror');
  const [members, setMembers] = useState<string[]>([]);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const partner = filesystem === 'btrfs' && mirror !== disk ? mirror : '';
  const chosen = kind === 'single' ? [disk, partner] : members;
  const expected = kind === 'single' ? disk : name;
  const enough = kind === 'single' ? Boolean(disk) : members.length >= LAYOUTS[layout].minimum;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (kind === 'single') await action('volume_create', { name, disk, filesystem, confirmation_name: name, confirmation_disk: typed, ...(partner ? { mirror: [partner] } : {}) });
      else await action('pool_create', { name, layout, disks: members, confirmation: typed });
      toast(`Speicherbereich „${name}“ angelegt.`);
      onDone();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Neuer Speicherbereich" onClose={onClose} wide>
      {blank.length === 0 ? (
        <Notice tone="info">Es ist kein leeres Laufwerk angeschlossen. Titan richtet nur vollständig leere, unpartitionierte Laufwerke ein und überschreibt keine vorhandenen Daten.</Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Art">
            <Select value={kind} onChange={event => { setKind(event.target.value as 'single' | 'pool'); setTyped(''); }}>
              <option value="single">Einzelnes Laufwerk oder Btrfs-Spiegel</option>
              {blank.length >= 2 && <option value="pool">ZFS-Verbund aus mehreren Laufwerken</option>}
            </Select>
          </Field>
          <Field label="Name" help="Kleinbuchstaben, Ziffern, - und _; beginnt mit einem Buchstaben.">
            <Input value={name} onChange={event => setName(event.target.value)} required pattern="[a-z][a-z0-9_\-]{0,30}" autoCapitalize="none" spellCheck={false} />
          </Field>
          {kind === 'single' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Laufwerk">
                <Select value={disk} onChange={event => { setDisk(event.target.value); setTyped(''); }}>
                  {blank.map(item => (
                    <option key={item.name} value={item.name}>{item.model || 'Laufwerk'} · {bytes(item.size)} · {item.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Dateisystem">
                <Select value={filesystem} onChange={event => setFilesystem(event.target.value)}>
                  {filesystems.map(item => (
                    <option key={item} value={item}>{FS_LABEL[item] || item}</option>
                  ))}
                </Select>
              </Field>
              {filesystem === 'btrfs' && <p className="text-xs text-white/50">Beta · Btrfs-Spiegel und Laufwerkstausch sind noch nicht umfassend auf physischer Hardware erprobt.</p>}
              {filesystem === 'btrfs' && blank.length >= 2 && (
                <Field label="Spiegeln auf" help="Mit einem zweiten Laufwerk liegt alles doppelt vor; eines darf ausfallen.">
                  <Select value={partner} onChange={event => setMirror(event.target.value)}>
                    <option value="">Nicht spiegeln</option>
                    {blank.filter(item => item.name !== disk).map(item => (
                      <option key={item.name} value={item.name}>{item.model || 'Laufwerk'} · {bytes(item.size)} · {item.name}</option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          ) : (
            <>
              <Field label="Schutz">
                <Select value={layout} onChange={event => setLayout(event.target.value)}>
                  {Object.entries(LAYOUTS).filter(([, value]) => blank.length >= value.minimum).map(([id, value]) => (
                    <option key={id} value={id}>{value.label}</option>
                  ))}
                </Select>
              </Field>
              <fieldset>
                <legend className="mb-1 text-[13px] font-medium text-white/70">Laufwerke (mindestens {LAYOUTS[layout].minimum})</legend>
                {blank.map(item => (
                  <label key={item.name} className="flex cursor-pointer items-center gap-3 py-1.5 text-sm">
                    <input type="checkbox" className="size-4 accent-[var(--color-brand)]" checked={members.includes(item.name)} onChange={event => setMembers(event.target.checked ? [...members, item.name] : members.filter(value => value !== item.name))} />
                    {item.model || 'Laufwerk'} · {bytes(item.size)} · {item.name}
                  </label>
                ))}
              </fieldset>
            </>
          )}
          <Notice tone="warn">
            {chosen.filter(Boolean).join(', ') || 'Das gewählte Laufwerk'} wird formatiert. Zur Bestätigung{' '}
            <span className="font-mono font-semibold">{expected || '…'}</span> eingeben.
          </Notice>
          <Field label="Bestätigung">
            <Input value={typed} onChange={event => setTyped(event.target.value)} autoCapitalize="none" spellCheck={false} autoComplete="off" required />
          </Field>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="danger" busy={busy} disabled={!enough || !name || typed !== expected}>Formatieren und anlegen</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function ReplaceDialog({ volume, storage, onClose, onDone }: { volume: Volume; storage: Storage; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const blank = storage.disks.filter(isBlank);
  const current = volume.disks || [];
  const [member, setMember] = useState(current[0] || '');
  const [disk, setDisk] = useState(blank[0]?.name || '');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await action('volume_replace', { name: volume.name, disk, confirmation_name: volume.name, confirmation_disk: typed, ...(volume.degraded ? {} : { member }) });
      toast('Der Austausch läuft. Die Daten bleiben währenddessen erreichbar.');
      onDone();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title={`Laufwerk in „${volume.name}“ ersetzen`} onClose={onClose}>
      {blank.length === 0 ? (
        <Notice tone="info">Schließe zuerst ein leeres Ersatzlaufwerk an. Es muss mindestens so groß sein wie das alte.</Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          {volume.degraded ? (
            <Notice tone="warn">Dem Verbund fehlt ein Laufwerk. Titan baut dessen Inhalt aus der verbliebenen Kopie auf dem Ersatzlaufwerk neu auf.</Notice>
          ) : (
            <Field label="Altes Laufwerk" help="Es bleibt bis zum Abschluss im Verbund und kann danach entfernt werden.">
              <Select value={member} onChange={event => setMember(event.target.value)}>
                {current.map(item => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Ersatzlaufwerk">
            <Select value={disk} onChange={event => { setDisk(event.target.value); setTyped(''); }}>
              {blank.map(item => (
                <option key={item.name} value={item.name}>{item.model || 'Laufwerk'} · {bytes(item.size)} · {item.name}</option>
              ))}
            </Select>
          </Field>
          <Notice tone="warn">
            {disk} wird überschrieben. Zur Bestätigung <span className="font-mono font-semibold">{disk || '…'}</span> eingeben.
          </Notice>
          <Field label="Bestätigung">
            <Input value={typed} onChange={event => setTyped(event.target.value)} autoCapitalize="none" spellCheck={false} autoComplete="off" required />
          </Field>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="danger" busy={busy} disabled={!disk || typed !== disk}>Ersetzen</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function StorageSection() {
  const toast = useToast();
  const storage = useApi<Storage>('/api/storage', 30000);
  const system = useApi<SystemDisk>('/api/system-disk', 60000);
  const locations = useApi<Locations>('/api/storage-locations', 30000);
  const [savingDefault, setSavingDefault] = useState(false);
  const [creating, setCreating] = useState(false);
  const [growing, setGrowing] = useState(false);
  const [replacing, setReplacing] = useState<Volume | null>(null);

  if (storage.loading) return <Loading />;
  if (storage.error && !storage.data) return <Notice>{storage.error}</Notice>;
  const data = storage.data!;
  const disk = system.data?.supported ? system.data : null;
  const internal = locations.data?.resources.find(item => item.id === 'system');
  const isDefault = locations.data?.default_storage === 'system';

  return (
    <div className="space-y-4">
      <section aria-label="Interner Speicher">
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <div>
                <div className="font-semibold">Interner Speicher</div>
                <div className="text-xs text-white/45">Systemlaufwerk{disk ? ` ${disk.disk}` : ''} · für Dateien, Apps und virtuelle Maschinen</div>
              </div>
            </div>
            {disk?.available && disk.growable_bytes > 0 && (
              <Button size="sm" variant="primary" onClick={() => setGrowing(true)}>
                <Maximize2 className="size-4" /> Ganze Platte nutzen
              </Button>
            )}
          </div>
          {locations.loading ? <Loading /> : internal?.available ? (
            <>
              <Usage used={internal.used_bytes ?? internal.total_bytes - internal.free_bytes} total={internal.total_bytes} free={internal.free_bytes} />
              <p className="mt-3 text-sm text-white/60">Der Datenbereich auf der Titan-Systemplatte ist bereits nutzbar. Dafür muss kein neuer Speicherbereich angelegt oder formatiert werden. Ein Teil der Platte bleibt für Titan und Systemupdates reserviert.</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" variant="primary" busy={savingDefault} disabled={isDefault} onClick={async () => {
                  setSavingDefault(true);
                  try {
                    await action('storage_preferences_save', { default_storage: 'system' });
                    toast('Interner Speicher als Standard für neue Daten gewählt. Vorhandene Daten bleiben an ihrem Speicherort.');
                    await locations.reload();
                  } catch (reason) { toast(message(reason), true); }
                  finally { setSavingDefault(false); }
                }}>{isDefault ? 'Standard für neue Daten' : 'Für neue Daten verwenden'}</Button>
                <Button size="sm" onClick={() => go('settings', 'shares')}>Freigaben verwalten</Button>
              </div>
            </>
          ) : <Notice>{internal?.error || locations.error || 'Der interne Datenspeicher ist derzeit nicht erreichbar.'}</Notice>}
          {!system.loading && (system.error || system.data && !system.data.supported) && (
            <p className="mt-3 text-sm text-warn">Erweiterung derzeit nicht verfügbar: {system.error || system.data?.reason}</p>
          )}
          {disk && disk.growable_bytes > 0 && (
            <p className="mt-3 text-sm text-white/60">
              Auf dem Systemlaufwerk sind noch {bytes(disk.growable_bytes)} ungenutzt.
              {!disk.available && disk.reason ? ` ${disk.reason}` : ''}
            </p>
          )}
        </Card>
      </section>
      {data.volumes.map(volume => (
        <Card key={volume.name}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <div>
                <div className="font-semibold">{volume.name}</div>
                <div className="text-xs text-white/45">
                  <span className="uppercase">{volume.filesystem}</span>
                  {volume.mirror && ` · Spiegel aus ${(volume.disks || []).length} Laufwerken`}
                </div>
              </div>
            </div>
            <span className={cx('rounded-full px-2.5 py-0.5 text-xs font-medium', volume.degraded || volume.errors ? 'bg-bad/15 text-bad' : volume.mounted && !volume.replacing ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn')}>{volume.state}</span>
          </div>
          {volume.mounted && <Usage used={volume.used} total={volume.total} free={volume.free} />}
          {volume.replacing && (
            <p className="mt-3 text-sm text-white/60">
              Die Daten werden auf {volume.replacing.disk} übertragen{volume.replacing.percent != null ? ` (${Math.round(volume.replacing.percent)} %)` : ''}. Das NAS bleibt dabei benutzbar.
            </p>
          )}
          {!volume.replacing && volume.error && <p className="mt-3 text-sm text-warn">{volume.error}</p>}
          {volume.mirror && !volume.replacing && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 truncate text-xs text-white/45">{(volume.disks || []).join(' · ')}</span>
              <Button size="sm" variant={volume.degraded || volume.errors ? 'primary' : 'secondary'} onClick={() => setReplacing(volume)}>
                <Replace className="size-4" /> Laufwerk ersetzen
              </Button>
            </div>
          )}
        </Card>
      ))}
      {data.pools.map(pool => (
        <Card key={pool.name}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <div>
                <div className="font-semibold">{pool.name}</div>
                <div className="text-xs text-white/45">ZFS-Verbund</div>
              </div>
            </div>
            <span className={cx('rounded-full px-2.5 py-0.5 text-xs font-medium', pool.health === 'ONLINE' ? 'bg-ok/15 text-ok' : 'bg-bad/15 text-bad')}>
              {pool.health === 'ONLINE' ? 'In Ordnung' : pool.health}
            </span>
          </div>
          <Usage used={pool.used} total={pool.size} free={pool.free} />
        </Card>
      ))}
      <Card>
        <h2 className="text-sm font-semibold">Laufwerke</h2>
        <ul className="mt-2 divide-y divide-white/6">
          {data.disks.map(item => (
            <li key={item.name} className="flex items-center justify-between gap-4 py-2.5 text-sm">
              <span className="min-w-0 truncate">
                <span className="font-medium">{item.model || 'Laufwerk'}</span> <span className="text-white/45">{item.name}</span>
              </span>
              <span className="shrink-0 tabular-nums text-white/65">
                {bytes(item.size)} · {isBlank(item) ? 'leer' : 'in Verwendung'}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Plus className="size-4" /> Neuer Speicherbereich
        </Button>

      </div>
      <details className="glass-soft rounded-2xl p-4"><summary className="cursor-pointer text-sm font-semibold">Wartung, Wiederherstellungspunkte und Standardspeicher</summary><ManagementPanel feature="storage" /></details>
      {creating && <CreateDialog storage={data} onClose={() => setCreating(false)} onDone={storage.reload} />}
      {replacing && <ReplaceDialog volume={replacing} storage={data} onClose={() => setReplacing(null)} onDone={storage.reload} />}
      {growing && disk && (
        <Confirm
          title="Ganzes Systemlaufwerk nutzen?"
          text={`Der interne Datenbereich wird um ${bytes(disk.growable_bytes)} erweitert. Die System- und Bootpartitionen bleiben unverändert. Vorhandene Daten bleiben erhalten; der Vorgang lässt sich nicht rückgängig machen.`}
          confirmLabel="Erweitern"
          onClose={() => setGrowing(false)}
          onConfirm={async () => {
            try {
              const result = await action('system_disk_grow', { expected_revision: disk.revision, confirmation: 'ERWEITERN' });
              toast(String(result.message || 'Interner Speicher erweitert.'));
            } catch (reason) {
              toast(message(reason), true);
            }
            await Promise.all([system.reload(), locations.reload(), storage.reload()]);
          }}
        />
      )}
    </div>
  );
}
