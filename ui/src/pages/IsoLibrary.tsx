import { useState } from 'react';
import { action } from '../api';
import { bytes, message, useApi } from '../lib';
import { Button, Loading, Modal, Notice } from '../ui';

export function IsoLibrary({ onClose }: { onClose: () => void }) {
  const data = useApi<{ items: { name: string; size: number; used_by: string[] }[]; error?: string }>('/api/iso-library');
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const remove = async () => {
    setBusy(true); setError('');
    try { await action('iso_remove', { name: selected }); setSelected(''); await data.reload(); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  return <Modal title="ISO-Bibliothek" onClose={() => { if (!busy) onClose(); }}>
    {data.loading ? <Loading /> : <div className="space-y-4">
      <p className="text-sm text-white/65">ISO-Abbilder, die in einer VM eingelegt sind, bleiben geschützt. Neue Abbilder fügst du über „ISO hochladen“ hinzu.</p>
      {(error || data.error || data.data?.error) && <Notice>{error || data.error || data.data?.error}</Notice>}
      <ul className="divide-y divide-white/10">{data.data?.items.map(item => <li key={item.name} className="flex items-center justify-between gap-4 py-3"><div className="min-w-0"><p className="break-all text-sm font-medium">{item.name}</p><p className="text-xs text-white/55">{bytes(item.size)}{item.used_by.length ? ` · Eingelegt: ${item.used_by.join(', ')}` : ''}</p></div><Button size="sm" disabled={busy || !!item.used_by.length} onClick={() => setSelected(item.name)}>Entfernen</Button></li>)}</ul>
      {data.data?.items.length === 0 && <p className="text-sm">Noch keine ISO-Abbilder gespeichert.</p>}
      {selected && <div className="space-y-3"><Notice tone="warn">„{selected}“ dauerhaft aus der ISO-Bibliothek löschen?</Notice><div className="flex justify-end gap-2"><Button disabled={busy} onClick={() => setSelected('')}>Abbrechen</Button><Button variant="danger" busy={busy} onClick={remove}>Endgültig entfernen</Button></div></div>}
    </div>}
  </Modal>;
}
