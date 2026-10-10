import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeft, BookOpen, Check, CircleDashed, ExternalLink, Search, XCircle } from 'lucide-react';
import { get, post, waitJob } from '../api';
import type { CatalogApp, InstallStatus, InstalledApp, SchemaField } from '../api';
import { cx, go, message, useApi } from '../lib';
import { AppIcon, Button, Card, Empty, Field, Input, Loading, Notice, Select, Sheet, Spinner, useToast } from '../ui';

type Catalog = { apps: CatalogApp[]; error?: string | null };

const initial = (field: SchemaField) => String(field.display_default ?? field.default ?? '');

function AppCard({ app, installed }: { app: CatalogApp; installed: boolean }) {
  return (
    <button
      type="button"
      onClick={() => go('store', app.id)}
      className="glass-soft flex items-center gap-4 rounded-2xl p-4 text-left transition-colors hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-brand"
    >
      <AppIcon id={app.id} name={app.name} color={app.color} size={60} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold">{app.name}</span>
          {installed && <span className="rounded-full bg-ok/15 px-2 py-0.5 text-[11px] font-medium text-ok">Installiert</span>}
        </div>
        <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-white/55">{app.description}</p>
      </div>
    </button>
  );
}

function StepIcon({ status }: { status: string }) {
  if (status === 'completed' || status === 'skipped') return <Check className="size-4 text-ok" aria-label="Fertig" />;
  if (status === 'running') return <Spinner className="size-4 text-brand" />;
  if (status === 'failed' || status === 'interrupted') return <XCircle className="size-4 text-bad" aria-label="Fehlgeschlagen" />;
  return <CircleDashed className="size-4 text-white/30" aria-label="Ausstehend" />;
}

function Detail({ app, installedApp, onChanged }: { app: CatalogApp; installedApp?: InstalledApp; onChanged: () => void }) {
  const toast = useToast();
  const statusPath = `/api/app-install?app=${encodeURIComponent(app.id)}`;
  const install = useApi<InstallStatus>(statusPath);
  const fields = useMemo(() => (app.install_schema || []).filter(field => !field.generated), [app]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [live, setLive] = useState<InstallStatus | null>(null);

  useEffect(() => {
    setValues(Object.fromEntries(fields.map(field => [field.key, initial(field)])));
  }, [fields]);

  // While an installation runs, mirror the agent's real step list.
  useEffect(() => {
    if (!running) return;
    let stopped = false;
    const tick = async () => {
      try {
        const value = await get<InstallStatus>(statusPath);
        if (!stopped) setLive(value);
      } catch {
        // A transient read failure must not hide the running installation.
      }
    };
    void tick();
    const timer = window.setInterval(tick, 1500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [running, statusPath]);

  const state = live || install.data;
  const installed = Boolean(installedApp) || Boolean(state?.installed);

  const start = async (resume: boolean) => {
    if (!state) return;
    setError('');
    setRunning(true);
    try {
      const options = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ''));
      const { job } = resume
        ? await post<{ job: string }>('/api/app-install/resume', { app: app.id, expected_revision: state.revision })
        : await post<{ job: string }>('/api/app-install', { app: app.id, options, expected_revision: state.revision });
      await waitJob(job, 60 * 60 * 1000);
      toast(`${app.name} wurde installiert.`);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setRunning(false);
      setLive(null);
      await install.reload();
      onChanged();
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void start(false);
  };

  const url = installedApp?.port ? `${installedApp.scheme || 'http'}://${window.location.hostname}:${installedApp.port}` : null;
  const showSteps = running || (state && state.status !== 'idle' && !installed);

  return (
    <Sheet
      title={app.name}
      subtitle={app.category}
      actions={
        <Button variant="ghost" size="sm" onClick={() => go('store')}>
          <ArrowLeft className="size-4" /> App Store
        </Button>
      }
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <div className="flex items-center gap-5">
            <AppIcon id={app.id} name={app.name} color={app.color} size={96} />
            <div className="min-w-0">
              <p className="text-[15px] leading-relaxed text-white/75">{app.description}</p>
              {app.documentation && (
                <a href={app.documentation} target="_blank" rel="noreferrer noopener" className="mt-2 inline-flex items-center gap-1.5 text-sm text-brand hover:underline">
                  <BookOpen className="size-4" /> Dokumentation
                </a>
              )}
            </div>
          </div>
          {app.note && <Notice tone="info">{app.note}</Notice>}
          {app.dependencies && app.dependencies.length > 0 && (
            <Card>
              <h2 className="text-sm font-semibold">Enthaltene Dienste</h2>
              <ul className="mt-3 space-y-1.5 text-sm text-white/65">
                {app.dependencies.map(item => (
                  <li key={item} className="flex items-center gap-2">
                    <Check className="size-3.5 text-ok" aria-hidden /> {item}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {app.first_login?.instructions && (
            <Card>
              <h2 className="text-sm font-semibold">Nach der Installation</h2>
              <p className="mt-2 text-sm leading-relaxed text-white/65">{app.first_login.instructions}</p>
            </Card>
          )}
        </div>

        <Card className="h-fit">
          {install.loading ? (
            <Loading />
          ) : installed && !running ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium text-ok">
                <Check className="size-4" /> Installiert
              </div>
              {url && installedApp?.state === 'running' ? (
                <Button variant="primary" className="w-full" onClick={() => window.open(url, '_blank', 'noopener')}>
                  <ExternalLink className="size-4" /> Öffnen
                </Button>
              ) : (
                <p className="text-sm text-white/55">Die App ist gestoppt. Auf der Startseite über das App-Menü starten.</p>
              )}
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <dl className="grid grid-cols-2 gap-3 text-sm">
                {app.port && (
                  <div>
                    <dt className="text-xs text-white/45">Port</dt>
                    <dd className="mt-0.5 font-medium tabular-nums">{app.port}</dd>
                  </div>
                )}
                {app.memory && (
                  <div>
                    <dt className="text-xs text-white/45">RAM-Grenze</dt>
                    <dd className="mt-0.5 font-medium">{app.memory.toUpperCase()}</dd>
                  </div>
                )}
              </dl>
              {!showSteps &&
                fields.map(field => (
                  <Field key={field.key} label={field.label + (field.required ? '' : ' (optional)')} help={field.help}>
                    {field.choices ? (
                      <Select value={values[field.key] ?? ''} onChange={event => setValues({ ...values, [field.key]: event.target.value })} required={field.required}>
                        {field.choices.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Input
                        type={field.secret || field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
                        value={values[field.key] ?? ''}
                        placeholder={field.placeholder}
                        onChange={event => setValues({ ...values, [field.key]: event.target.value })}
                        required={field.required}
                        autoComplete="off"
                      />
                    )}
                  </Field>
                ))}
              {showSteps && state && (
                <ol className="space-y-2.5">
                  {state.steps.map(step => (
                    <li key={step.id} className="flex items-start gap-2.5 text-sm">
                      <span className="mt-0.5">
                        <StepIcon status={step.status} />
                      </span>
                      <span className="min-w-0">
                        <span className={cx(step.status === 'pending' ? 'text-white/45' : 'text-white/90')}>{step.label}</span>
                        {step.message && <span className="block text-xs leading-relaxed text-white/50">{step.message}</span>}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
              {error && <Notice>{error}</Notice>}
              {state?.demo && <Notice tone="info">In der Demo werden keine Apps installiert.</Notice>}
              {state?.resumable && !running ? (
                <Button variant="primary" className="w-full" onClick={() => start(true)}>
                  Installation fortsetzen
                </Button>
              ) : (
                <Button type="submit" variant="primary" className="w-full" busy={running} disabled={!state || state.demo}>
                  {running ? 'Wird installiert …' : 'Installieren'}
                </Button>
              )}
            </form>
          )}
        </Card>
      </div>
    </Sheet>
  );
}

export function Store({ appId }: { appId?: string }) {
  const catalog = useApi<Catalog>('/api/catalog');
  const apps = useApi<{ installed: InstalledApp[] }>('/api/apps', 15000);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');

  const installed = useMemo(() => new Map((apps.data?.installed || []).map(app => [app.id, app])), [apps.data]);
  const all = catalog.data?.apps || [];
  const selected = appId ? all.find(app => app.id === appId) : undefined;

  if (appId) {
    if (catalog.loading) return <Sheet title="App Store"><Loading /></Sheet>;
    if (!selected)
      return (
        <Sheet title="App Store">
          <Empty title="App nicht gefunden">
            <Button className="mt-3" onClick={() => go('store')}>Zum App Store</Button>
          </Empty>
        </Sheet>
      );
    return <Detail key={selected.id} app={selected} installedApp={installed.get(selected.id)} onChanged={apps.reload} />;
  }

  const categories = [...new Set(all.map(app => app.category))].sort((a, b) => a.localeCompare(b, 'de'));
  const needle = query.trim().toLowerCase();
  const visible = all.filter(app => (!category || app.category === category) && (!needle || `${app.name} ${app.description} ${app.category}`.toLowerCase().includes(needle)));
  const featured = all[0];

  return (
    <Sheet
      title="App Store"
      subtitle="Geprüfte Apps, mit einem Klick als Docker-Compose-Verbund installiert"
      actions={
        <div className="relative">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-white/40" aria-hidden />
          <Input value={query} onChange={event => setQuery(event.target.value)} placeholder="Apps suchen" aria-label="Apps suchen" className="h-10 w-56 rounded-full pl-10" />
        </div>
      }
    >
      {catalog.loading ? (
        <Loading />
      ) : catalog.error ? (
        <Notice>{catalog.error}</Notice>
      ) : (
        <div className="space-y-7">
          {featured && !needle && !category && (
            <button
              type="button"
              onClick={() => go('store', featured.id)}
              className="relative flex w-full items-center gap-6 overflow-hidden rounded-3xl bg-gradient-to-br from-indigo-500/70 via-violet-600/60 to-fuchsia-600/50 p-7 text-left transition-transform hover:scale-[1.005] focus-visible:outline-2 focus-visible:outline-white sm:p-9"
            >
              <AppIcon id={featured.id} name={featured.name} color={featured.color} size={104} />
              <div className="min-w-0">
                <div className="text-xs font-semibold uppercase tracking-widest text-white/70">Empfohlen</div>
                <div className="mt-1 text-3xl font-semibold tracking-tight">{featured.name}</div>
                <p className="mt-2 line-clamp-2 max-w-xl text-sm leading-relaxed text-white/80">{featured.description}</p>
              </div>
            </button>
          )}
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Kategorien">
            {['', ...categories].map(item => (
              <button
                key={item || 'all'}
                type="button"
                role="tab"
                aria-selected={category === item}
                onClick={() => setCategory(item)}
                className={cx('h-9 rounded-full px-4 text-sm font-medium transition-colors', category === item ? 'bg-white text-slate-900' : 'bg-white/8 text-white/75 hover:bg-white/14')}
              >
                {item || 'Alle'}
              </button>
            ))}
          </div>
          {visible.length ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {visible.map(app => (
                <AppCard key={app.id} app={app} installed={installed.has(app.id)} />
              ))}
            </div>
          ) : (
            <Empty title="Keine App gefunden">Suchbegriff oder Kategorie ändern.</Empty>
          )}
        </div>
      )}
    </Sheet>
  );
}
