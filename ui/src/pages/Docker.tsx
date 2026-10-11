import { useState } from 'react';
import { FileText, Play, RotateCw, Square } from 'lucide-react';
import { action } from '../api';
import { bytes, cx, go, message, useApi } from '../lib';
import { Button, Card, Empty, IconButton, Loading, Modal, Notice, StateDot, useToast } from '../ui';

type Container = {
  id: string; name: string; image: string; state: string; health: string | null; project?: string | null;
  managed_app?: string | null; ports?: Record<string, { HostIp: string; HostPort: string }[] | null>;
};
type Engine = {
  available: boolean; error?: string; containers: Container[];
  images: { ID: string; Repository: string; Tag: string; Size: string; CreatedSince?: string }[];
  volumes: { Name: string; Driver: string }[];
  networks: { Name: string; Driver: string; Scope?: string }[];
};
type Metrics = { containers: Record<string, { cpu_percent: number; memory_bytes: number }> };
type Details = { container: Container; logs: string };

const TABS = [['containers', 'Container'], ['images', 'Images'], ['volumes', 'Volumes'], ['networks', 'Netzwerke']] as const;
type Tab = (typeof TABS)[number][0];

const published = (container: Container) =>
  Object.entries(container.ports || {})
    .flatMap(([target, bindings]) => (bindings || []).map(binding => `${binding.HostPort}→${target}`))
    .join(', ');

function LogDialog({ container, onClose }: { container: Container; onClose: () => void }) {
  const details = useApi<Details>(`/api/docker-container?container=${encodeURIComponent(container.id)}`);
  return (
    <Modal title={`Protokoll · ${container.name}`} onClose={onClose} wide>
      {details.loading ? (
        <Loading />
      ) : details.error || !details.data ? (
        <Notice>{details.error || 'Protokoll nicht verfügbar.'}</Notice>
      ) : (
        <pre className="scroll-area max-h-[60dvh] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-black/35 p-3.5 font-mono text-xs leading-relaxed text-white/75" tabIndex={0}>
          {details.data.logs || 'Noch keine Ausgabe.'}
        </pre>
      )}
    </Modal>
  );
}

function ContainerRow({ container, metrics, onChanged }: { container: Container; metrics?: { cpu_percent: number; memory_bytes: number }; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState(false);
  const running = container.state === 'running';

  const run = async (command: 'start' | 'stop' | 'restart', done: string) => {
    setBusy(true);
    try {
      await action('docker_container_action', { container: container.id, action: command });
      toast(`${container.name}: ${done}`);
    } catch (reason) {
      toast(`${container.name}: ${message(reason)}`, true);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3">
      <div className="min-w-0 flex-1 basis-56">
        <div className="flex items-center gap-2 text-sm font-medium">
          <StateDot state={busy ? 'restarting' : container.state} />
          <span className="truncate">{container.name}</span>
          {container.managed_app && (
            <button type="button" onClick={() => go('apps', container.managed_app!)} className="shrink-0 rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-normal text-white/70 hover:bg-white/16">
              App
            </button>
          )}
        </div>
        <div className="truncate text-xs text-white/45">{container.image}</div>
      </div>
      <div className="w-36 shrink-0 text-xs tabular-nums text-white/55">
        {running && metrics ? `${metrics.cpu_percent.toFixed(1)} % CPU · ${bytes(metrics.memory_bytes)}` : running ? '' : 'Gestoppt'}
        {published(container) && <div className="truncate text-white/40">{published(container)}</div>}
      </div>
      <div className="flex shrink-0">
        <IconButton label={`Protokoll von ${container.name}`} onClick={() => setLogs(true)}>
          <FileText className="size-4" />
        </IconButton>
        {running ? (
          <>
            <IconButton label={`${container.name} neu starten`} disabled={busy} onClick={() => run('restart', 'neu gestartet.')}>
              <RotateCw className="size-4" />
            </IconButton>
            <IconButton label={`${container.name} stoppen`} disabled={busy} onClick={() => run('stop', 'gestoppt.')}>
              <Square className="size-4" />
            </IconButton>
          </>
        ) : (
          <IconButton label={`${container.name} starten`} disabled={busy} onClick={() => run('start', 'gestartet.')}>
            <Play className="size-4" />
          </IconButton>
        )}
      </div>
      {logs && <LogDialog container={container} onClose={() => setLogs(false)} />}
    </li>
  );
}

export function DockerSection() {
  const engine = useApi<Engine>('/api/docker-engine', 10000);
  const metrics = useApi<Metrics>('/api/docker-metrics', 10000);
  const [tab, setTab] = useState<Tab>('containers');

  if (engine.loading) return <Loading />;
  if (!engine.data) return <Notice>{engine.error}</Notice>;
  if (!engine.data.available) return <Notice tone="warn">{engine.data.error || 'Docker ist auf diesem System nicht verfügbar.'}</Notice>;
  const data = engine.data;
  const counts: Record<Tab, number> = { containers: data.containers.length, images: data.images.length, volumes: data.volumes.length, networks: data.networks.length };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Docker-Bereiche">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cx('h-9 rounded-full px-4 text-sm font-medium transition-colors', tab === id ? 'bg-white text-slate-900' : 'bg-white/8 text-white/75 hover:bg-white/14')}
          >
            {label} <span className="opacity-60">{counts[id]}</span>
          </button>
        ))}
      </div>
      <Card>
        {tab === 'containers' &&
          (data.containers.length ? (
            <ul className="divide-y divide-white/6">
              {data.containers.map(container => (
                <ContainerRow key={container.id} container={container} metrics={metrics.data?.containers[container.id]} onChanged={engine.reload} />
              ))}
            </ul>
          ) : (
            <Empty title="Keine Container">Installiere eine App im App Store.</Empty>
          ))}
        {tab === 'images' && (
          <ul className="divide-y divide-white/6">
            {data.images.map(image => (
              <li key={image.ID + image.Tag} className="flex items-center justify-between gap-4 py-2.5 text-sm">
                <span className="min-w-0 truncate">{image.Repository}<span className="text-white/45">:{image.Tag}</span></span>
                <span className="shrink-0 text-xs tabular-nums text-white/55">{image.Size}</span>
              </li>
            ))}
          </ul>
        )}
        {tab === 'volumes' && (
          <ul className="divide-y divide-white/6">
            {data.volumes.map(volume => (
              <li key={volume.Name} className="flex items-center justify-between gap-4 py-2.5 text-sm">
                <span className="min-w-0 truncate">{volume.Name}</span>
                <span className="shrink-0 text-xs text-white/55">{volume.Driver}</span>
              </li>
            ))}
          </ul>
        )}
        {tab === 'networks' && (
          <ul className="divide-y divide-white/6">
            {data.networks.map(network => (
              <li key={network.Name} className="flex items-center justify-between gap-4 py-2.5 text-sm">
                <span className="min-w-0 truncate">{network.Name}</span>
                <span className="shrink-0 text-xs text-white/55">{network.Driver}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Button onClick={() => window.open('/classic#docker', '_blank', 'noopener')}>Eigene Container anlegen, Images laden und aufräumen</Button>
    </div>
  );
}
