import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Settings2 } from 'lucide-react';
import { action } from '../api';
import { message, useApi } from '../lib';
import { Button, Card, Field, Input, Notice, Select, useToast } from '../ui';

type Setting = { key: string; label: string; value: string | number | null; type: string; min?: number | null; max?: number | null; choices?: [string, string][] | null; editable: boolean };
type Details = { installed: boolean; app?: { port: number | null }; settings?: Setting[] };

/**
 * Settings of an installed package that can change later, such as ports or
 * Tailscale routing. Saving rebuilds the stopped containers from the new
 * configuration, so the change is in effect at the next start.
 */
export function AppSettingsCard({ app, running, onSaved }: { app: string; running: boolean; onSaved: () => void }) {
  const toast = useToast();
  const details = useApi<Details>(`/api/package-details?app=${encodeURIComponent(app)}`);
  const [values, setValues] = useState<Record<string, string>>({});
  const [port, setPort] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const settings = (details.data?.settings || []).filter(item => item.editable);
  const loaded = JSON.stringify([details.data?.app?.port, settings.map(item => [item.key, item.value])]);
  useEffect(() => {
    setValues(Object.fromEntries(settings.map(item => [item.key, item.value == null ? '' : String(item.value)])));
    setPort(details.data?.app?.port ? String(details.data.app.port) : '');
  }, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Apps that are not Titan packages have no editable settings.
  if (details.loading || details.error || !details.data?.installed) return null;
  const hasPort = Boolean(details.data.app?.port);
  if (!settings.length && !hasPort) return null;

  const changed = (hasPort && port !== String(details.data.app?.port)) || settings.some(item => (values[item.key] ?? '') !== (item.value == null ? '' : String(item.value)));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const options = Object.fromEntries(settings.map(item => [item.key, item.type === 'number' ? Number(values[item.key]) : values[item.key] ?? '']));
      await action('package_settings', { app, port: hasPort ? Number(port) : 0, options });
      toast('Einstellungen gespeichert. Die Container wurden neu angelegt; die Änderung gilt ab dem nächsten Start.');
      await details.reload();
      onSaved();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Settings2 className="size-4 text-white/50" aria-hidden /> Einstellungen
      </h2>
      <form onSubmit={submit} className="mt-3 space-y-3">
        {running && <Notice tone="info">Zum Ändern die App zuerst stoppen.</Notice>}
        {hasPort && (
          <Field label="Port">
            <Input type="number" min={1024} max={65535} value={port} onChange={event => setPort(event.target.value)} disabled={running || busy} required />
          </Field>
        )}
        {settings.map(item => (
          <Field key={item.key} label={item.label}>
            {item.choices ? (
              <Select value={values[item.key] ?? ''} onChange={event => setValues({ ...values, [item.key]: event.target.value })} disabled={running || busy}>
                {item.choices.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </Select>
            ) : (
              <Input
                type={item.type === 'number' ? 'number' : 'text'}
                min={item.min ?? undefined}
                max={item.max ?? undefined}
                value={values[item.key] ?? ''}
                onChange={event => setValues({ ...values, [item.key]: event.target.value })}
                disabled={running || busy}
                autoComplete="off"
              />
            )}
          </Field>
        ))}
        {error && <Notice>{error}</Notice>}
        <Button type="submit" className="w-full" variant="primary" busy={busy} disabled={running || !changed}>
          Einstellungen speichern
        </Button>
      </form>
    </Card>
  );
}
