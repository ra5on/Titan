import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Globe } from 'lucide-react';
import { post } from '../api';
import { go, message, useApi } from '../lib';
import { forgetRemoteAccess } from '../system';
import { Button, Card, Field, Input, Loading, Notice, Select, useToast } from '../ui';

type Remote = { enabled: boolean; public_origin: string; connector: string; app_urls: Record<string, string>; service_url?: string };
type Diagnosis = { connected: boolean; message: string; checks: { name: string; ok: boolean | null; message: string }[] };
type Overview = {
  remote: Remote;
  revision: string;
  connectors: { id: string; name: string }[];
  apps: { id: string; name: string }[];
  demo?: boolean;
  diagnosis?: Diagnosis;
};

/**
 * Access from outside the home network through a Cloudflare Tunnel: one public
 * address for Titan and, per app, the public address that opens it. With an
 * app address set, the app also opens inside the Titan window from outside.
 */
export function RemoteSection() {
  const toast = useToast();
  const overview = useApi<Overview>('/api/remote-access');
  const [form, setForm] = useState<Remote | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);

  const revision = overview.data?.revision;
  useEffect(() => {
    if (overview.data) setForm({ enabled: overview.data.remote.enabled, public_origin: overview.data.remote.public_origin, connector: overview.data.remote.connector, app_urls: { ...overview.data.remote.app_urls } });
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  if (overview.loading || !form || !overview.data) return overview.error ? <Notice>{overview.error}</Notice> : <Loading />;
  const data = overview.data;
  const apps = data.apps.filter(app => !data.connectors.some(connector => connector.id === app.id));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const app_urls = Object.fromEntries(Object.entries(form.app_urls).map(([id, address]) => [id, address.trim()]).filter(([, address]) => address));
      await post('/api/remote-access', {
        enabled: form.enabled,
        public_origin: form.public_origin.trim(),
        connector: form.connector || data.connectors[0]?.id || '',
        app_urls,
        expected_revision: data.revision,
      });
      forgetRemoteAccess();
      setDiagnosis(null);
      toast('Fernzugriff gespeichert.');
      await overview.reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {data.connectors.length === 0 && (
        <Notice tone="info">
          Für den Fernzugriff kannst du das Plugin „Cloudflare Tunnel“ installieren.{' '}
          <button type="button" className="underline underline-offset-4" onClick={() => go('store', 'plugin-cloudflare')}>
            Im App Store öffnen
          </button>
        </Notice>
      )}
      <Card className="space-y-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Globe className="size-4 text-white/50" aria-hidden /> Titan von unterwegs
        </h2>
        <label className="flex cursor-pointer items-center gap-3 text-sm">
          <input type="checkbox" className="size-4 accent-[var(--color-brand)]" checked={form.enabled} onChange={event => setForm({ ...form, enabled: event.target.checked })} />
          Fernzugriff über den Tunnel einschalten
        </label>
        <Field label="Öffentliche Adresse von Titan" help="Die HTTPS-Adresse, die du in Cloudflare auf dieses NAS zeigen lässt, zum Beispiel https://nas.example.org.">
          <Input type="url" value={form.public_origin} onChange={event => setForm({ ...form, public_origin: event.target.value })} placeholder="https://" autoComplete="off" required={form.enabled} />
        </Field>
        {data.connectors.length > 1 && (
          <Field label="Tunnel">
            <Select value={form.connector || data.connectors[0].id} onChange={event => setForm({ ...form, connector: event.target.value })}>
              {data.connectors.map(connector => (
                <option key={connector.id} value={connector.id}>{connector.name}</option>
              ))}
            </Select>
          </Field>
        )}
      </Card>
      {data.remote.enabled && data.remote.service_url && <Card className="space-y-3">
        <h2 className="text-sm font-semibold">Zieladresse für Cloudflare</h2>
        <p className="text-sm text-white/65">In der öffentlichen Route von Cloudflare den Service-Typ <strong>HTTP</strong> wählen und diese Zieladresse verwenden. Deine öffentliche Titan-Adresse bleibt HTTPS.</p>
        <Input aria-label="Tunnel-Zieladresse" readOnly value={data.remote.service_url} onFocus={event => event.target.select()} />
        <p className="text-xs text-white/50">Keinen HTTP-Host-Header mit der internen NAS-IP erzwingen. Titan prüft hier den öffentlichen Domainnamen.</p>
      </Card>}
      <Card className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold">Apps von unterwegs</h2>
          <p className="mt-0.5 text-sm leading-relaxed text-white/50">
            Lege in Cloudflare pro App eine eigene Adresse an und trage sie hier ein. Die App öffnet dann auch von außen im Titan-Fenster. Schütze diese Adressen in Cloudflare mit einer Anmeldung.
          </p>
        </div>
        {apps.length === 0 ? (
          <p className="text-sm text-white/55">Noch keine App installiert.</p>
        ) : (
          apps.map(app => (
            <Field key={app.id} label={app.name}>
              <Input
                type="url"
                aria-label={`Öffentliche Adresse von ${app.name}`}
                value={form.app_urls[app.id] || ''}
                onChange={event => setForm({ ...form, app_urls: { ...form.app_urls, [app.id]: event.target.value } })}
                placeholder="https://"
                autoComplete="off"
              />
            </Field>
          ))
        )}
      </Card>
      {error && <Notice>{error}</Notice>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" busy={busy}>Speichern</Button>
        <Button busy={checking} disabled={busy || !data.remote.enabled || data.demo} onClick={async () => {
          setChecking(true);
          setError('');
          try { setDiagnosis(await post<Diagnosis>('/api/remote-access/diagnose', {})); }
          catch (reason) { setError(message(reason)); }
          finally { setChecking(false); }
        }}>Verbindung prüfen</Button>
      </div>
      {(diagnosis || data.diagnosis)?.checks?.map(check => <Notice key={check.name} tone={check.ok ? 'info' : 'warn'}><strong>{check.name}:</strong> {check.message}</Notice>)}
    </form>
  );
}
