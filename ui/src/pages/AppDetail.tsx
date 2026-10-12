import { useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowLeft, ArrowUpCircle, ExternalLink, Play, RefreshCw, RotateCw, Square, Trash2 } from 'lucide-react';
import { action } from '../api';
import type { InstalledApp } from '../api';
import { go, message, useApi } from '../lib';
import { AppDevicesCard } from './Devices';
import { AppSettingsCard } from './AppSettings';
import { AppIcon, Button, Card, Confirm, Empty, Loading, Notice, Sheet, StateDot, useToast } from '../ui';

type Details = {
  app: InstalledApp;
  container: {
    image: string;
    state: string;
    health: string;
    restarts: number;
    ports: { port: number; target: number; protocol: string }[];
    endpoints: { url: string; scope: string }[];
  } | null;
  logs: string;
  warnings: string[];
  config_path?: string;
  data_path?: string;
};

const STATES: Record<string, string> = { running: 'Läuft', exited: 'Gestoppt', created: 'Angelegt', restarting: 'Startet neu', paused: 'Pausiert', missing: 'Container fehlt' };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-sm">
      <span className="shrink-0 text-white/55">{label}</span>
      <span className="min-w-0 text-right [overflow-wrap:anywhere]">{children}</span>
    </div>
  );
}

export function AppDetail({ appId }: { appId: string }) {
  const toast = useToast();
  const details = useApi<Details>(`/api/app-details?app=${encodeURIComponent(appId)}&tail=200`, 10000);
  const [busy, setBusy] = useState('');
  const [removing, setRemoving] = useState(false);
  const back = (
    <Button variant="ghost" size="sm" onClick={() => go()}>
      <ArrowLeft className="size-4" /> Start
    </Button>
  );

  if (details.loading) return <Sheet title="App" actions={back}><Loading /></Sheet>;
  if (!details.data)
    return (
      <Sheet title="App" actions={back}>
        <Empty title="App nicht gefunden">{details.error}</Empty>
      </Sheet>
    );

  const { app, container, logs, warnings } = details.data;
  const running = app.state === 'running';
  const lan = container?.endpoints.find(item => item.scope === 'lan')?.url;
  const url = app.port ? `${app.scheme || 'http'}://${window.location.hostname}:${app.port}` : null;

  const run = async (command: 'start' | 'stop' | 'restart' | 'update' | 'remove', done: string) => {
    setBusy(command);
    try {
      await action('app_action', { app: app.id, action: command });
      toast(`${app.name}: ${done}`);
      if (command === 'remove') return go();
    } catch (reason) {
      toast(`${app.name}: ${message(reason)}`, true);
    } finally {
      setBusy('');
    }
    await details.reload();
  };

  return (
    <Sheet title={app.name} subtitle="Installierte App" actions={back}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-4">
            <AppIcon id={app.id} name={app.name} size={84} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm text-white/70">
                <StateDot state={busy ? 'restarting' : app.state} /> {STATES[app.state] || app.state}
                {app.status && <span className="text-white/40">· {app.status}</span>}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {running && (url || app.id === 'titan-tailscale') && (
                  <Button variant="primary" onClick={() => go('open', app.id)}>
                    <ExternalLink className="size-4" /> Öffnen
                  </Button>
                )}
                {running ? (
                  <>
                    <Button busy={busy === 'restart'} disabled={Boolean(busy)} onClick={() => run('restart', 'neu gestartet.')}>
                      <RotateCw className="size-4" /> Neu starten
                    </Button>
                    <Button busy={busy === 'stop'} disabled={Boolean(busy)} onClick={() => run('stop', 'gestoppt.')}>
                      <Square className="size-4" /> Stoppen
                    </Button>
                  </>
                ) : (
                  <Button variant="primary" busy={busy === 'start'} disabled={Boolean(busy)} onClick={() => run('start', 'gestartet.')}>
                    <Play className="size-4" /> Starten
                  </Button>
                )}
              </div>
            </div>
          </div>
          {warnings.map(text => (
            <Notice key={text} tone="warn">{text}</Notice>
          ))}
          <Card>
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">Protokoll</h2>
              <Button size="sm" variant="ghost" onClick={() => details.reload()}>
                <RefreshCw className="size-4" /> Aktualisieren
              </Button>
            </div>
            <pre className="scroll-area mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-black/35 p-3.5 font-mono text-xs leading-relaxed text-white/75" tabIndex={0} aria-label="Protokoll der App">
              {logs || 'Noch keine Ausgabe.'}
            </pre>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <h2 className="text-sm font-semibold">Details</h2>
            <div className="mt-2 divide-y divide-white/6">
              {lan && <Row label="Adresse">{lan}</Row>}
              {container && <Row label="Image">{container.image}</Row>}
              {container && container.ports.length > 0 && <Row label="Ports">{container.ports.map(item => `${item.port}/${item.protocol}`).join(', ')}</Row>}
              {container && container.restarts > 0 && <Row label="Neustarts">{container.restarts}</Row>}
              {details.data.data_path && <Row label="Daten">{details.data.data_path}</Row>}
            </div>
          </Card>
          <AppSettingsCard app={app.id} running={running} onSaved={details.reload} />
          <AppDevicesCard app={app.id} assigned={(app.hardware || []).map(item => item.id)} running={running} onSaved={details.reload} />
          <Card className="space-y-3">
            <h2 className="text-sm font-semibold">Wartung</h2>
            <Button className="w-full" busy={busy === 'update'} disabled={Boolean(busy)} onClick={() => run('update', 'aktualisiert.')}>
              <ArrowUpCircle className="size-4" /> Aktualisieren
            </Button>
            <Button variant="danger" className="w-full" disabled={Boolean(busy)} onClick={() => setRemoving(true)}>
              <Trash2 className="size-4" /> Deinstallieren
            </Button>
          </Card>
        </div>
      </div>
      {removing && (
        <Confirm
          title={`${app.name} deinstallieren?`}
          text="Die Container werden entfernt. Konfiguration und Nutzdaten der App bleiben auf dem NAS erhalten."
          confirmLabel="Deinstallieren"
          danger
          onClose={() => setRemoving(false)}
          onConfirm={() => run('remove', 'deinstalliert.')}
        />
      )}
    </Sheet>
  );
}
