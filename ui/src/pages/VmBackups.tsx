import { useState } from 'react';
import { action } from '../api';
import type { Vm, VmOptions } from '../api';
import { bytes, dateTime, message, useApi } from '../lib';
import { Button, Card, Field, Input, Loading, Notice, Select, useToast } from '../ui';

type Snapshot = { id: string; name: string; created: number; disk_count: number };
type Operation = { kind: 'snapshot' | 'clone' | 'backup' | 'restore' | 'remove'; snapshot?: Snapshot };

/** Kept in the VM settings dialog, beside hardware and networks. */
export function VmBackups({ vm, options, onChanged }: { vm: Vm; options: VmOptions; onChanged: () => void }) {
  const data = useApi<{ snapshots: Snapshot[]; snapshot_note: string; state: string }>(`/api/vm-extensions?vm=${encodeURIComponent(vm.id)}`);
  const locations = useApi<{ items: { label: string; path: string; available: boolean; backup_eligible?: boolean }[] }>('/api/storage-locations?purpose=backup');
  const [operation, setOperation] = useState<Operation | null>(null);
  const [name, setName] = useState('');
  const [storage, setStorage] = useState(options.default_storage);
  const [target, setTarget] = useState('');
  const [shutdown, setShutdown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toast = useToast();
  const off = (data.data?.state || vm.state) === 'shut off';
  const possible = ['shut off', 'running', 'in shutdown'].includes(data.data?.state || vm.state);
  const start = (kind: Operation['kind'], snapshot?: Snapshot) => {
    setOperation({ kind, snapshot }); setShutdown(false); setError('');
    setName(kind === 'snapshot' ? 'Vor Änderung' : `${vm.display_name || vm.name} ${kind === 'clone' ? 'Kopie' : 'Snapshot'}`);
  };
  const titles = { snapshot: 'Snapshot erstellen', clone: 'VM klonen', backup: 'Extern sichern', restore: 'Als neue VM wiederherstellen', remove: 'Snapshot löschen' };
  const submit = async () => {
    if (!operation || busy) return;
    setBusy(true); setError('');
    try {
      const args = { vm: vm.id, name, storage, shutdown };
      if (operation.kind === 'snapshot') await action('vm_snapshot_create', { vm: vm.id, name, shutdown });
      if (operation.kind === 'clone') await action('vm_clone', { vm: vm.id, name, storage });
      if (operation.kind === 'backup') await action('vm_backup', { vm: vm.id, target, shutdown });
      if (operation.kind === 'restore') await action('vm_snapshot_restore_new', { ...args, snapshot: operation.snapshot!.id });
      if (operation.kind === 'remove') await action('vm_snapshot_remove', { vm: vm.id, snapshot: operation.snapshot!.id });
      toast('VM-Auftrag abgeschlossen.'); setOperation(null); await data.reload(); onChanged();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  if (data.loading) return <Loading />;
  if (!data.data) return <Notice>{data.error}</Notice>;
  return <div className="space-y-4">
    <Notice tone="info">{data.data.snapshot_note || 'Snapshots und Klone ersetzen keine unabhängige Datensicherung.'}</Notice>
    {error && <Notice>{error}</Notice>}
    {operation ? <form className="space-y-3" onSubmit={event => { event.preventDefault(); void submit(); }}>
      <h3 className="font-medium">{titles[operation.kind]}</h3>
      <fieldset disabled={busy} className="space-y-3">
        {['snapshot', 'clone', 'restore'].includes(operation.kind) && <Field label="Name"><Input value={name} onChange={event => setName(event.target.value)} required maxLength={operation.kind === 'snapshot' ? 80 : 96} /></Field>}
        {['clone', 'restore'].includes(operation.kind) && <>
          <Field label="Speicherbereich"><Select value={storage} onChange={event => setStorage(event.target.value)} required>{options.storage.map(item => <option key={item.id} value={item.id} disabled={!item.available}>{item.label} · {bytes(item.free_bytes)} frei</option>)}</Select></Field>
          <Notice tone="info">Titan erstellt unabhängige Laufwerke und eine ausgeschaltete VM mit eigener Kennung und neuen MAC-Adressen. Die ursprüngliche VM bleibt erhalten. Gast-IP und Rechnernamen vor dem ersten Start prüfen.</Notice>
        </>}
        {operation.kind === 'backup' && <>
          <Field label="Unabhängiges Sicherungsziel"><Select value={target} onChange={event => setTarget(event.target.value)} required><option value="">Laufwerk auswählen</option>{locations.data?.items.filter(item => item.available && item.backup_eligible).map(item => <option key={item.path} value={item.path}>{item.label}</option>)}</Select></Field>
          <p className="text-sm text-white/60">Alle verwalteten Laufwerke, VM-Konfiguration und UEFI-Variablen werden gesichert. Die VM bleibt anschließend ausgeschaltet. Das gewählte Ziel gilt danach für alle Titan-Sicherungen.</p>
        </>}
        {operation.kind === 'remove' && <Notice tone="warn">„{operation.snapshot?.name}“ endgültig löschen? Die aktuellen VM-Daten bleiben erhalten.</Notice>}
        {!off && ['snapshot', 'backup', 'restore'].includes(operation.kind) && <label className="flex gap-2 text-sm"><input type="checkbox" checked={shutdown} onChange={event => setShutdown(event.target.checked)} required /> VM geordnet herunterfahren und anschließend fortfahren. Titan wartet höchstens 120 Sekunden und erzwingt kein Ausschalten.</label>}
        <div className="flex gap-2"><Button type="submit" variant={operation.kind === 'remove' ? 'danger' : 'primary'} busy={busy}>{titles[operation.kind]}</Button><Button onClick={() => setOperation(null)}>Abbrechen</Button></div>
      </fieldset>
    </form> : <>
      <div className="flex flex-wrap gap-2"><Button disabled={!possible} onClick={() => start('snapshot')}>Snapshot erstellen</Button><Button disabled={!possible} onClick={() => start('backup')}>Extern sichern</Button><Button disabled={!off} onClick={() => start('clone')}>VM klonen</Button></div>
      {data.data.snapshots.map(snapshot => <Card key={snapshot.id} className="space-y-3"><p className="font-medium">{snapshot.name}</p><p className="text-xs text-white/55">{dateTime(snapshot.created)} · {snapshot.disk_count} Laufwerke</p><div className="flex flex-wrap gap-2"><Button disabled={!possible} onClick={() => start('restore', snapshot)}>Als neue VM wiederherstellen</Button><Button disabled={!off} variant="danger" onClick={() => start('remove', snapshot)}>Löschen</Button></div></Card>)}
      {!data.data.snapshots.length && <p className="text-sm text-white/55">Noch keine Snapshots vorhanden.</p>}
    </>}
  </div>;
}
