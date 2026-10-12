import { useState } from 'react';
import { ArrowLeft, Cloud, Cpu, Download, PackageCheck, RefreshCw, Trash2 } from 'lucide-react';
import { action } from '../api';
import { dateTime, go, message, useApi } from '../lib';
import { Button, Card, Field, Input, Loading, Modal, Notice, Sheet } from '../ui';

export type Plugin = {
  id: string; name: string; description: string; installed: boolean; running: boolean; beta?: boolean;
  version: string | null; latest: string | null; update_available: boolean; checked_at?: number;
  public_origin?: string; service_url?: string; connected?: boolean; docker_installed?: boolean;
  card?: boolean; passthrough?: boolean;
};
type Inventory = { revision: string; items: Plugin[]; demo?: boolean };

export function PluginTiles({ query = '' }: { query?: string }) {
  const data = useApi<Inventory>('/api/plugins');
  const items = data.data?.items.filter(item => `${item.name} ${item.description}`.toLocaleLowerCase('de').includes(query.toLocaleLowerCase('de'))) || [];
  return <section className="space-y-3" aria-label="Systemplugins">
    <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Plugins</h2><Button size="sm" variant="ghost" onClick={() => go('store', 'plugins')}>Alle Plugins</Button></div>
    <p className="text-sm text-white/55">Optionale Dienste und Treiber. Titan lädt sie erst bei der Installation; Updates und Deinstallation verwaltest du hier.</p>
    {data.error && <Notice>{data.error}</Notice>}
    {data.loading && <Loading />}
    <div className="grid gap-3 sm:grid-cols-2">{items.map(item => <button type="button" key={item.id} className="glass-soft flex items-center gap-4 rounded-2xl p-4 text-left hover:bg-white/10" onClick={() => go('store', 'plugin-' + item.id)}>
      <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-sky-400/15">{item.id === 'cloudflare' ? <Cloud className="size-7 text-sky-300" /> : <Cpu className="size-7 text-emerald-300" />}</span>
      <span><span className="font-semibold">{item.name}</span><span className="ml-2 text-xs text-white/50">Plugin{item.beta ? ' · Beta' : ''}{item.installed ? ' · Installiert' : ''}</span><span className="mt-1 block text-sm text-white/55">{item.description}</span></span>
    </button>)}</div>
  </section>;
}

export function PluginStore({ pluginId, admin }: { pluginId?: string; admin: boolean }) {
  const data = useApi<Inventory>(admin ? '/api/plugins' : null, 15000);
  const [operation, setOperation] = useState<'install' | 'update' | 'remove' | 'stop' | null>(null);
  const [token, setToken] = useState('');
  const [origin, setOrigin] = useState('');
  const [license, setLicense] = useState(false);
  const [replaceDocker, setReplaceDocker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState('');
  const [reviewRevision, setReviewRevision] = useState('');
  const item = data.data?.items.find(item => item.id === pluginId);
  const run = async (verb: string) => {
    if (!data.data || !item || busy) return;
    setBusy(true); setError(''); setResult('');
    try {
      const installing = ['install', 'update'].includes(verb);
      const result = await action('plugin_action', { plugin: item.id, action: verb, expected_revision: operation ? reviewRevision : data.data.revision,
        ...(verb === 'remove' ? { confirmation: item.id } : {}),
        ...(installing ? { options: item.id === 'cloudflare' ? { ...(token ? { token } : {}), public_origin: origin || item.public_origin || '', replace_docker: replaceDocker } : { accept_license: license } } : {}),
      });
      setResult(String(result.message || 'Plugin-Aktion abgeschlossen.')); setOperation(null); setToken('');
      await data.reload();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const open = (verb: 'install' | 'update' | 'remove' | 'stop') => {
    setReviewRevision(data.data?.revision || '');
    setOperation(verb); setToken(''); setOrigin(item?.public_origin || ''); setLicense(false); setReplaceDocker(false); setError('');
  };
  const close = () => { if (!busy) { setOperation(null); setToken(''); } };
  const titles = { install: item?.installed ? 'Cloudflare-Einstellungen ändern' : 'Plugin installieren', update: 'Plugin aktualisieren', remove: 'Plugin deinstallieren', stop: 'Dienst stoppen' };
  return <Sheet title={item?.name || 'Plugins'} subtitle="Optionale Erweiterungen für dein Titan-System" actions={<Button size="sm" onClick={() => go('store')}><ArrowLeft className="size-4" /> App Store</Button>}>
    {!admin ? <Notice tone="info">Plugins werden von einem Administrator verwaltet.</Notice> : !pluginId ? <PluginTiles /> : data.loading ? <Loading /> : !item ? <Notice>{data.error || 'Plugin nicht gefunden.'}</Notice> : <div className="mx-auto max-w-3xl space-y-4">
      {data.data?.demo && <Notice tone="info">Demo: Plugin-Aktionen werden simuliert. Es werden keine Pakete oder Dienste auf dem Host verändert.</Notice>}
      {data.error && <Notice>{data.error}</Notice>}
      <Card className="space-y-4">
        <div className="flex items-center gap-3"><PackageCheck className="size-8 text-brand" /><div><h2 className="font-semibold">{item.installed ? 'Installiert' : 'Verfügbar zur Installation'}{item.beta && <span className="ml-2 rounded-full bg-warn/15 px-2 py-0.5 text-xs text-warn">Beta</span>}</h2><p className="text-sm text-white/55">{item.description}</p></div></div>
        {item.beta && <p className="text-sm text-white/55">Dieses optionale Plugin ist noch nicht umfassend auf physischer Hardware erprobt.</p>}
        <dl className="grid grid-cols-2 gap-2 text-sm"><dt className="text-white/50">Installierte Version</dt><dd>{item.version || '–'}</dd><dt className="text-white/50">Verfügbare Version</dt><dd>{item.latest || 'Nach Updateprüfung bekannt'}</dd><dt className="text-white/50">Status</dt><dd>{!item.installed ? 'Nicht installiert' : item.running ? 'Aktiv' : 'Gestoppt / nicht bereit'}</dd>{item.checked_at && <><dt className="text-white/50">Letzte Prüfung</dt><dd>{dateTime(item.checked_at)}</dd></>}</dl>
        {item.id === 'nvidia' && <p className="text-sm text-white/65">Der proprietäre NVIDIA-Treiber wird aus dem offiziellen Paketarchiv geladen und für den laufenden Kernel gebaut. Er gehört nicht zum Basisimage. Nach Systemupdates wird er für den neuen Kernel erneut eingerichtet. GPU-Apps vor Update oder Deinstallation stoppen.</p>}
        {item.id === 'nvidia' && item.passthrough && <Notice tone="warn">Eine NVIDIA-Karte ist an eine VM durchgereicht. Für diese Karte wird der Treiber im Gast benötigt.</Notice>}
        {item.id === 'cloudflare' && <div className="space-y-3">
          <p className="text-sm text-white/65">Cloudflare läuft als eigener Debian-Dienst. Ein Docker-Container wird dafür nicht benötigt. Token und Installation bleiben bei Titan-Systemupdates erhalten.</p>
          <Notice tone="info"><strong>Cloudflare-Ziel: Typ HTTP · URL 127.0.0.1:5102</strong><span className="mt-1 block">Die öffentliche Titan-Adresse bleibt HTTPS. Eine NAS-IP mit HTTPS spricht einen anderen Zugang an und kann eine leere Seite liefern. Diese Route im Cloudflare-Konto eintragen.</span></Notice>
          {item.installed && <p className="text-sm">Verbindung zu Cloudflare: {item.connected ? 'Bestätigt' : 'Nicht bestätigt'}. <button type="button" className="text-brand underline" onClick={() => go('settings', 'remote')}>Öffentlichen Titan-Zugang prüfen</button></p>}
        </div>}
        <div className="flex flex-wrap gap-2">
          <Button busy={busy} onClick={() => run('check')}><RefreshCw className="size-4" /> Nach Updates suchen</Button>
          {!item.installed && <Button variant="primary" disabled={busy || item.id === 'nvidia' && item.card === false} onClick={() => open('install')}><Download className="size-4" /> Installieren</Button>}
          {item.installed && <>
            <Button variant="primary" disabled={busy} onClick={() => open('update')}>Aktualisieren</Button>
            {item.id === 'cloudflare' && <><Button disabled={busy} onClick={() => open('install')}>Token und Adresse ändern</Button><Button disabled={busy} onClick={() => item.running ? open('stop') : void run('start')}>{item.running ? 'Stoppen' : 'Starten'}</Button></>}
            <Button variant="danger" disabled={busy} onClick={() => open('remove')}><Trash2 className="size-4" /> Deinstallieren</Button>
          </>}
        </div>
        {busy && <p role="status" className="text-sm text-white/65">Auftrag läuft. Installationen und Treiberbau können mehrere Minuten dauern. Der Verlauf bleibt unter Einstellungen → Aktivität sichtbar.</p>}
      </Card>
      {result && <Notice tone="info">{result}</Notice>}
      {error && !operation && <Notice>{error}</Notice>}
    </div>}
    {operation && item && <Modal title={titles[operation]} onClose={close}>
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); void run(operation); }}>
        <fieldset disabled={busy} className="space-y-4">
          {['install', 'update'].includes(operation) ? item.id === 'cloudflare' ? <>
            <Notice tone="info"><strong>Im Cloudflare-Konto eintragen</strong><span className="mt-1 block">Service-Typ: <strong>HTTP</strong> · URL: <strong>127.0.0.1:5102</strong></span><span className="mt-1 block">Das ist das lokale Ziel des Tunnels. Unten gehört deine öffentliche Adresse mit https:// hinein.</span></Notice>
            <Field label="Tunnel-Token" help={item.installed ? 'Leer lassen, um den gespeicherten Token zu behalten.' : 'Den Token (eyJ…) aus Cloudflare einfügen, keinen Installationsbefehl.'}><Input type="password" autoComplete="new-password" value={token} onChange={event => setToken(event.target.value)} required={!item.installed} /></Field>
            <Field label="Öffentliche Titan-Adresse"><Input type="url" placeholder="https://titan.example.com" value={origin} onChange={event => setOrigin(event.target.value)} required /></Field>
            {item.docker_installed && !item.installed && <label className="flex gap-2 text-sm"><input type="checkbox" required checked={replaceDocker} onChange={event => setReplaceDocker(event.target.checked)} /> Den bisherigen Titan-Docker-Tunnel nach erfolgreicher Verbindung stoppen. Bei einem Fehler wird der bisherige Zustand wiederhergestellt.</label>}
          </> : <>
            <Notice tone="warn">Zum Abschluss startet Docker neu; laufende Apps sind kurz unterbrochen. Für den Treiberbau müssen Kernel-Header vorhanden sein und mindestens 4 GB im Systembereich frei sein.</Notice>
            <label className="flex gap-2 text-sm"><input type="checkbox" required checked={license} onChange={event => setLicense(event.target.checked)} /> Ich akzeptiere die <a className="text-brand underline" href="https://www.nvidia.com/en-us/drivers/nvidia-license/" target="_blank" rel="noreferrer">NVIDIA-Lizenzbedingungen</a>.</label>
          </> : <Notice tone="warn">{item.id === 'cloudflare' ? 'Der Fernzugriff über diesen Dienst endet. Öffne Titan über die lokale Adresse, bevor du fortfährst.' : 'GPU-Beschleunigung für Apps ist danach nicht verfügbar. Laufende GPU-Apps zuerst stoppen; Docker wird neu gestartet.'}{operation === 'remove' && item.id === 'cloudflare' && ' Der lokale Token wird gelöscht. Der Tunnel im Cloudflare-Konto bleibt erhalten.'}</Notice>}
          {error && <Notice>{error}</Notice>}
          {busy && item.id === 'cloudflare' && ['install', 'update'].includes(operation) && <p role="status" className="text-sm text-white/65">Cloudflare wird eingerichtet. Nach dem Download kann der Verbindungsaufbau bis zu drei Minuten dauern. Titan wartet dabei auch auf den automatischen Wechsel von UDP auf TCP.</p>}
          <div className="flex justify-end gap-2"><Button onClick={close}>Abbrechen</Button><Button type="submit" variant={operation === 'remove' ? 'danger' : 'primary'} busy={busy}>{operation === 'install' ? item.installed ? 'Speichern' : 'Installieren' : operation === 'update' ? 'Aktualisieren' : operation === 'remove' ? 'Deinstallieren' : 'Stoppen'}</Button></div>
        </fieldset>
      </form>
    </Modal>}
  </Sheet>;
}
