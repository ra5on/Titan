import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Archive, HardDriveDownload, RotateCcw, ShieldCheck } from 'lucide-react';
import { action, post } from '../api';
import type { Share } from '../api';
import { bytes, dateTime, message, useApi } from '../lib';
import { Button, Card, Empty, Field, IconButton, Input, Loading, Modal, Notice, Select, useToast } from '../ui';

type Settings = {
  target: string;
  auto_backup: boolean;
  interval: 'daily' | 'weekly';
  window_day: number;
  window_hour: number;
  retention: number;
  shares: string[];
  include_config: boolean;
};
type Backup = { id: string; type: string; created: number; shares?: string[]; include_config?: boolean; bytes?: number; verified?: boolean };
type Backups = { items: Backup[]; settings: Settings };
type Locations = { items: { id: string; label: string; path: string; kind: string; available: boolean; backup_eligible?: boolean; free_bytes?: number }[] };

const DAYS = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];

function Toggle({ label, checked, onChange, help }: { label: string; checked: boolean; onChange: (value: boolean) => void; help?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 py-1.5">
      <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-[var(--color-brand)]" checked={checked} onChange={event => onChange(event.target.checked)} />
      <span>
        <span className="block text-sm">{label}</span>
        {help && <span className="block text-xs leading-relaxed text-white/45">{help}</span>}
      </span>
    </label>
  );
}

function RestoreDialog({ backup, onClose }: { backup: Backup; onClose: () => void }) {
  const toast = useToast();
  const shares = useApi<Share[]>('/api/managed-shares');
  const [share, setShare] = useState('');
  const [name, setName] = useState('wiederhergestellt');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const target = share || shares.data?.[0]?.name;
    if (!target) return;
    setBusy(true);
    setError('');
    try {
      await action('backup_restore', { backup: backup.id, share: target, name });
      toast(`Sicherung nach „${target}/${name}“ wiederhergestellt.`);
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Sicherung wiederherstellen" onClose={onClose}>
      {shares.loading ? (
        <Loading />
      ) : !shares.data?.length ? (
        <Notice tone="info">Zum Wiederherstellen wird eine Freigabe als Ziel benötigt.</Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm leading-relaxed text-white/65">Die Dateien werden in einen neuen Ordner kopiert. Vorhandene Dateien werden nicht überschrieben.</p>
          <Field label="In Freigabe">
            <Select value={share || shares.data[0].name} onChange={event => setShare(event.target.value)}>
              {shares.data.map(item => (
                <option key={item.name} value={item.name}>{item.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Neuer Ordner" help="Kleinbuchstaben, Ziffern, - und _.">
            <Input value={name} onChange={event => setName(event.target.value)} required pattern="[a-z][a-z0-9_\-]{0,30}" autoCapitalize="none" spellCheck={false} />
          </Field>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Wiederherstellen</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function BackupsSection() {
  const toast = useToast();
  const backups = useApi<Backups>('/api/backups');
  const locations = useApi<Locations>('/api/storage-locations');
  const shares = useApi<Share[]>('/api/managed-shares');
  const [form, setForm] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [verifying, setVerifying] = useState('');
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [error, setError] = useState('');

  const loaded = backups.data?.settings;
  useEffect(() => {
    if (loaded && !form) setForm(loaded);
  }, [loaded, form]);

  if (backups.loading || !form) return backups.error ? <Notice>{backups.error}</Notice> : <Loading />;

  const targets = (locations.data?.items || []).filter(item => item.backup_eligible && item.available);
  const known = targets.some(item => item.path === form.target);
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setForm({ ...form, [key]: value });
  const dirty = JSON.stringify(form) !== JSON.stringify({ ...form, ...loaded });

  const save = async (event?: FormEvent) => {
    event?.preventDefault();
    setSaving(true);
    setError('');
    try {
      const saved = await post<Settings>('/api/backup/settings', {
        target: form.target, auto_backup: form.auto_backup, interval: form.interval, window_day: form.window_day,
        window_hour: form.window_hour, retention: form.retention, shares: form.shares, include_config: form.include_config,
      });
      setForm({ ...form, ...saved });
      await backups.reload();
      toast('Sicherungseinstellungen gespeichert.');
      return true;
    } catch (reason) {
      setError(message(reason));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    if (dirty && !(await save())) return;
    setRunning(true);
    try {
      const result = await action('backup_create', {});
      toast(String(result.message || 'Sicherung abgeschlossen.'));
    } catch (reason) {
      toast(message(reason), true);
    } finally {
      setRunning(false);
      await backups.reload();
    }
  };

  const verify = async (backup: Backup) => {
    setVerifying(backup.id);
    try {
      const result = await action('backup_verify', { backup: backup.id });
      toast(String(result.message || 'Sicherung ist vollständig und unverändert.'));
    } catch (reason) {
      toast(message(reason), true);
    } finally {
      setVerifying('');
    }
  };

  const items = backups.data?.items || [];
  return (
    <div className="space-y-4">
      <Card>
        <form onSubmit={save} className="space-y-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <HardDriveDownload className="size-4 text-white/50" aria-hidden /> Ziel und Inhalt
          </h2>
          <Field label="Sicherungsziel" help="Eine andere Platte als die mit den Originaldaten: ein zweiter Speicherbereich oder ein angeschlossenes Laufwerk.">
            <Select value={form.target} onChange={event => set('target', event.target.value)}>
              <option value="">Kein Ziel gewählt</option>
              {!known && form.target && <option value={form.target}>{form.target} (nicht angeschlossen)</option>}
              {targets.map(item => (
                <option key={item.path} value={item.path}>
                  {item.label}{item.free_bytes ? ` · ${bytes(item.free_bytes)} frei` : ''} · {item.path}
                </option>
              ))}
            </Select>
          </Field>
          <fieldset>
            <legend className="mb-1 text-[13px] font-medium text-white/70">Freigaben sichern</legend>
            {(shares.data || []).map(share => (
              <Toggle key={share.name} label={share.name} checked={form.shares.includes(share.name)} onChange={on => set('shares', on ? [...form.shares, share.name] : form.shares.filter(name => name !== share.name))} />
            ))}
            {shares.data?.length === 0 && <p className="text-sm text-white/50">Noch keine Freigabe vorhanden.</p>}
          </fieldset>
          <Toggle label="Titan-Konfiguration mitsichern" help="Benutzer, Freigaben und Einstellungen, damit sich das NAS nach einem Ausfall neu aufsetzen lässt." checked={form.include_config} onChange={on => set('include_config', on)} />

          <h2 className="pt-2 text-sm font-semibold">Zeitplan</h2>
          <Toggle label="Automatisch sichern" checked={form.auto_backup} onChange={on => set('auto_backup', on)} />
          {form.auto_backup && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Rhythmus">
                <Select value={form.interval} onChange={event => set('interval', event.target.value as Settings['interval'])}>
                  <option value="daily">Täglich</option>
                  <option value="weekly">Wöchentlich</option>
                </Select>
              </Field>
              {form.interval === 'weekly' && (
                <Field label="Wochentag">
                  <Select value={form.window_day} onChange={event => set('window_day', Number(event.target.value))}>
                    {DAYS.map((day, index) => (
                      <option key={day} value={index}>{day}</option>
                    ))}
                  </Select>
                </Field>
              )}
              <Field label="Uhrzeit">
                <Select value={form.window_hour} onChange={event => set('window_hour', Number(event.target.value))}>
                  {Array.from({ length: 24 }, (_, hour) => (
                    <option key={hour} value={hour}>{String(hour).padStart(2, '0')}:00</option>
                  ))}
                </Select>
              </Field>
            </div>
          )}
          <Field label="Aufbewahrung" help="So viele Sicherungen bleiben erhalten; ältere werden entfernt.">
            <Input type="number" min={1} max={365} value={form.retention} onChange={event => set('retention', Number(event.target.value))} className="w-32" required />
          </Field>
          {error && <Notice>{error}</Notice>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" busy={saving} disabled={running}>Speichern</Button>
            <Button variant="primary" busy={running} disabled={saving || !form.target} onClick={runNow}>
              <Archive className="size-4" /> Jetzt sichern
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold">Vorhandene Sicherungen</h2>
        {items.length === 0 ? (
          <Empty title="Noch keine Sicherung">Ziel wählen und „Jetzt sichern“ starten.</Empty>
        ) : (
          <ul className="mt-2 divide-y divide-white/6">
            {items.map(backup => (
              <li key={backup.id} className="flex items-center gap-3 py-2.5">
                <Archive className="size-5 shrink-0 text-white/45" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{dateTime(backup.created)}</div>
                  <div className="truncate text-xs text-white/45">
                    {[backup.type === 'vm' ? 'Virtuelle Maschine' : (backup.shares || []).join(', ') || 'Nur Konfiguration', backup.bytes ? bytes(backup.bytes) : null].filter(Boolean).join(' · ')}
                  </div>
                </div>
                <IconButton label={`Sicherung vom ${dateTime(backup.created)} prüfen`} disabled={Boolean(verifying)} onClick={() => verify(backup)}>
                  <ShieldCheck className="size-4" />
                </IconButton>
                {backup.type !== 'vm' && (backup.shares || []).length > 0 && (
                  <IconButton label={`Sicherung vom ${dateTime(backup.created)} wiederherstellen`} onClick={() => setRestoring(backup)}>
                    <RotateCcw className="size-4" />
                  </IconButton>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Button onClick={() => window.open('/classic#backups', '_blank', 'noopener')}>App-Sicherungen und einzelne Dateien wiederherstellen</Button>
      {restoring && <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />}
    </div>
  );
}
