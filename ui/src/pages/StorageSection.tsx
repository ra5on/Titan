import { useState } from 'react';
import type { FormEvent } from 'react';
import { HardDrive, Maximize2, Plus } from 'lucide-react';
import { action } from '../api';
import { bytes, cx, message, percent, useApi } from '../lib';
import { Button, Card, Confirm, Field, Input, Loading, Meter, Modal, Notice, Select, useToast } from '../ui';

type Disk = { name: string; size: number; model: string; type?: string; fstype: string | null; mountpoints?: (string | null)[]; children?: unknown[]; ro?: boolean };
type Volume = { name: string; filesystem: string; mounted: boolean; state: string; total: number; used: number; free: number; error?: string | null };
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
  const [layout, setLayout] = useState('mirror');
  const [members, setMembers] = useState<string[]>([]);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const chosen = kind === 'single' ? [disk] : members;
  const expected = kind === 'single' ? disk : name;
  const enough = kind === 'single' ? Boolean(disk) : members.length >= LAYOUTS[layout].minimum;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (kind === 'single') await action('volume_create', { name, disk, filesystem, confirmation_name: name, confirmation_disk: typed });
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
              <option value="single">Ein Laufwerk</option>
              {blank.length >= 2 && <option value="pool">Verbund aus mehreren Laufwerken (ZFS, schützt vor Plattenausfall)</option>}
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

export function StorageSection() {
  const toast = useToast();
  const storage = useApi<Storage>('/api/storage', 30000);
  const system = useApi<SystemDisk>('/api/system-disk', 60000);
  const [creating, setCreating] = useState(false);
  const [growing, setGrowing] = useState(false);

  if (storage.loading) return <Loading />;
  if (storage.error && !storage.data) return <Notice>{storage.error}</Notice>;
  const data = storage.data!;
  const disk = system.data?.supported ? system.data : null;

  return (
    <div className="space-y-4">
      {disk && (
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <div>
                <div className="font-semibold">Interner Speicher</div>
                <div className="text-xs text-white/45">Systemlaufwerk {disk.disk} · für Dateien, Apps und virtuelle Maschinen</div>
              </div>
            </div>
            {disk.available && disk.growable_bytes > 0 && (
              <Button size="sm" variant="primary" onClick={() => setGrowing(true)}>
                <Maximize2 className="size-4" /> Ganze Platte nutzen
              </Button>
            )}
          </div>
          <Usage used={disk.filesystem_used} total={disk.filesystem_size} />
          {disk.growable_bytes > 0 && (
            <p className="mt-3 text-sm text-white/60">
              Auf dem Systemlaufwerk sind noch {bytes(disk.growable_bytes)} ungenutzt.
              {!disk.available && disk.reason ? ` ${disk.reason}` : ''}
            </p>
          )}
        </Card>
      )}
      {data.volumes.map(volume => (
        <Card key={volume.name}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <div>
                <div className="font-semibold">{volume.name}</div>
                <div className="text-xs uppercase text-white/45">{volume.filesystem}</div>
              </div>
            </div>
            <span className={cx('rounded-full px-2.5 py-0.5 text-xs font-medium', volume.mounted ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn')}>{volume.state}</span>
          </div>
          {volume.mounted ? <Usage used={volume.used} total={volume.total} free={volume.free} /> : volume.error && <p className="mt-3 text-sm text-warn">{volume.error}</p>}
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
        <Button onClick={() => window.open('/classic#storage', '_blank', 'noopener')}>Plattentausch, Prüfläufe und Snapshots</Button>
      </div>
      {creating && <CreateDialog storage={data} onClose={() => setCreating(false)} onDone={storage.reload} />}
      {growing && disk && (
        <Confirm
          title="Ganzes Systemlaufwerk nutzen?"
          text={`Der interne Speicher wird um ${bytes(disk.growable_bytes)} auf die volle Größe des Systemlaufwerks erweitert. Vorhandene Daten bleiben erhalten; der Vorgang lässt sich nicht rückgängig machen.`}
          confirmLabel="Erweitern"
          onClose={() => setGrowing(false)}
          onConfirm={async () => {
            try {
              const result = await action('system_disk_grow', { expected_revision: disk.revision, confirmation: 'ERWEITERN' });
              toast(String(result.message || 'Interner Speicher erweitert.'));
            } catch (reason) {
              toast(message(reason), true);
            }
            await system.reload();
          }}
        />
      )}
    </div>
  );
}
