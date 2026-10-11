import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Disc3, MonitorPlay, Plus, Power, PowerOff, RotateCw, Play, Trash2, X, Zap } from 'lucide-react';
import { ISO_NAME, action, uploadIso } from '../api';
import type { Vm, VmList, VmOptions } from '../api';
import { bytes, message, useApi } from '../lib';
import { Button, Card, Confirm, Empty, Field, IconButton, Input, Loading, Meter, Modal, Notice, Select, Sheet, StateDot, useToast } from '../ui';

const STATES: Record<string, string> = { running: 'Läuft', 'shut off': 'Aus', paused: 'Pausiert', 'in shutdown': 'Fährt herunter', crashed: 'Abgestürzt' };

function CreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const options = useApi<VmOptions>('/api/vm-options');
  const [form, setForm] = useState({ name: '', cpus: '2', memory: '4', disk: '32', source: '', storage: '', firmware: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm({ ...form, [key]: event.target.value });

  // The agent needs a boot source: an installer ISO or an existing disk image.
  const sources = [
    ...(options.data?.isos || []).map(iso => ({ value: 'iso:' + iso, label: iso, group: 'ISO-Abbilder' })),
    ...(options.data?.disk_images || []).map(image => ({ value: 'image:' + image.id, label: image.name + ' · ' + bytes(image.virtual_size), group: 'Laufwerksimages' })),
  ];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!options.data) return;
    const source = form.source || sources[0]?.value || '';
    setBusy(true);
    setError('');
    try {
      await action('vm_create', {
        name: form.name.trim(),
        cpus: Number(form.cpus),
        memory_mb: Math.round(Number(form.memory) * 1024),
        disk_gb: Number(form.disk),
        ...(source.startsWith('iso:') ? { iso: source.slice(4) } : { iso: null, disk_image: source.slice(6) }),
        storage: form.storage || options.data.default_storage,
        firmware: form.firmware || options.data.firmwares[0] || 'bios',
      });
      toast(`VM „${form.name.trim()}“ angelegt.`);
      onCreated();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Neue virtuelle Maschine" onClose={onClose} wide>
      {options.loading ? (
        <Loading />
      ) : options.error || !options.data ? (
        <Notice>{options.error || 'VM-Optionen nicht verfügbar.'}</Notice>
      ) : !sources.length ? (
        <Notice tone="info">
          Für eine neue VM wird ein ISO-Abbild oder ein Laufwerksimage benötigt. Lade zuerst über „ISO hochladen“ ein Installationsmedium hoch.
        </Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Name">
            <Input value={form.name} onChange={set('name')} required maxLength={60} placeholder="z. B. Home Assistant" />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="CPU-Kerne">
              <Input type="number" min={1} max={64} value={form.cpus} onChange={set('cpus')} required />
            </Field>
            <Field label="RAM (GiB)">
              <Input type="number" min={0.5} step={0.5} value={form.memory} onChange={set('memory')} required />
            </Field>
            <Field label="Disk (GiB)">
              <Input type="number" min={8} value={form.disk} onChange={set('disk')} required />
            </Field>
          </div>
          <Field label="Startmedium" help="Weitere Installationsmedien fügst du über „ISO hochladen“ hinzu.">
            <Select value={form.source || sources[0].value} onChange={set('source')}>
              {['ISO-Abbilder', 'Laufwerksimages'].map(group => {
                const items = sources.filter(item => item.group === group);
                return items.length ? (
                  <optgroup key={group} label={group}>
                    {items.map(item => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </optgroup>
                ) : null;
              })}
            </Select>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Speicherort">
              <Select value={form.storage || options.data.default_storage} onChange={set('storage')}>
                {options.data.storage.filter(item => item.available).map(item => (
                  <option key={item.id} value={item.id}>{item.label} · {bytes(item.free_bytes)} frei</option>
                ))}
              </Select>
            </Field>
            <Field label="Firmware">
              <Select value={form.firmware || options.data.firmwares[0]} onChange={set('firmware')}>
                {options.data.firmwares.map(item => (
                  <option key={item} value={item}>{item.toUpperCase()}</option>
                ))}
              </Select>
            </Field>
          </div>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Anlegen</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function VmCard({ vm, onChanged }: { vm: Vm; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<'poweroff' | 'remove' | null>(null);
  const label = vm.display_name || vm.name;
  const running = vm.state === 'running';
  const off = vm.state === 'shut off';

  const run = async (command: string, done: string) => {
    setBusy(true);
    try {
      await action('vm_action', { vm: vm.id, action: command });
      toast(`${label}: ${done}`);
    } catch (reason) {
      toast(`${label}: ${message(reason)}`, true);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  const openConsole = () => window.open(`/console.html?${new URLSearchParams({ vm: vm.id, name: label })}`, '_blank', 'noopener');

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-start gap-3.5">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-300 to-teal-600 shadow-lg shadow-black/30">
          <MonitorPlay className="size-6" strokeWidth={1.8} aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{label}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[13px] text-white/55">
            <StateDot state={busy ? 'restarting' : vm.state} /> {STATES[vm.state] || vm.state}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-white/40">CPU</dt>
          <dd className="mt-0.5 tabular-nums">{vm.cpus} Kerne{running && vm.metrics?.cpu_percent != null ? ` · ${Math.round(vm.metrics.cpu_percent)} %` : ''}</dd>
        </div>
        <div>
          <dt className="text-xs text-white/40">RAM</dt>
          <dd className="mt-0.5 tabular-nums">{bytes(vm.memory_mb * 1024 * 1024)}</dd>
        </div>
        <div>
          <dt className="text-xs text-white/40">Disk</dt>
          <dd className="mt-0.5 tabular-nums">{vm.disk_gb} GB</dd>
        </div>
      </dl>
      <div className="flex items-center gap-2">
        {running ? (
          <>
            <Button size="sm" variant="primary" onClick={openConsole}>
              <MonitorPlay className="size-4" /> Konsole
            </Button>
            <Button size="sm" busy={busy} onClick={() => run('shutdown', 'Herunterfahren angefordert.')}>
              <Power className="size-4" /> Herunterfahren
            </Button>
            <span className="flex-1" />
            <IconButton label="Neu starten" disabled={busy} onClick={() => run('reboot', 'Neustart angefordert.')}>
              <RotateCw className="size-4" />
            </IconButton>
            <IconButton label="Sofort ausschalten" disabled={busy} onClick={() => setConfirm('poweroff')}>
              <Zap className="size-4" />
            </IconButton>
          </>
        ) : (
          <>
            <Button size="sm" variant="primary" busy={busy} disabled={!off && vm.state !== 'paused'} onClick={() => run('start', 'gestartet.')}>
              <Play className="size-4" /> Starten
            </Button>
            <span className="flex-1" />
            {off ? (
              <IconButton label="VM löschen" disabled={busy} onClick={() => setConfirm('remove')}>
                <Trash2 className="size-4" />
              </IconButton>
            ) : (
              <IconButton label="Sofort ausschalten" disabled={busy} onClick={() => setConfirm('poweroff')}>
                <PowerOff className="size-4" />
              </IconButton>
            )}
          </>
        )}
      </div>
      {confirm === 'poweroff' && (
        <Confirm
          title={`${label} sofort ausschalten?`}
          text="Das entspricht dem Ziehen des Netzsteckers. Nicht gespeicherte Daten im Gast gehen verloren."
          confirmLabel="Ausschalten"
          danger
          onClose={() => setConfirm(null)}
          onConfirm={() => run('poweroff', 'ausgeschaltet.')}
        />
      )}
      {confirm === 'remove' && (
        <Confirm
          title={`${label} löschen?`}
          text="Die VM und ihre virtuellen Datenträger werden dauerhaft gelöscht. Das lässt sich nicht rückgängig machen."
          confirmLabel="Endgültig löschen"
          danger
          onClose={() => setConfirm(null)}
          onConfirm={() => run('remove', 'gelöscht.')}
        />
      )}
    </Card>
  );
}

export function Vms() {
  const vms = useApi<VmList>('/api/vms', 5000);
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [iso, setIso] = useState<{ name: string; fraction: number } | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);

  const startIso = async (file: File | undefined) => {
    if (!file || iso) return;
    if (!ISO_NAME.test(file.name) || !file.size) return toast('Eine nicht leere .iso-Datei mit einfachem Namen wählen (Buchstaben, Ziffern, Punkt, - und _).', true);
    const controller = new AbortController();
    abort.current = controller;
    setIso({ name: file.name, fraction: 0 });
    try {
      await uploadIso(file, fraction => setIso({ name: file.name, fraction }), controller.signal);
      toast(file.name + ' steht als Startmedium bereit.');
    } catch (reason) {
      toast(message(reason), true);
    } finally {
      abort.current = null;
      setIso(null);
    }
  };
  const available = vms.data?.available;

  return (
    <Sheet
      title="Virtuelle Maschinen"
      subtitle="KVM-Gäste direkt auf dem NAS"
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={() => window.open('/classic#vms', '_blank', 'noopener')}>
            Erweiterte Verwaltung
          </Button>
          <Button size="sm" disabled={!available || Boolean(iso)} onClick={() => picker.current?.click()}>
            <Disc3 className="size-4" /> ISO hochladen
          </Button>
          <input
            ref={picker}
            type="file"
            accept=".iso"
            hidden
            onChange={event => {
              const file = event.target.files?.[0];
              event.target.value = '';
              void startIso(file);
            }}
          />
          <Button size="sm" variant="primary" disabled={!available} onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Neue VM
          </Button>
        </>
      }
    >
      {iso && (
        <div className="glass-soft mb-4 flex items-center gap-3 rounded-xl px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex justify-between gap-3 text-xs text-white/70">
              <span className="truncate">{iso.name}</span>
              <span className="shrink-0 tabular-nums">{Math.round(iso.fraction * 100)} %</span>
            </div>
            <Meter value={iso.fraction * 100} tone="ok" />
          </div>
          <IconButton label="ISO-Upload abbrechen" onClick={() => abort.current?.abort()}>
            <X className="size-4" />
          </IconButton>
        </div>
      )}
      {vms.loading ? (
        <Loading />
      ) : vms.error && !vms.data ? (
        <Notice>{vms.error}</Notice>
      ) : !available ? (
        <Notice tone="warn">{vms.data?.error || 'KVM/libvirt ist auf diesem System nicht verfügbar.'}</Notice>
      ) : !vms.data?.vms.length ? (
        <Empty title="Noch keine virtuelle Maschine">
          <Button variant="primary" className="mt-3" onClick={() => setCreating(true)}>
            <Plus className="size-4" /> Erste VM anlegen
          </Button>
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {vms.data.vms.map(vm => (
            <VmCard key={vm.id} vm={vm} onChanged={vms.reload} />
          ))}
        </div>
      )}
      {creating && <CreateDialog onClose={() => setCreating(false)} onCreated={vms.reload} />}
    </Sheet>
  );
}
