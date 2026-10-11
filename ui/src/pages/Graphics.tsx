import { useState } from 'react';
import { Cpu, Download } from 'lucide-react';
import { post, waitJob } from '../api';
import { cx, message, useApi } from '../lib';
import { Button, Card, Confirm, Notice, useToast } from '../ui';

type Gpu = { pci: string; vendor: string; model: string; driver: string | null; passthrough?: boolean };
type Components = {
  components: { nvidia?: { card: boolean; installed: boolean; available: boolean; requested: boolean; passthrough: boolean } };
  gpus?: Gpu[];
};

/**
 * Graphics cards of the NAS and the optional NVIDIA driver. Intel and AMD
 * cards work with the built-in kernel drivers. NVIDIA's driver is proprietary,
 * so Titan downloads it from NVIDIA on request instead of shipping it.
 */
export function GraphicsCard() {
  const toast = useToast();
  const components = useApi<Components>('/api/components', 30000);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const gpus = components.data?.gpus || [];
  const nvidia = components.data?.components.nvidia;
  if (!components.data || (!gpus.length && !nvidia?.card)) return null;

  const install = async () => {
    setBusy(true);
    setError('');
    try {
      const { job } = await post<{ job: string }>('/api/components/install', { component: 'nvidia' });
      await waitJob(job, 40 * 60 * 1000);
      toast('Der NVIDIA-Treiber ist installiert. Die Grafikkarte lässt sich jetzt einer App zuweisen.');
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
      await components.reload();
    }
  };

  return (
    <Card>
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Cpu className="size-4 text-white/50" aria-hidden /> Grafikkarte
      </h2>
      {nvidia?.card && <p className="mt-2 text-xs text-white/50">Beta · Die optionale NVIDIA-Treiberinstallation ist noch nicht umfassend auf physischer Hardware erprobt.</p>}
      <ul className="mt-2 divide-y divide-white/6">
        {gpus.map(gpu => (
          <li key={gpu.pci} className="flex items-center justify-between gap-4 py-2.5 text-sm">
            <span className="min-w-0 truncate">
              <span className="font-medium">{gpu.vendor}</span> <span className="text-white/65">{gpu.model}</span>
            </span>
            <span className={cx('shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium', gpu.passthrough ? 'bg-white/10 text-white/70' : gpu.driver ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn')}>
              {gpu.passthrough ? 'An VM durchgereicht' : gpu.driver ? `Treiber ${gpu.driver}` : 'Kein Treiber'}
            </span>
          </li>
        ))}
      </ul>
      {nvidia?.card && (
        <div className="mt-3 space-y-3">
          {nvidia.available ? (
            <Notice tone="info">Der NVIDIA-Treiber ist aktiv. Weise die Karte auf der Seite einer App unter „Grafikkarte und Geräte“ zu.</Notice>
          ) : (
            <>
              <p className="text-sm leading-relaxed text-white/60">
                Für Apps wie Ollama, Jellyfin oder Immich braucht eine NVIDIA-Karte den Treiber von NVIDIA. Titan lädt ihn direkt bei NVIDIA und baut das Kernelmodul; das dauert einige Minuten und braucht Internet. Für eine virtuelle Maschine ist er nicht nötig.
              </p>
              {nvidia.requested && !busy && <Notice tone="warn">Der Treiber war eingerichtet und wird nach einem Systemupdate im Hintergrund neu gebaut. Dauert das länger als einige Minuten, hier erneut installieren.</Notice>}
              {error && <Notice>{error}</Notice>}
              <Button variant="primary" busy={busy} onClick={() => setConfirm(true)}>
                <Download className="size-4" /> {busy ? 'Wird installiert …' : 'NVIDIA-Treiber installieren'}
              </Button>
            </>
          )}
        </div>
      )}
      {confirm && (
        <Confirm
          title="NVIDIA-Treiber installieren?"
          text="Titan lädt den proprietären Treiber aus dem Paketarchiv von NVIDIA; dafür gelten NVIDIAs Lizenzbedingungen. Zum Abschluss startet Docker neu, laufende Apps sind dabei kurz unterbrochen."
          confirmLabel="Installieren"
          onClose={() => setConfirm(false)}
          onConfirm={() => {
            void install();
          }}
        />
      )}
    </Card>
  );
}
