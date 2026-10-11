import { useEffect, useState } from 'react';
import { Cpu, Usb } from 'lucide-react';
import { action } from '../api';
import { cx, message, useApi } from '../lib';
import { Button, Card, Loading, Modal, Notice, useToast } from '../ui';

type AppDevice = { id: string; label: string; kind: 'usb' | 'gpu' | 'npu' };
type AppDevices = { devices: AppDevice[]; notes: string[] };
type UsbDevice = { id: string; name: string; port?: string; serial?: string; blocked?: boolean; reason?: string; selected?: boolean };
type VmUsb = { devices: UsbDevice[]; selected: string[]; editable: boolean };

const KINDS: Record<AppDevice['kind'], string> = { gpu: 'Grafikkarten', npu: 'KI-Beschleuniger', usb: 'USB-Geräte' };

function Check({ checked, disabled, onChange, title, detail }: { checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void; title: string; detail?: string }) {
  return (
    <label className={cx('flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-white/6', disabled && 'cursor-not-allowed opacity-55')}>
      <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-[var(--color-brand)]" checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)} />
      <span className="min-w-0">
        <span className="block text-sm [overflow-wrap:anywhere]">{title}</span>
        {detail && <span className="block text-xs text-white/45">{detail}</span>}
      </span>
    </label>
  );
}

/** Graphics cards and USB devices handed to a Docker app. The agent only accepts changes while the app is stopped. */
export function AppDevicesCard({ app, assigned, running, onSaved }: { app: string; assigned: string[]; running: boolean; onSaved: () => void }) {
  const toast = useToast();
  const inventory = useApi<AppDevices>('/api/app-devices');
  const [selected, setSelected] = useState<string[]>(assigned);
  const [busy, setBusy] = useState(false);
  const key = assigned.join('\n');
  useEffect(() => setSelected(assigned), [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const devices = inventory.data?.devices || [];
  // Keep a device that is assigned but currently unplugged visible, so it can be removed.
  const missing = assigned.filter(id => !devices.some(device => device.id === id));
  const changed = selected.length !== assigned.length || selected.some(id => !assigned.includes(id));

  const save = async () => {
    setBusy(true);
    try {
      await action('app_hardware', { app, hardware: selected });
      toast('Geräte gespeichert. Sie gelten ab dem nächsten Start der App.');
      onSaved();
    } catch (reason) {
      toast(message(reason), true);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: string, on: boolean) => setSelected(on ? [...selected, id] : selected.filter(item => item !== id));

  return (
    <Card>
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Cpu className="size-4 text-white/50" aria-hidden /> Grafikkarte und Geräte
      </h2>
      {inventory.loading ? (
        <Loading />
      ) : !devices.length && !missing.length ? (
        <p className="mt-2 text-sm leading-relaxed text-white/55">Titan hat keine Grafikkarte und kein USB-Gerät gefunden, das sich an eine App durchreichen lässt.</p>
      ) : (
        <>
          {running && (
            <div className="mt-3">
              <Notice tone="info">Zum Ändern die App zuerst stoppen.</Notice>
            </div>
          )}
          {(Object.keys(KINDS) as AppDevice['kind'][]).map(kind => {
            const items = devices.filter(device => device.kind === kind);
            if (!items.length) return null;
            return (
              <div key={kind} className="mt-3">
                <div className="px-3 text-xs font-medium uppercase tracking-wider text-white/40">{KINDS[kind]}</div>
                {items.map(device => (
                  <Check key={device.id} title={device.label} checked={selected.includes(device.id)} disabled={running || busy} onChange={on => toggle(device.id, on)} />
                ))}
              </div>
            );
          })}
          {missing.map(id => (
            <Check key={id} title={id} detail="Nicht angeschlossen. Abwählen entfernt die Zuordnung." checked={selected.includes(id)} disabled={running || busy} onChange={on => toggle(id, on)} />
          ))}
          <Button className="mt-3 w-full" variant="primary" busy={busy} disabled={running || !changed} onClick={save}>
            Geräte speichern
          </Button>
        </>
      )}
    </Card>
  );
}

/** USB devices passed through to a virtual machine. */
export function VmUsbDialog({ vm, label, onClose }: { vm: string; label: string; onClose: () => void }) {
  const toast = useToast();
  const usb = useApi<VmUsb>(`/api/vm-usb?vm=${encodeURIComponent(vm)}`);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = selected ?? usb.data?.selected ?? [];

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await action('vm_usb_update', { vm, devices: current });
      toast(`USB-Geräte für „${label}“ gespeichert.`);
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title={`USB-Geräte für „${label}“`} onClose={onClose}>
      {usb.loading ? (
        <Loading />
      ) : usb.error || !usb.data ? (
        <Notice>{usb.error || 'USB-Geräte konnten nicht gelesen werden.'}</Notice>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-white/50">Beta · USB-Durchreichung ist noch nicht umfassend auf physischer Hardware erprobt.</p>
          {!usb.data.editable && <Notice tone="info">Zum Ändern die VM zuerst herunterfahren.</Notice>}
          {usb.data.devices.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-white/55">
              <Usb className="size-4" aria-hidden /> Am NAS ist kein USB-Gerät angeschlossen, das sich durchreichen lässt.
            </p>
          ) : (
            <div>
              {usb.data.devices.map(device => (
                <Check
                  key={device.id}
                  title={device.name || device.id}
                  detail={[device.id, device.serial && `Seriennummer ${device.serial}`, device.reason].filter(Boolean).join(' · ')}
                  checked={current.includes(device.id)}
                  disabled={!usb.data!.editable || busy || (device.blocked && !current.includes(device.id))}
                  onChange={on => setSelected(on ? [...current, device.id] : current.filter(item => item !== device.id))}
                />
              ))}
            </div>
          )}
          <p className="text-xs leading-relaxed text-white/45">Ein durchgereichtes Gerät steht Titan, Apps und anderen VMs nicht mehr zur Verfügung. Pro VM sind bis zu acht Geräte möglich.</p>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button variant="primary" busy={busy} disabled={!usb.data.editable || selected === null} onClick={save}>
              Speichern
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

type PciDevice = { address: string; kind: 'gpu' | 'accelerator'; name: string; driver: string | null; companions: string[]; blocked: boolean; reason: string; warning?: string };
type VmPci = { devices: PciDevice[]; selected: string[]; iommu: boolean; editable: boolean };

/** Graphics cards and accelerators handed to a virtual machine as whole PCI devices. */
export function VmPciDialog({ vm, label, onClose }: { vm: string; label: string; onClose: () => void }) {
  const toast = useToast();
  const pci = useApi<VmPci>(`/api/vm-pci?vm=${encodeURIComponent(vm)}`);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = selected ?? pci.data?.selected ?? [];

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      await action('vm_pci_update', { vm, devices: current });
      toast(`PCI-Geräte für „${label}“ gespeichert.`);
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title={`Grafikkarte und PCI-Geräte für „${label}“`} onClose={onClose}>
      {pci.loading ? (
        <Loading />
      ) : pci.error || !pci.data ? (
        <Notice>{pci.error || 'PCI-Geräte konnten nicht gelesen werden.'}</Notice>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-white/50">Beta · PCI-Durchreichung ist noch nicht umfassend auf physischer Hardware erprobt.</p>
          {!pci.data.iommu && <Notice tone="warn">IOMMU ist nicht aktiv. Schalte VT-d (Intel) oder AMD-Vi im BIOS/UEFI des NAS ein und starte neu.</Notice>}
          {!pci.data.editable && <Notice tone="info">Zum Ändern die VM zuerst herunterfahren.</Notice>}
          {pci.data.devices.length === 0 ? (
            <p className="text-sm text-white/55">Titan hat keine Grafikkarte und keinen Beschleuniger gefunden, der sich durchreichen lässt.</p>
          ) : (
            <div>
              {pci.data.devices.map(device => (
                <Check
                  key={device.address}
                  title={device.name}
                  detail={[device.address, device.companions.length ? `mit ${device.companions.join(', ')}` : '', device.reason || device.warning].filter(Boolean).join(' · ')}
                  checked={current.includes(device.address)}
                  disabled={!pci.data!.editable || busy || (device.blocked && !current.includes(device.address))}
                  onChange={on => setSelected(on ? [...current, device.address] : current.filter(item => item !== device.address))}
                />
              ))}
            </div>
          )}
          <p className="text-xs leading-relaxed text-white/45">
            Ein durchgereichtes Gerät gehört der VM, solange sie läuft. Titan und Apps können es in dieser Zeit nicht verwenden; nach dem Ausschalten erhält Titan es zurück. Für Grafikkarten sollte die VM mit UEFI angelegt sein.
          </p>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button variant="primary" busy={busy} disabled={!pci.data.editable || selected === null} onClick={save}>
              Speichern
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
