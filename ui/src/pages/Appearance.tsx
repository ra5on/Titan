import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, X } from 'lucide-react';
import type { InstalledApp, Session, VmList } from '../api';
import { message, useApi } from '../lib';
import { DEFAULT_PREFS, applyTransparency, usePrefs } from '../prefs';
import type { Prefs } from '../prefs';
import { Button, Field, IconButton, Modal, Notice, Select, useToast } from '../ui';

export const TOOL_LABELS: Record<string, string> = {
  'tool:home': 'Start', 'tool:store': 'App Store', 'tool:files': 'Dateien', 'tool:vms': 'Virtuelle Maschinen', 'tool:settings': 'Einstellungen',
};
const WIDGETS: [Prefs['widgets'][number], string][] = [['cpu', 'Prozessor'], ['ram', 'Arbeitsspeicher'], ['storage', 'Speicher']];
const SIZES: [Prefs['dock_size'], string][] = [['small', 'Klein'], ['medium', 'Mittel'], ['large', 'Groß']];

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-3 py-1.5 text-sm">
      <input type="checkbox" className="size-4 accent-[var(--color-brand)]" checked={checked} onChange={event => onChange(event.target.checked)} />
      <span className="min-w-0 truncate">{label}</span>
    </label>
  );
}

/** Transparency, dock and start page of the signed-in account. */
export function AppearanceDialog({ session, onClose }: { session: Session; onClose: () => void }) {
  const toast = useToast();
  const { prefs, save } = usePrefs();
  const canApps = Boolean(session.permissions.apps?.allowed);
  const canVms = Boolean(session.permissions.vms?.allowed);
  const apps = useApi<{ installed: InstalledApp[] }>(canApps ? '/api/apps' : null);
  const vms = useApi<VmList>(canVms ? '/api/vms' : null);
  const [draft, setDraft] = useState<Prefs>(prefs);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Show the transparency while the slider moves; restore the saved value on cancel.
  useEffect(() => {
    applyTransparency(draft.transparency);
    return () => applyTransparency(prefs.transparency);
  }, [draft.transparency, prefs.transparency]);

  const installed = apps.data?.installed || [];
  const machines = vms.data?.vms || [];
  const label = (entry: string) =>
    TOOL_LABELS[entry] ||
    (entry.startsWith('app:') ? installed.find(app => app.id === entry.slice(4))?.name || entry.slice(4) : machines.find(vm => vm.id === entry.slice(3))?.display_name || machines.find(vm => vm.id === entry.slice(3))?.name || 'Virtuelle Maschine');
  const candidates = [...Object.keys(TOOL_LABELS), ...installed.map(app => 'app:' + app.id), ...machines.map(vm => 'vm:' + vm.id)].filter(entry => !draft.dock.includes(entry));

  const move = (index: number, offset: number) => {
    const dock = [...draft.dock];
    [dock[index], dock[index + offset]] = [dock[index + offset], dock[index]];
    setDraft({ ...draft, dock });
  };
  const toggle = <K extends 'widgets' | 'hidden_apps' | 'pinned_vms'>(key: K, value: string, on: boolean) =>
    setDraft({ ...draft, [key]: on ? [...draft[key], value] : (draft[key] as string[]).filter(item => item !== value) } as Prefs);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await save(draft);
      toast('Darstellung gespeichert.');
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Darstellung" onClose={onClose} wide>
      <div className="space-y-6">
        <Field label={`Transparenz · ${draft.transparency} %`} help="Wie stark der Hintergrund durch Fenster, Kacheln und Dock scheint.">
          <input type="range" min={0} max={100} step={5} value={draft.transparency} onChange={event => setDraft({ ...draft, transparency: Number(event.target.value) })} className="w-full accent-[var(--color-brand)]" />
        </Field>

        <section>
          <h3 className="mb-2 text-sm font-semibold">Dock</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Größe">
              <Select value={draft.dock_size} onChange={event => setDraft({ ...draft, dock_size: event.target.value as Prefs['dock_size'] })}>
                {SIZES.map(([id, text]) => (
                  <option key={id} value={id}>{text}</option>
                ))}
              </Select>
            </Field>
            <Field label="Hinzufügen">
              <Select value="" onChange={event => event.target.value && setDraft({ ...draft, dock: [...draft.dock, event.target.value] })} disabled={!candidates.length || draft.dock.length >= 16}>
                <option value="">{candidates.length ? 'App, VM oder Werkzeug wählen' : 'Alles ist bereits im Dock'}</option>
                {candidates.map(entry => (
                  <option key={entry} value={entry}>{label(entry)}</option>
                ))}
              </Select>
            </Field>
          </div>
          <ul className="mt-3 divide-y divide-white/6 rounded-xl border border-white/10">
            {draft.dock.map((entry, index) => (
              <li key={entry} className="flex items-center gap-1 py-1 pl-3.5 pr-1.5">
                <span className="min-w-0 flex-1 truncate text-sm">{label(entry)}</span>
                <IconButton label={`${label(entry)} nach oben`} disabled={index === 0} onClick={() => move(index, -1)}>
                  <ArrowUp className="size-4" />
                </IconButton>
                <IconButton label={`${label(entry)} nach unten`} disabled={index === draft.dock.length - 1} onClick={() => move(index, 1)}>
                  <ArrowDown className="size-4" />
                </IconButton>
                <IconButton label={`${label(entry)} aus dem Dock entfernen`} disabled={entry === 'tool:settings'} onClick={() => setDraft({ ...draft, dock: draft.dock.filter(item => item !== entry) })}>
                  <X className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className="mb-1 text-sm font-semibold">Startseite</h3>
          <div className="grid gap-x-6 sm:grid-cols-3">
            <fieldset>
              <legend className="py-1 text-xs font-medium uppercase tracking-wider text-white/40">Kacheln</legend>
              {WIDGETS.map(([id, text]) => (
                <Toggle key={id} label={text} checked={draft.widgets.includes(id)} onChange={on => toggle('widgets', id, on)} />
              ))}
            </fieldset>
            {installed.length > 0 && (
              <fieldset>
                <legend className="py-1 text-xs font-medium uppercase tracking-wider text-white/40">Apps</legend>
                {installed.map(app => (
                  <Toggle key={app.id} label={app.name} checked={!draft.hidden_apps.includes(app.id)} onChange={on => toggle('hidden_apps', app.id, !on)} />
                ))}
              </fieldset>
            )}
            {machines.length > 0 && (
              <fieldset>
                <legend className="py-1 text-xs font-medium uppercase tracking-wider text-white/40">Virtuelle Maschinen</legend>
                {machines.map(vm => (
                  <Toggle key={vm.id} label={vm.display_name || vm.name} checked={draft.pinned_vms.includes(vm.id)} onChange={on => toggle('pinned_vms', vm.id, on)} />
                ))}
              </fieldset>
            )}
          </div>
        </section>

        {error && <Notice>{error}</Notice>}
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" onClick={() => setDraft(DEFAULT_PREFS)}>Zurücksetzen</Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button variant="primary" busy={busy} onClick={submit}>Speichern</Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
