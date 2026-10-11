import { action, get, post } from './api';

/** Restart the NAS. The agent only reboots the system state the administrator has seen. */
export async function rebootSystem() {
  const system = await get<{ booted: { digest: string } }>('/api/updates/system');
  const result = await action('system_reboot', { expected_digest: system.booted.digest, confirmation: 'NEUSTART' });
  return String(result.message || 'Das NAS startet neu.');
}

export async function shutdownSystem() {
  const result = await action('system_shutdown', { confirmation: true });
  return String(result.message || 'Das NAS wird ausgeschaltet.');
}

export const logout = () => post('/api/logout');

export type AppAddress = { url: string | null; embeddable: boolean; reason?: string };

type RemoteAccess = { remote?: { enabled?: boolean; public_origin?: string; app_urls?: Record<string, string> } };
let remote: Promise<RemoteAccess | null> | null = null;

/** Forget the cached remote access settings after they changed. */
export const forgetRemoteAccess = () => {
  remote = null;
};

/**
 * Address of an app for this browser. On the NAS address it is the app's own
 * port; when Titan is opened through the configured public address, it is the
 * app's public address from the remote access settings.
 */
export async function appAddress(app: { id: string; port: number | null; scheme?: string }): Promise<AppAddress> {
  remote ??= get<RemoteAccess>('/api/remote-access').catch(() => null);
  const settings = (await remote)?.remote;
  if (settings?.enabled && settings.public_origin === window.location.origin) {
    const address = settings.app_urls?.[app.id];
    return address
      ? { url: address, embeddable: true }
      : { url: null, embeddable: false, reason: 'Für diese App ist keine öffentliche Adresse eingerichtet. Lege sie im Fernzugriff an, um die App von unterwegs zu öffnen.' };
  }
  if (!app.port) return { url: null, embeddable: false, reason: 'Diese App hat keine eigene Weboberfläche.' };
  const scheme = app.scheme || 'http';
  const url = `${scheme}://${window.location.hostname}:${app.port}`;
  // Browsers refuse to show an unencrypted page inside an encrypted one.
  if (window.location.protocol === 'https:' && scheme === 'http')
    return { url, embeddable: false, reason: 'Titan läuft verschlüsselt (HTTPS), diese App unverschlüsselt. Browser zeigen sie deshalb nicht im Titan-Fenster an.' };
  return { url, embeddable: true };
}
