import { VmBackups } from './VmBackups';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { action } from '../api';
import type { Vm, VmNetwork, VmOptions } from '../api';
import { bytes, message, useApi } from '../lib';
import { Button, Card, Confirm, Field, Input, Loading, Modal, Notice, Select, useToast } from '../ui';
import { VmPciDialog, VmUsbDialog } from './Devices';

type Disk = { target: string; disk: string; storage: string; virtual_size: number; boot: boolean };
type Hardware = { disks: Disk[]; networks: (VmNetwork & { index: number })[]; guest_agent: { configured: boolean; message: string } };
type Run = (operation: string, args: Record<string, unknown>, done: string) => Promise<boolean>;
const defaultNetwork: VmNetwork = { mode: 'network', source: 'default', model: 'virtio', mac: '', connected: true };

function NetworkFields({ value, onChange, options }: { value: VmNetwork; onChange: (value: VmNetwork) => void; options: VmOptions }) {
  const choices = options.network_options;
  const sources = value.mode === 'network' ? choices?.networks.map(item => item.name) : value.mode === 'bridge' ? choices?.bridges : choices?.interfaces;
  return <div className="space-y-3">
    <Field label="Netzwerkart"><Select value={value.mode} onChange={event => onChange({ ...value, mode: event.target.value, source: '' })}>
      <option value="network">Virtuelles Netzwerk (NAT / isoliert)</option><option value="bridge">Netzwerkbrücke</option><option value="direct">Direkte Schnittstelle (macvtap)</option>
    </Select></Field>
    <Field label="Netzwerk"><Select required value={value.source} onChange={event => onChange({ ...value, source: event.target.value })}>
      <option value="">Bitte auswählen</option>
      {value.source && !sources?.includes(value.source) && <option value={value.source} disabled>{value.source} · nicht verfügbar</option>}
      {sources?.map(source => <option key={source}>{source}</option>)}
    </Select></Field>
    {value.mode === 'direct' && <Notice tone="info">Bei macvtap kann der Gast den NAS-Host über diese Schnittstelle normalerweise nicht erreichen.</Notice>}
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Netzwerkkartenmodell"><Select value={value.model} onChange={event => onChange({ ...value, model: event.target.value })}><option value="virtio">VirtIO</option><option value="e1000">Intel E1000</option></Select></Field>
      <Field label="MAC-Adresse" help="Leer lassen für automatische Vergabe."><Input value={value.mac} onChange={event => onChange({ ...value, mac: event.target.value })} /></Field>
    </div>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={value.connected} onChange={event => onChange({ ...value, connected: event.target.checked })} /> Kabel verbunden</label>
  </div>;
}

function NetworkEditor({ network, options, run, onClose }: { network?: VmNetwork & { index: number }; options: VmOptions; run: Run; onClose: () => void }) {
  const [value, setValue] = useState<VmNetwork>(network ? { mode: network.mode, source: network.source, model: network.model, mac: network.mac, connected: network.connected } : defaultNetwork);
  return <form className="space-y-3" onSubmit={async event => {
    event.preventDefault();
    if (await run(network ? 'vm_nic_update' : 'vm_nic_add', { network: value, ...(network ? { index: network.index } : {}) }, 'Netzwerkkarte gespeichert.')) onClose();
  }}>
    <NetworkFields value={value} onChange={setValue} options={options} />
    <div className="flex gap-2"><Button type="submit" variant="primary">Netzwerkkarte speichern</Button><Button onClick={onClose}>Abbrechen</Button></div>
  </form>;
}

/** Hardware changes use Titan's existing offline validation and job queue. */
export function VmSettings({ vm, onClose, onChanged }: { vm: Vm; onClose: () => void; onChanged: () => void }) {
  const options = useApi<VmOptions>('/api/vm-options');
  const hardware = useApi<Hardware>(`/api/vm-extensions?vm=${encodeURIComponent(vm.id)}`);
  const toast = useToast();
  const [tab, setTab] = useState('general');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({ name: vm.display_name || vm.name, cpus: vm.cpus, memory: vm.memory_mb, firmware: vm.firmware || 'bios', boot: vm.boot || 'hd' });
  const [pins, setPins] = useState(vm.cpu_ids || []);
  const [manual, setManual] = useState(Boolean(vm.cpu_ids?.length));
  const [iso, setIso] = useState(vm.iso || '');
  const [newDisk, setNewDisk] = useState(32);
  const [storage, setStorage] = useState('');
  const [grow, setGrow] = useState<Record<string, number>>({});
  const [network, setNetwork] = useState<number | 'new' | null>(null);
  const [devices, setDevices] = useState<'usb' | 'pci' | null>(null);
  const [remove, setRemove] = useState<{ operation: string; args: Record<string, unknown>; title: string; text: string } | null>(null);
  const off = vm.state === 'shut off';
  const label = vm.display_name || vm.name;
  const run: Run = async (operation, args, done) => {
    setBusy(true); setError('');
    try {
      await action(operation, { vm: vm.id, ...args });
      toast(done);
      await hardware.reload(); onChanged();
      return true;
    } catch (reason) { setError(message(reason)); return false; }
    finally { setBusy(false); }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (manual && pins.length < form.cpus) return setError('Mindestens so viele Host-CPUs wie virtuelle CPUs auswählen.');
    await run('vm_update', { display_name: form.name, cpus: form.cpus, memory_mb: form.memory, firmware: form.firmware, boot: form.boot, cpu_ids: manual ? pins : [] }, 'VM-Einstellungen gespeichert.');
  };
  const storageSelect = <Field label="Speicherort des neuen Laufwerks"><Select value={storage || options.data?.default_storage || 'system'} onChange={event => setStorage(event.target.value)}>
    {options.data?.storage.map(item => <option key={item.id} value={item.id} disabled={!item.available}>{item.label} · {bytes(item.free_bytes)} frei</option>)}
  </Select></Field>;
  return <Modal title={`Einstellungen · ${label}`} onClose={onClose} wide>
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="VM-Einstellungen">
        {[['general', 'Allgemein'], ['disks', 'Laufwerke und ISO'], ['network', 'Netzwerk'], ['devices', 'Geräte'], ['backups', 'Sicherungen und Klone']].map(([id, title]) => <Button key={id} role="tab" aria-selected={id === tab} onClick={() => setTab(id)} variant={id === tab ? 'primary' : 'secondary'}>{title}</Button>)}
      </div>
      {!off && <Notice tone="info">Zum Ändern der Hardware die VM zuerst vollständig herunterfahren. Die aktuellen Einstellungen bleiben sichtbar.
        {vm.state === 'running' && <Button className="mt-2" busy={busy} onClick={() => run('vm_action', { action: 'shutdown' }, 'Herunterfahren angefordert.')}>VM herunterfahren</Button>}
      </Notice>}
      {error && <Notice>{error}</Notice>}
      {options.loading || hardware.loading ? <Loading /> : !options.data || !hardware.data ? <Notice>{options.error || hardware.error}</Notice> : <>
        {tab === 'general' && <>
          <form onSubmit={save}>
            <fieldset disabled={!off || busy} className="space-y-4 disabled:opacity-60">
              <Field label="Anzeigename"><Input required maxLength={96} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="CPU-Kerne"><Input type="number" required min={1} max={Math.max(1, options.data.cpu_topology?.cpus.filter(cpu => cpu.online !== false).length || 64)} value={form.cpus} onChange={event => setForm({ ...form, cpus: Number(event.target.value) })} /></Field>
                <Field label="RAM (MiB)"><Input type="number" required min={512} step={1} value={form.memory} onChange={event => setForm({ ...form, memory: Number(event.target.value) })} /></Field>
              </div>
              <Field label="Host-CPUs zuweisen"><Select value={manual ? 'manual' : 'auto'} onChange={event => setManual(event.target.value === 'manual')}><option value="auto">Automatisch</option><option value="manual">Manuell auswählen</option></Select></Field>
              {manual && <div className="flex flex-wrap gap-3">{options.data.cpu_topology?.cpus.map(cpu => <label key={cpu.id} className="text-sm"><input type="checkbox" disabled={cpu.online === false} checked={pins.includes(cpu.id)} onChange={event => setPins(event.target.checked ? [...pins, cpu.id] : pins.filter(id => id !== cpu.id))} /> CPU {cpu.id}{cpu.core_type === 'performance' ? ' (P)' : cpu.core_type === 'efficiency' ? ' (E)' : ''}</label>)}</div>}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Firmware"><Select value={form.firmware} onChange={event => setForm({ ...form, firmware: event.target.value })}>{Array.from(new Set([form.firmware, ...options.data.firmwares])).map(item => <option key={item} value={item}>{item.toUpperCase()}</option>)}</Select></Field>
                <Field label="Zuerst starten von"><Select value={form.boot} onChange={event => setForm({ ...form, boot: event.target.value })}><option value="hd">Festplatte</option><option value="cdrom">CD/DVD</option><option value="network">Netzwerk (PXE)</option></Select></Field>
              </div>
              {form.firmware !== (vm.firmware || 'bios') && <Notice tone="warn">Das installierte Gastsystem muss den gewählten Bootmodus unterstützen. Ein Wechsel konvertiert die Gastfestplatte nicht.</Notice>}
              <Button type="submit" variant="primary" busy={busy}>Einstellungen speichern</Button>
            </fieldset>
          </form>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={busy} checked={vm.autostart} onChange={event => run('vm_action', { action: event.target.checked ? 'autostart' : 'disable-autostart' }, 'Automatischer Start gespeichert.')} /> Beim Start des NAS automatisch starten</label>
        </>}
        {tab === 'disks' && <fieldset disabled={!off || busy} className="space-y-4 disabled:opacity-60">
          <form className="space-y-3" onSubmit={async event => { event.preventDefault(); if (await run('vm_media', { iso: iso || null }, 'Installationsmedium gespeichert.')) setForm({ ...form, boot: iso ? 'cdrom' : 'hd' }); }}>
            <Field label="CD/DVD-Medium"><Select value={iso} onChange={event => setIso(event.target.value)}><option value="">Ausgeworfen</option>{options.data.isos.map(item => <option key={item}>{item}</option>)}</Select></Field>
            <Button type="submit">Medium speichern</Button>
          </form>
          {hardware.data.disks.map(disk => <Card key={disk.target} className="space-y-3">
            <p className="text-sm font-medium">{disk.target} · {disk.boot ? 'Systemlaufwerk' : 'Zusätzliches Laufwerk'} · {bytes(disk.virtual_size)}</p>
            <p className="break-all text-xs text-white/50">{disk.disk}</p>
            <form className="flex items-end gap-2" onSubmit={event => { event.preventDefault(); void run('vm_disk_grow', { disk_gb: grow[disk.target] || Math.ceil(disk.virtual_size / 1024 ** 3) + 16, target: disk.target }, 'Laufwerk erweitert. Partition und Dateisystem im Gast anschließend erweitern.'); }}>
              <Field label={`Neue Größe für ${disk.target} (GiB)`}><Input type="number" required min={Math.floor(disk.virtual_size / 1024 ** 3) + 1} max={16384} value={grow[disk.target] ?? Math.ceil(disk.virtual_size / 1024 ** 3) + 16} onChange={event => setGrow({ ...grow, [disk.target]: Number(event.target.value) })} /></Field>
              <Button type="submit">Erweitern</Button>
              {!disk.boot && <Button onClick={() => setRemove({ operation: 'vm_disk_remove', args: { target: disk.target }, title: `${disk.target} trennen?`, text: 'Das Laufwerk wird aus der VM entfernt. Die Image-Datei und ihre Daten bleiben erhalten.' })}>Trennen</Button>}
            </form>
          </Card>)}
          <p className="text-xs text-white/55">Verkleinern wird zum Schutz der Daten nicht angeboten. Nach dem Erweitern auch Partition und Dateisystem im Gast vergrößern.</p>
          <form className="space-y-3" onSubmit={event => { event.preventDefault(); void run('vm_disk_add', { disk_gb: newDisk, storage: storage || options.data!.default_storage }, 'Laufwerk hinzugefügt. Im Gast partitionieren und formatieren.'); }}>
            <Field label="Zusätzliches Laufwerk (GiB)"><Input type="number" min={1} max={16384} required value={newDisk} onChange={event => setNewDisk(Number(event.target.value))} /></Field>
            {storageSelect}<Button type="submit">Laufwerk hinzufügen</Button>
          </form>
        </fieldset>}
        {tab === 'network' && <fieldset disabled={!off || busy} className="space-y-4 disabled:opacity-60">
          {hardware.data.networks.map(nic => <Card key={nic.index} className="space-y-3"><p className="text-sm">Netzwerkkarte {nic.index + 1} · {nic.source} · {nic.model} · {nic.mac || 'Automatische MAC'}</p>
            <div className="flex gap-2"><Button onClick={() => setNetwork(nic.index)}>Bearbeiten</Button><Button onClick={() => setRemove({ operation: 'vm_nic_remove', args: { index: nic.index }, title: 'Netzwerkkarte entfernen?', text: 'Die VM verliert die Verbindung über diese Netzwerkkarte.' })}>Entfernen</Button></div>
          </Card>)}
          {network === null ? <Button onClick={() => setNetwork('new')}>Netzwerkkarte hinzufügen</Button> : <NetworkEditor key={network} network={hardware.data.networks.find(nic => nic.index === network)} options={options.data} run={run} onClose={() => setNetwork(null)} />}
          {options.data.network_options?.warnings.map(warning => <Notice key={warning} tone="warn">{warning}</Notice>)}
        </fieldset>}
        {tab === 'backups' && <VmBackups vm={vm} options={options.data} onChanged={onChanged} />}
        {tab === 'devices' && <div className="space-y-4">
          <div className="flex flex-wrap gap-2"><Button onClick={() => setDevices('usb')}>USB-Geräte zuordnen</Button><Button onClick={() => setDevices('pci')}>Grafikkarte und PCI-Geräte zuordnen</Button></div>
          <label className="flex gap-2 text-sm"><input type="checkbox" disabled={!off || busy} checked={hardware.data.guest_agent.configured} onChange={event => run('vm_guest_agent', { enabled: event.target.checked }, 'Gastagent-Kanal gespeichert.')} /> QEMU-Gastagent aktivieren</label>
          <p className="text-sm text-white/55">{hardware.data.guest_agent.message}</p>
        </div>}
      </>}
      <div className="flex justify-end"><Button onClick={onClose} disabled={busy}>Schließen</Button></div>
    </div>
    {devices === 'usb' && <VmUsbDialog vm={vm.id} label={label} onClose={() => setDevices(null)} />}
    {devices === 'pci' && <VmPciDialog vm={vm.id} label={label} onClose={() => setDevices(null)} />}
    {remove && <Confirm title={remove.title} text={remove.text} confirmLabel="Bestätigen" onClose={() => setRemove(null)} onConfirm={async () => { await run(remove.operation, remove.args, 'VM-Hardware geändert.'); }} />}
  </Modal>;
}
