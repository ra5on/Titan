import { useState } from 'react';
import type { FormEvent } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { action } from '../api';
import type { Share } from '../api';
import { cx, dateTime, message, useApi } from '../lib';
import { Button, Card, Field, IconButton, Loading, Modal, Notice, Select, useToast } from '../ui';

export type Target = { label: string; path: string };
type Job = {
  share: string; target: string; destination: string; interval_minutes: number; delete: boolean; enabled: boolean;
  last_run: number | null; last_ok: boolean | null; last_message: string; running: boolean;
};

const INTERVALS: [number, string][] = [[1, 'Jede Minute'], [5, 'Alle 5 Minuten'], [15, 'Alle 15 Minuten'], [60, 'Stündlich'], [1440, 'Täglich']];

function JobDialog({ shares, targets, taken, onClose, onSaved }: { shares: Share[]; targets: Target[]; taken: string[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const free = shares.filter(share => !taken.includes(share.name));
  const [share, setShare] = useState(free[0]?.name || '');
  const [target, setTarget] = useState(targets[0]?.path || '');
  const [interval, setInterval] = useState(5);
  const [remove, setRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await action('sync_job_save', { share, target, interval_minutes: interval, delete: remove, enabled: true });
      toast(`Abgleich für „${share}“ eingerichtet.`);
      onSaved();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Laufenden Abgleich einrichten" onClose={onClose}>
      {!free.length ? (
        <Notice tone="info">Für jede Freigabe ist bereits ein Abgleich eingerichtet.</Notice>
      ) : !targets.length ? (
        <Notice tone="info">Es ist keine zweite Platte als Ziel verfügbar. Schließe ein Laufwerk an oder lege einen weiteren Speicherbereich an.</Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Freigabe">
            <Select value={share} onChange={event => setShare(event.target.value)}>
              {free.map(item => (
                <option key={item.name} value={item.name}>{item.label || item.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Ziel" help="Die Kopie liegt dort im Ordner titan-sync.">
            <Select value={target} onChange={event => setTarget(event.target.value)}>
              {targets.map(item => (
                <option key={item.path} value={item.path}>{item.label} · {item.path}</option>
              ))}
            </Select>
          </Field>
          <Field label="Rhythmus">
            <Select value={interval} onChange={event => setInterval(Number(event.target.value))}>
              {INTERVALS.map(([minutes, label]) => (
                <option key={minutes} value={minutes}>{label}</option>
              ))}
            </Select>
          </Field>
          <label className="flex cursor-pointer items-start gap-3">
            <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-[var(--color-brand)]" checked={remove} onChange={event => setRemove(event.target.checked)} />
            <span>
              <span className="block text-sm">Gelöschte Dateien auch im Ziel löschen</span>
              <span className="block text-xs leading-relaxed text-white/45">Aus: versehentlich Gelöschtes bleibt im Ziel erhalten. An: das Ziel ist eine exakte Kopie.</span>
            </span>
          </label>
          <Notice tone="info">Ein Abgleich ersetzt keine Sicherung: geänderte oder beschädigte Dateien überschreiben beim nächsten Lauf die Kopie.</Notice>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Einrichten</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function SyncCard({ shares, targets }: { shares: Share[]; targets: Target[] }) {
  const toast = useToast();
  const jobs = useApi<{ jobs: Job[] }>('/api/sync-jobs', 15000);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState('');

  const run = async (operation: 'sync_job_run' | 'sync_job_remove', job: Job, done: (result: Record<string, unknown>) => string) => {
    setBusy(job.share);
    try {
      toast(done(await action(operation, { share: job.share })));
    } catch (reason) {
      toast(message(reason), true);
    } finally {
      setBusy('');
      await jobs.reload();
    }
  };

  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <RefreshCw className="size-4 text-white/50" aria-hidden /> Laufender Abgleich
          </h2>
          <p className="mt-0.5 text-sm text-white/50">Beta · Hält eine Freigabe laufend als Kopie auf einer zweiten Platte.</p>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>Einrichten</Button>
      </div>
      {jobs.loading ? (
        <Loading />
      ) : (
        <ul className="mt-2 divide-y divide-white/6">
          {(jobs.data?.jobs || []).map(job => (
            <li key={job.share} className="flex items-center gap-3 py-2.5">
              <span className={cx('size-2 shrink-0 rounded-full', job.last_ok === false ? 'bg-bad' : job.last_run ? 'bg-ok' : 'bg-white/30')} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{job.share} → {job.destination}</div>
                <div className="truncate text-xs text-white/45">
                  {INTERVALS.find(([minutes]) => minutes === job.interval_minutes)?.[1] || `Alle ${job.interval_minutes} Minuten`}
                  {job.last_run ? ` · zuletzt ${dateTime(job.last_run)}${job.last_message ? `: ${job.last_message}` : ''}` : ' · noch nicht gelaufen'}
                </div>
              </div>
              <IconButton label={`Abgleich für ${job.share} jetzt starten`} disabled={Boolean(busy) || job.running} onClick={() => run('sync_job_run', job, result => String(result.message || 'Abgleich abgeschlossen.'))}>
                <RefreshCw className={cx('size-4', (busy === job.share || job.running) && 'animate-spin')} />
              </IconButton>
              <IconButton label={`Abgleich für ${job.share} entfernen`} disabled={Boolean(busy)} onClick={() => run('sync_job_remove', job, () => 'Abgleich entfernt. Die Kopie im Ziel bleibt erhalten.')}>
                <Trash2 className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      {adding && <JobDialog shares={shares} targets={targets} taken={(jobs.data?.jobs || []).map(job => job.share)} onClose={() => setAdding(false)} onSaved={jobs.reload} />}
    </Card>
  );
}
