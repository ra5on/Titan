import { go, useApi } from '../lib';
import { Button, Loading, Notice } from '../ui';

export function RemoteSession({ kind, target, title }: { kind: 'app' | 'vm'; target: string; title: string }) {
  const service = useApi<{installed: boolean; running: boolean; demo?: boolean}>('/api/desktops/status', 15000);
  if (service.loading) return <Loading />;
  if (service.error || !service.data?.running) return <div className="mx-auto max-w-lg space-y-3 p-6">
    <Notice tone="info">{service.error || 'Für Sitzungen innerhalb von Titan das Plugin „Browser und VM-Sitzungen“ installieren oder starten.'}</Notice>
    <Button onClick={() => go('store', 'plugin-guacamole')}>Zum Plugin</Button>
  </div>;
  if (service.data.demo) return <div className="p-6"><Notice tone="info">Die Demo startet keine Fernsitzungen. Apps und VMs benötigen eine echte Titan-Installation.</Notice></div>;
  return <iframe src={`/desktop.html?${new URLSearchParams({kind, target})}`} title={title}
    className="absolute inset-0 size-full border-0" allow="fullscreen; clipboard-read; clipboard-write" />;
}
