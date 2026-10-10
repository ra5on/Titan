// Thin client for the Titan web API. All mutations carry the session CSRF token.

export type Permission = { allowed: boolean };
export type Session = {
  user: { name: string; role: 'admin' | 'user'; system_user: string; csrf: string } | null;
  setup_required: boolean;
  setup_csrf?: string;
  demo: boolean;
  version: string;
  stage: string;
  permissions: Partial<Record<'files' | 'apps' | 'vms' | 'backups', Permission>>;
};

export type Status = {
  hostname: string;
  uptime: number;
  cpus: number;
  cpu_percent: number;
  cpu_temperature?: number;
  temperature_available?: boolean;
  memory_total: number;
  memory_used: number;
  version: string;
};

export type InstalledApp = {
  id: string;
  name: string;
  port: number | null;
  scheme: string;
  state: string;
  status: string;
};

export type SchemaField = {
  key: string;
  label: string;
  type: string;
  default?: string | number | boolean | null;
  display_default?: string | number | boolean | null;
  required?: boolean;
  generated?: boolean;
  secret?: boolean;
  choices?: [string, string][];
  help?: string;
  placeholder?: string;
};

export type CatalogApp = {
  id: string;
  name: string;
  category: string;
  description: string;
  port: number | null;
  memory?: string;
  color?: string;
  symbol?: string;
  documentation?: string;
  note?: string;
  version?: string;
  catalog_status?: string;
  dependencies?: string[];
  install_schema?: SchemaField[];
  first_login?: { instructions?: string };
};

export type InstallStep = { id: string; label: string; status: string; message: string };
export type InstallStatus = {
  app: string;
  revision: string;
  status: string;
  current_step: string;
  steps: InstallStep[];
  resumable: boolean;
  installed: boolean;
  demo?: boolean;
};

export type Share = { name: string; path: string; readers: string[]; writers: string[] };
export type FileEntry = { name: string; directory: boolean; symlink: boolean; size: number; modified: number };
export type FileListing = { entries: FileEntry[]; path: string; total: number; has_more: boolean };

export type Vm = {
  id: string;
  name: string;
  display_name?: string;
  state: string;
  cpus: number;
  memory_mb: number;
  disk_gb: number;
  autostart: boolean;
  metrics?: { cpu_percent?: number; memory_resident_bytes?: number };
};
export type VmList = { vms: Vm[]; available: boolean; error?: string };
export type VmOptions = {
  storage: { id: string; label: string; available: boolean; free_bytes: number }[];
  default_storage: string;
  isos: string[];
  firmwares: string[];
};

export type Storage = {
  pools: { name: string; size: number; used: number; free: number; health: string }[];
  disks: { name: string; size: number; model: string; fstype: string | null }[];
};
export type Monitoring = {
  alerts: { id: string; severity: string; title: string; detail: string; active: boolean; acknowledged: boolean }[];
  services: Record<string, { installed: boolean; active: boolean }>;
};
export type Users = { web: { name: string; role: string; enabled: boolean; display_name: string }[] };
export type Updates = { current: string; channel: string; available: boolean; latest?: string | null };
export type Job = { id: string; action: string; status: 'queued' | 'running' | 'completed' | 'failed'; result: Record<string, unknown> };

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

let csrf = '';
export const setCsrf = (value: string) => {
  csrf = value;
};

async function parse<T>(response: Response): Promise<T> {
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // Non-JSON bodies only occur on proxy failures; report the status below.
  }
  if (!response.ok) {
    const message = (data as { error?: string } | null)?.error || `Anfrage fehlgeschlagen (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return data as T;
}

export const get = <T>(path: string, signal?: AbortSignal) =>
  fetch(path, { credentials: 'same-origin', signal }).then(response => parse<T>(response));

export const post = <T>(path: string, body: unknown = {}, token = csrf) =>
  fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(body),
  }).then(response => parse<T>(response));

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/** Wait for a background job and return its result; a failed job rejects with its message. */
export async function waitJob(id: string, timeoutMs = 30 * 60 * 1000): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const job = (await get<Job[]>('/api/jobs')).find(item => item.id === id);
    if (job?.status === 'completed') return job.result;
    if (job?.status === 'failed') throw new ApiError(String(job.result.error || job.result.message || 'Auftrag fehlgeschlagen.'), 500);
    await sleep(1000);
  }
  throw new ApiError('Der Auftrag läuft noch. Den Stand später erneut prüfen.', 504);
}

/** Run an agent mutation through the job queue and wait for it. */
export async function action(operation: string, args: Record<string, unknown> = {}) {
  const { job } = await post<{ job: string }>('/api/actions', { operation, arguments: args });
  return waitJob(job);
}

const CHUNK = 2 * 1024 * 1024;

/** Chunked upload using the server's private staging and atomic commit protocol. */
export async function uploadFile(share: string, path: string, file: File, onProgress: (fraction: number) => void, signal: AbortSignal) {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const upload_id = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  const base = { share, path, upload_id, total: file.size };
  let offset = 0;
  try {
    while (offset < file.size) {
      const chunk = file.slice(offset, offset + CHUNK);
      const response = await fetch('/api/file-upload', {
        method: 'POST',
        credentials: 'same-origin',
        signal,
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-CSRF-Token': csrf,
          'X-Titan-Upload': encodeURIComponent(JSON.stringify({ ...base, offset })),
        },
        body: chunk,
      });
      const result = await parse<{ offset: number }>(response);
      offset = result.offset;
      onProgress(file.size ? offset / file.size : 1);
    }
    await post('/api/files', { ...base, action: 'upload', finish: true });
    onProgress(1);
  } catch (error) {
    // Release the staged partial file; the original error is what the user needs.
    await post('/api/files', { ...base, action: 'upload', cancel: true }).catch(() => undefined);
    throw error;
  }
}
