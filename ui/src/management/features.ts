import './modules';
import type { Session } from '../api';
import { waitJob } from '../api';
import { go, message } from '../lib';
import { modules as m, helpers, esc, field, selectField, formEnd, button } from './runtime';
import type { Data } from './runtime';

export type Feature = 'security' | 'web' | 'monitoring' | 'services' | 'docker' | 'backups' | 'storage' | 'updates' | 'resources' | 'logs' | 'activity';
const moduleNames: Partial<Record<Feature, string>> = { security: 'TitanSecurity', web: 'TitanWebAccess', monitoring: 'TitanMonitoring', services: 'TitanServices', docker: 'TitanDocker', backups: 'TitanBackupCenter', storage: 'TitanStorage', updates: 'TitanUpdates', resources: 'TitanResources' };

export async function mountFeature(feature: Feature, host: HTMLElement, ctx: Data, session?: Session) {
  let allUsers = false;
  let revision = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  let current: Data = {};
  const disposeModule = () => { m[moduleNames[feature] || '']?.dispose?.(); if (feature === 'storage') m.TitanStorageRecovery.disposeDialog(); };
  const paint = (html: string) => { if (!ctx.alive()) return; disposeModule(); host.innerHTML = html; };
  const refresh = async (all?: boolean) => {
    if (typeof all === 'boolean') allUsers = all;
    const mine = ++revision;
    const read = ctx.api;
    const valid = () => ctx.alive() && mine === revision;
    if (feature === 'docker') { await m.TitanDocker.mount(host, ctx); return; }
    if (feature === 'security') {
      const admin = session?.user?.role === 'admin';
      const [data, protection] = await Promise.all([read('/api/security' + (allUsers && admin ? '?all=1' : '')), admin ? read('/api/security/login-protection') : null]);
      if (!valid()) return;
      const options = { ...ctx, username: session?.user?.name, admin, protection, refresh };
      paint(m.TitanSecurity.render(data, options));
      m.TitanSecurity.mount(host, data, options);
    } else if (feature === 'web') {
      const [access, settings] = await Promise.all([read('/api/web-access'), read('/api/settings')]);
      if (!valid()) return;
      current = settings;
      paint(`<section class="panel"><h2>Servername</h2><form data-server-name>${field('Name im Netzwerk', 'hostname', 'text', settings.hostname, 'required maxlength="63"')}${formEnd('Servername speichern')}</form></section>` + m.TitanWebAccess.render(access));
      host.querySelector<HTMLFormElement>('[data-server-name]')!.onsubmit = event => {
        event.preventDefault();
        const form = event.currentTarget as HTMLFormElement;
        void saveSettings(form, { hostname: new FormData(form).get('hostname') });
      };
      m.TitanWebAccess.mount(host, { ...ctx, refresh });
    } else if (feature === 'monitoring') {
      const [data, settings] = await Promise.all([read('/api/monitoring'), read('/api/notifications/settings')]);
      if (!valid()) return;
      paint(button('Systemzustand prüfen', 'monitoring-check', '', 'primary') + m.TitanMonitoring.render(data, settings, helpers));
      m.TitanMonitoring.mount(host, { ...ctx, data });
    } else if (feature === 'services') {
      const data = await read('/api/services'); if (!valid()) return;
      paint(m.TitanServices.render(data, helpers));
      m.TitanServices.mount(host, { ...ctx, navigate: refresh }, data);
    } else if (feature === 'backups') {
      const admin = session?.user?.role === 'admin';
      const [data, settings, shares, locations] = await Promise.all([read('/api/backups'), read('/api/backup/settings'), read(admin ? '/api/managed-shares' : '/api/shares'), admin ? read('/api/storage-locations?purpose=backup') : { items: [] }]);
      if (!valid()) return;
      current = { data, settings, shares, locations };
      paint(button('Jetzt sichern', 'backup-create', settings.target ? '' : 'disabled', 'primary') + m.TitanBackupCenter.render(data, settings, shares, locations, helpers));
      m.TitanBackupCenter.mount(host, { ...ctx, shares, locations, refresh });
    } else if (feature === 'storage') {
      const [storage, snapshots, maintenance, health, locations] = await Promise.all([read('/api/storage'), read('/api/snapshots'), read('/api/storage/maintenance'), read('/api/monitoring'), read('/api/storage-locations')]);
      if (!valid()) return;
      // Reuse the tested maintenance and restore controllers without adding a
      // second storage overview. The React page owns capacity/setup/replacement.
      const template = document.createElement('template');
      template.innerHTML = m.TitanStorage.render(storage, snapshots, {}, { ...helpers, maintenance, health, locations });
      const maintenanceHtml = template.content.querySelector('[data-storage-pane="health"]')!.innerHTML;
      const preferencesHtml = template.content.querySelector('[data-storage-pane="settings"]')!.innerHTML;
      const pools = (storage.pools || []).map((pool: Data) => `<article class="list-row"><strong>${esc(pool.name)}</strong><div class="form-actions">${button('Daten prüfen', 'scrub', `data-pool="${esc(pool.name)}"`)}<button type="button" class="button" data-storage-command="recovery" data-pool="${esc(pool.name)}">RAID-Zustand / Reparatur</button>${button('Datenbereich hinzufügen', 'dataset-create', `data-parent="${esc(pool.name)}"`)}</div></article>`).join('');
      const disks = (storage.disks || []).filter((d: Data) => d.type === 'disk').map((d: Data) => `<article class="list-row"><strong>${esc(d.model || d.name)} <small>${esc(d.name)}</small></strong><div class="form-actions"><button type="button" class="button" data-storage-command="inspect-smart" data-disk="${esc(d.name)}">Zustand ansehen</button><button type="button" class="button" data-storage-command="smart" data-disk="${esc(d.name)}">SMART-Selbsttest</button></div></article>`).join('');
      const datasets = (storage.datasets || []).map((d: Data) => `<article class="list-row"><strong>${esc(d.name)}</strong>${button('Wiederherstellungspunkt erstellen', 'snapshot-create', `data-dataset="${esc(d.name)}"`)}</article>`).join('');
      paint(`<div data-storage-workspace><section class="panel"><h2>Laufwerke und ZFS</h2>${disks || '<p>Keine physischen Laufwerke gemeldet.</p>'}${pools}${datasets}</section>${maintenanceHtml}${preferencesHtml}</div>`);
      m.TitanStorage.mount(host, { ...ctx, storage, maintenance, locations, refresh });
    } else if (feature === 'updates') {
      const [settings, offer, system] = await Promise.all([read('/api/settings'), read('/api/updates'), read('/api/updates/system')]);
      if (!valid()) return;
      current = settings;
      paint(m.TitanWebUpdates.panel() + '<section id="update-progress" class="panel" hidden aria-live="polite"></section>' + m.TitanUpdates.offer('all', offer, settings, session || {}, system) + m.TitanUpdates.panel(system, '', { split: true }) + updateSettings(settings));
      if (settings.channel !== 'stable') {
        const install = host.querySelector<HTMLButtonElement>('[data-action="update-install"]');
        if (install) { install.dataset.updateEligible = 'false'; install.disabled = true; }
      }
      m.TitanUpdates.mount(host, ctx);
      m.TitanWebUpdates.mount(host, ctx);
      host.querySelector<HTMLFormElement>('[data-update-settings]')!.onsubmit = event => {
        event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const values = new FormData(form);
        void saveSettings(form, { channel: 'stable', auto_check: values.has('auto_check'), check_interval: values.get('check_interval'), installation: values.get('installation'), window_day: Number(values.get('window_day')), window_hour: Number(values.get('window_hour')) });
      };
    } else if (feature === 'resources') {
      const data = await read('/api/status'); if (!valid()) return;
      paint('<section class="panel"><div data-live-resources>' + m.TitanResources.resourceMetrics(data, { ...helpers, demo: session?.demo }) + '</div></section>');
      m.TitanResources.mount(host, { ...ctx, metricsFormat: { ...helpers, demo: session?.demo } });
    } else if (feature === 'logs') {
      const data = await read('/api/logs'); if (!valid()) return;
      paint(button('Aktualisieren', 'refresh') + `<section class="panel table-wrap"><table><thead><tr><th>Zeit</th><th>Benutzer</th><th>Aktion</th><th>Details</th></tr></thead><tbody>${data.map((item: Data) => `<tr><td>${helpers.date(item.time)}</td><td>${esc(item.username)}</td><td>${esc(item.action)}</td><td>${esc(item.detail)}</td></tr>`).join('')}</tbody></table>${!data.length ? '<p>Noch keine Ereignisse.</p>' : ''}</section>`);
    } else if (feature === 'activity') {
      const jobs = await read('/api/jobs'); if (!valid()) return;
      const labels: Data = { queued: 'Wartet', running: 'Läuft', completed: 'Abgeschlossen', failed: 'Fehlgeschlagen' };
      paint(`<section class="panel"><h2>Aufträge</h2>${jobs.map((job: Data) => `<details class="list-row job-result"><summary>${esc(job.action)} · ${esc(labels[job.status] || job.status)}</summary><p>${esc(job.result?.message || job.result?.error || '')}</p><pre class="code">${esc(JSON.stringify(job.result || {}, null, 2))}</pre></details>`).join('') || '<p>Keine Aufträge vorhanden.</p>'}</section>`);
    }
  };
  const saveSettings = async (form: HTMLFormElement, values: Data) => {
    const submit = form.querySelector<HTMLButtonElement>('[type="submit"]')!; submit.disabled = true;
    try { await ctx.api('/api/settings', { ...current, ...values }); ctx.toast('Einstellungen gespeichert.'); await refresh(); }
    catch (reason) { ctx.toast(message(reason), true); }
    finally { submit.disabled = false; }
  };
  ctx.refresh = refresh; ctx.navigate = refresh;

  const dispatch = async (target: HTMLElement) => {
    const command = target.dataset.action;
    const ds = target.dataset;
    if (command === 'refresh') { await refresh(); return; }
    if (command === 'app-manage') { go('apps', ds.id!); return; }
    if (command === 'monitoring-check') { await ctx.action('monitoring_check'); await refresh(); return; }
    if (command === 'alert-ack') { await ctx.api('/api/monitoring/ack', { id: ds.id }); await refresh(); return; }
    if (command === 'smart') { ctx.dialog('Laufwerkszustand', m.TitanStorage.smartDetails(await ctx.api('/api/smart?disk=' + encodeURIComponent(ds.disk!)), ds.disk)); return; }
    if (command === 'scrub') { if (await ctx.askYesNo(`Datenprüfung für ${ds.pool} starten?`)) { await ctx.action('scrub', { pool: ds.pool }); await refresh(); } return; }
    if (command === 'snapshot-create') { ctx.dialog('Wiederherstellungspunkt erstellen', `<form><p>${esc(ds.dataset)}</p>${field('Name', 'name', 'text', 'manuell-' + new Date().toISOString().slice(0, 10), 'required pattern="[a-z][a-z0-9_-]{0,30}"')}${formEnd('Erstellen')}</form>`, (values: FormData) => ctx.action('snapshot_create', { dataset: ds.dataset, name: values.get('name') })); return; }
    if (command === 'dataset-create') { ctx.dialog('Datenbereich hinzufügen', `<form><p>${esc(ds.parent)}</p>${field('Name', 'name', 'text', '', 'required pattern="[a-z][a-z0-9_-]{0,30}"')}${field('Speicherlimit in GB', 'quota_gb', 'number', 0, 'min="0" max="1000000"', '0 bedeutet kein eigenes Limit.')}${formEnd()}</form>`, (values: FormData) => ctx.action('dataset_create', { parent: ds.parent, name: values.get('name'), quota_gb: Number(values.get('quota_gb')) })); return; }
    if (command === 'backup-create') {
      const { settings, shares, data } = current;
      if (!settings.target) throw new Error('Zuerst ein unabhängiges Sicherungsziel einrichten.');
      ctx.dialog('Sicherung starten', `<form><p>Freigaben und Apps auswählen. Apps werden für eine konsistente Sicherung vorübergehend gestoppt.</p>${shares.map((share: Data) => `<label class="check-label"><input type="checkbox" name="shares" value="${esc(share.name)}" ${settings.shares.includes(share.name) ? 'checked' : ''}>${esc(share.label || share.name)}</label>`).join('')}${settings.delegated ? '' : `<label class="check-label"><input type="checkbox" name="include_config" ${settings.include_config ? 'checked' : ''}>NAS-Konfiguration sichern</label>${m.TitanBackupCenter.appFields(data.available_apps || [], settings)}`}${formEnd('Sicherung starten')}</form>`, (form: FormData) => {
        const args = { shares: form.getAll('shares'), include_config: !settings.delegated && form.has('include_config'), ...(!settings.delegated ? { apps: form.getAll('apps'), app_data: form.getAll('app_data') } : {}) };
        if (!args.shares.length && !args.include_config && !args.apps?.length) throw new Error('Mindestens eine Freigabe, App oder die NAS-Konfiguration auswählen.');
        return ctx.action('backup_create', args);
      });
      m.TitanBackupCenter.wireAppFields(ctx.dialogRoot()); return;
    }
    if (command === 'backup-verify') { await ctx.action('backup_verify', { backup: ds.id }); ctx.toast('Sicherung geprüft; Dateien sind unverändert.'); await refresh(); return; }
    if (command === 'vm-restore') { ctx.dialog('VM als neue Maschine wiederherstellen', `<form><p>Die geprüfte Sicherung wird als neue ausgeschaltete VM importiert.</p>${field('Name der neuen VM', 'name', 'text', '', 'required maxlength="96"')}${formEnd('Wiederherstellen')}</form>`, (form: FormData) => ctx.action('vm_restore', { backup: ds.id, name: form.get('name') })); return; }
    if (command === 'backup-config-restore') { ctx.dialog('NAS-Konfiguration wiederherstellen', `<p class="notice warning">Gesicherte Benutzer, Freigabenrechte und NAS-Einstellungen ersetzen den aktuellen Stand. Datenordner bleiben erhalten. Titan sichert die aktuelle Konfiguration vorher. Weboberfläche und SMB werden kurz gestoppt. Alle Sitzungen enden; danach gelten die Konten und Passwörter aus der Sicherung.</p><form>${formEnd('Ja, wiederherstellen')}</form>`, () => ctx.action('backup_config_restore', { backup: ds.id, confirmation: ds.id })); return; }
    if (command === 'update-check') { const result = await ctx.api('/api/updates/check', { update_kind: 'all' }); await waitJob(result.job); await refresh(); return; }
    if (command === 'update-install') { if (current.channel !== 'stable') throw new Error('Zuerst den Stable-Kanal speichern.'); ctx.dialog('Systemupdate vorbereiten', `<p>Titan ${esc(ds.version)} herunterladen und prüfen? Das System wechselt erst nach einem bestätigten Neustart. Die NAS-Konfiguration wird vorher gesichert.</p><form>${formEnd('Ja, vorbereiten')}</form>`, () => ctx.action('update_install', { expected_version: ds.version, update_kind: 'all' })); return; }
    if (command === 'update-rollback') {
      const digest = host.querySelector<HTMLSelectElement>('#rollback-version')?.value;
      const state = await ctx.api('/api/updates/system');
      const choice = m.TitanUpdates.rollbackChoices(state).find((item: Data) => item.digest === digest);
      if (!state.rollback_available || !choice) throw new Error(state.rollback_reason || 'Gewählter Systemstand nicht mehr verfügbar.');
      const compatibility = m.TitanUpdates.rollbackSecurity(choice);
      const security = await ctx.api('/api/security?all=1');
      ctx.dialog('System-Rollback vorbereiten', `<p>Zurück zu ${esc(choice.version || 'dem vorherigen Stand')} beim nächsten Neustart. App-/VM-Daten, Freigaben und die aktuelle NAS-Konfiguration bleiben erhalten. Die Konfiguration wird vorher gesichert. Neuere Sicherheitskorrekturen können entfallen.</p>${compatibility.legacyTwoFactor && security.two_factor_user_count > 0 ? '<p class="notice warning">Dieser Stand unterstützt keine Zwei-Faktor-Anmeldung. Bis zur erneuten Aktualisierung wird nur das Passwort geprüft.</p>' : ''}${compatibility.legacyProtections ? '<p class="notice warning">Dieser Stand enthält den aktuellen Anmeldeschutz und die Schutzgrenze für Systemdateien noch nicht.</p>' : ''}<form>${formEnd('Ja, Rollback vorbereiten')}</form>`, () => ctx.action('update_rollback', { expected_digest: digest, confirmation: 'ROLLBACK' })); return;
    }
    if (command === 'system-reboot') {
      const state = await ctx.api('/api/updates/system'); const next = state.next_boot || state.staged || (state.rollback_queued ? state.rollback : state.booted);
      if (!next || state.reboot_scheduled) throw new Error('Neustart bereits geplant oder Systemstand nicht bestätigt.');
      ctx.dialog('NAS neu starten', `<p>Offene Arbeiten speichern und laufende VMs herunterfahren. Apps und Freigaben sind während des Neustarts nicht erreichbar. Titan aktiviert ${esc(next.version || 'den gewählten Stand')}.</p><form>${formEnd('Ja, neu starten')}</form>`, () => ctx.action('system_reboot', { expected_digest: next.digest, confirmation: 'NEUSTART' }));
    }
  };
  const click = (event: Event) => {
    const target = (event.target as Element).closest<HTMLElement>('[data-action]');
    if (!target || target.matches(':disabled') || ['close', 'accept'].includes(target.dataset.action || '')) return;
    if (!host.contains(target) && !ctx.dialogRoot().contains(target)) return;
    event.preventDefault();
    if (target.dataset.pending) return;
    target.dataset.pending = 'true';
    void dispatch(target).catch(reason => ctx.toast(message(reason), true)).finally(() => delete target.dataset.pending);
  };
  host.addEventListener('click', click, { signal: ctx.signal });
  ctx.dialogRoot().addEventListener('click', click, { signal: ctx.signal });
  const cleanup = () => { revision++; if (timer) clearInterval(timer); disposeModule(); host.replaceChildren(); };
  try { await refresh(); if (ctx.alive() && feature === 'activity') timer = setInterval(() => { if (!document.hidden && !host.querySelector('details[open]')) void refresh().catch(reason => ctx.toast(message(reason), true)); }, 3000); }
  catch (reason) { cleanup(); throw reason; }
  return cleanup;
}

function updateSettings(settings: Data) {
  return `<details class="panel"><summary>Automatische Updates und Wartungsfenster</summary><form data-update-settings><p>Titan veröffentlicht ausschließlich Stable-Versionen. Einzelne experimentelle Funktionen sind in der Oberfläche als Beta gekennzeichnet.</p>${settings.channel !== 'stable' ? '<p class="notice warning">Speichere diese Einstellungen, um vom bisherigen Kanal auf Stable zu wechseln. Es wird dabei keine Version installiert.</p>' : ''}<label class="check-label"><input type="checkbox" name="auto_check" ${settings.auto_check ? 'checked' : ''}>Automatisch nach Updates suchen</label>${selectField('Prüfintervall', 'check_interval', [['daily', 'Täglich'], ['weekly', 'Wöchentlich']], settings.check_interval)}${selectField('Vorbereitung', 'installation', [['manual', 'Manuell'], ['automatic', 'Automatisch im Wartungsfenster']], settings.installation)}${selectField('Wartungstag', 'window_day', ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'].map((day, index) => [index, day]), settings.window_day)}${selectField('Uhrzeit auf dem NAS', 'window_hour', Array.from({ length: 24 }, (_, hour) => [hour, `${String(hour).padStart(2, '0')}:00`]), settings.window_hour)}<p class="hint">Systemupdates werden geprüft und vorbereitet. Einen Neustart bestätigst du selbst.</p><div class="form-actions"><button type="submit" class="button primary">Update-Einstellungen speichern</button></div></form></details>`;
}
