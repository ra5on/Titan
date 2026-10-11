import { action, get, post } from '../api';
import { bytes, dateTime, message } from '../lib';

// Titan's independently tested administration modules accept a DOM host and
// callbacks. They run inside the React shell; app.js and workspace.js never load.
// Keep their untyped boundary here rather than spreading it through React pages.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Data = Record<string, any>;
export const modules = window as unknown as Record<string, Data>;
export const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
export const button = (label: string, command: string, attributes = '', variant = '') => `<button type="button" class="button ${variant}" data-action="${esc(command)}" ${attributes}>${esc(label)}</button>`;
export const field = (label: string, name: string, type = 'text', value: unknown = '', attributes = '', help = '') => `<label class="field">${esc(label)}<input name="${esc(name)}" type="${esc(type)}" value="${esc(value)}" ${attributes}>${help ? `<small>${esc(help)}</small>` : ''}</label>`;
export const selectField = (label: string, name: string, choices: unknown[][], value?: unknown) => `<label class="field">${esc(label)}<select name="${esc(name)}">${choices.map(([id, title]) => `<option value="${esc(id)}" ${String(id) === String(value) ? 'selected' : ''}>${esc(title)}</option>`).join('')}</select></label>`;
export const formEnd = (label = 'Speichern') => `<div class="form-actions"><button type="submit" class="button primary">${esc(label)}</button>${button('Abbrechen', 'close')}</div>`;
export const pill = (label: unknown, color = '') => `<span class="pill ${esc(color)}">${esc(label)}</span>`;
export const helpers = { esc, button, field, selectField, formEnd, pill, bytes, date: dateTime };

export function createRuntime(host: HTMLElement, modal: HTMLDialogElement, toast: (text: string, bad?: boolean) => void) {
  const body = modal.querySelector<HTMLElement>('#dialog-body')!;
  let alive = true;
  let busy = false;
  let sequence = 0;
  let cleanupDialog: (() => void) | undefined;
  const controller = new AbortController();
  const { signal } = controller;
  const close = () => { if (!busy) modal.close(); };
  modal.addEventListener('cancel', event => { if (busy) event.preventDefault(); }, { signal });
  modal.addEventListener('close', () => { cleanupDialog?.(); cleanupDialog = undefined; body.replaceChildren(); }, { signal });
  modal.addEventListener('click', event => {
    if ((event.target as Element).closest('[data-action="close"]')) close();
  }, { signal });

  const ctx: Data = {
    ...helpers, host, signal, alive: () => alive,
    api: (path: string, data?: unknown, options?: { signal?: AbortSignal }) => {
      if (!alive) return Promise.reject(new DOMException('Ansicht geschlossen', 'AbortError'));
      return data === undefined ? get(path, options?.signal || signal) : post(path, data);
    },
    toast: (text: string, bad = false) => { if (alive) toast(text, bad); },
    action: async (name: string, args: Data = {}) => {
      if (!alive) throw new DOMException('Ansicht geschlossen', 'AbortError');
      const status = host.parentElement?.querySelector<HTMLElement>('[data-management-job]');
      if (status) { status.hidden = false; status.textContent = 'Auftrag wird ausgeführt … Den Verlauf findest du unter Aktivität.'; }
      try {
        const result = await action(name, args);
        if (alive && status) status.textContent = String(result.message || 'Auftrag abgeschlossen.');
        return result;
      } catch (reason) {
        if (alive && status) status.textContent = message(reason);
        throw reason;
      }
    },
    dialogRoot: () => body,
    dialog: (title: string, html: string, submit?: (form: FormData) => Promise<unknown>) => {
      if (!alive || busy) return false;
      // Notify controllers before replacing a dialog. Calling close() here
      // would queue a close event that could erase the newly opened form.
      if (modal.open) modal.dispatchEvent(new Event('close'));
      cleanupDialog?.(); cleanupDialog = undefined;
      const id = ++sequence;
      body.innerHTML = `<header class="management-dialog-heading"><h2 id="management-dialog-title">${esc(title)}</h2>${button('Schließen', 'close', 'aria-label="Schließen"')}</header>${html}<p data-dialog-error role="alert" hidden></p>`;
      if (!modal.open) modal.showModal();
      if (submit) {
        const form = body.querySelector('form');
        form?.addEventListener('submit', async event => {
          event.preventDefault();
          if (busy) return;
          const values = new FormData(form);
          const controls = [...body.querySelectorAll<HTMLInputElement>('input, select, textarea, button')];
          const disabled = controls.map(node => node.disabled);
          busy = true;
          controls.forEach(node => node.disabled = true);
          const error = body.querySelector<HTMLElement>('[data-dialog-error]')!;
          error.hidden = true;
          try {
            await submit(values);
            if (alive && id === sequence) { busy = false; modal.close(); await ctx.refresh?.(); }
          } catch (reason) {
            if (alive && id === sequence) { error.textContent = message(reason); error.hidden = false; }
          } finally {
            busy = false;
            if (alive && id === sequence) controls.forEach((node, index) => node.disabled = disabled[index]);
          }
        }, { signal });
      }
      body.querySelector<HTMLElement>('[autofocus], input:not([type="hidden"]), select, textarea')?.focus();
      return true;
    },
    askYesNo: (question: string) => new Promise<boolean>(resolve => {
      if (!ctx.dialog('Bitte bestätigen', `<p>${esc(question)}</p><div class="form-actions">${button('Abbrechen', 'close')}${button('Ja, fortfahren', 'accept', '', 'primary')}</div>`)) { resolve(false); return; }
      cleanupDialog = () => resolve(false);
      body.querySelector('[data-action="accept"]')!.addEventListener('click', () => { cleanupDialog = undefined; modal.close(); resolve(true); }, { once: true, signal });
    }),
    dispose: () => {
      alive = false; sequence++; cleanupDialog?.(); cleanupDialog = undefined;
      controller.abort(); if (modal.open) modal.close(); body.replaceChildren();
    },
  };
  ctx.confirm = ctx.askYesNo;
  return ctx;
}
