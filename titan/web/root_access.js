'use strict';
(function(root){
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 let current=null;
 function render(data={},kind='terminal'){
  const enabled=data.enabled===true;
  return `<div class="root-access-bar ${enabled?'is-root':''}" data-root-access><span><strong>${enabled?(data.demo?'Root-Modus · Demo':'Root-Modus aktiv'):'Geschützter NAS-Modus'}</strong>${enabled?' · <span data-root-countdown></span>':''}</span><div>${enabled&&kind==='files'?'<button type="button" class="button small" data-root-files>Systemdateien öffnen</button>':''}<button type="button" class="button small ${enabled?'danger':''}" data-root-toggle>${enabled?'Root-Modus beenden':'Root-Modus aktivieren'}</button></div></div>`;
 }
 function mount(scope,data,ctx){
  current?.dispose();const bar=scope.querySelector('[data-root-access]');if(!bar)return;
  let alive=true,busy=false,timer=null,checking=false;
  const toggle=bar.querySelector('[data-root-toggle]'),files=bar.querySelector('[data-root-files]');
  async function refresh(){if(!alive)return;await ctx.refresh?.();}
  const enable=()=>{ctx.dialog('Root-Modus aktivieren',`<p>Root hat vollständige Administratorrechte. Systemdateien und Befehle können das NAS verändern. Schreibgeschützte Systembereiche werden nicht automatisch entsperrt; manuelle Änderungen können bei einem Update verloren gehen.</p>${data.demo?'<p class="notice">Isolierte Demo: Es werden keine Root-Befehle auf diesem Rechner ausgeführt.</p>':''}<form><label class="field">Aktuelles Passwort<input type="password" name="password" autocomplete="current-password" required></label>${data.two_factor_required?'<label class="field">Authenticator- oder Wiederherstellungscode<input name="otp" autocomplete="one-time-code" maxlength="64" required></label>':''}<label class="field">Dauer<select name="minutes"><option value="5">5 Minuten</option><option value="15" selected>15 Minuten</option><option value="30">30 Minuten</option></select></label><div class="form-actions"><button type="submit" class="button primary">Root-Modus aktivieren</button><button type="button" class="button" data-action="close">Abbrechen</button></div></form>`,async values=>{await ctx.api('/api/root-access',{password:values.get('password'),...(values.get('otp')?{otp:values.get('otp')}:{}),minutes:Number(values.get('minutes'))});ctx.toast?.('Root-Modus für diese Anmeldung aktiviert.');await refresh();});};
  const click=async()=>{if(busy)return;if(!data.enabled){enable();return;}busy=true;toggle.disabled=true;try{await ctx.api('/api/root-access',{enabled:false});ctx.toast?.('Root-Modus beendet. Root-Terminals wurden geschlossen.');await refresh();}catch(error){ctx.toast?.(error.message,true);}finally{if(alive){busy=false;toggle.disabled=false;}}};
  const openFiles=()=>ctx.openFiles?.();
  const tick=()=>{if(!alive||!data.enabled)return;const remaining=Math.max(0,Math.ceil(Number(data.expires)-Date.now()/1000));const countdown=bar.querySelector('[data-root-countdown]');if(countdown)countdown.textContent=remaining?`${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} Min.`:'wird beendet …';if(!remaining&&!checking){checking=true;void ctx.api('/api/root-access').then(next=>{if(!alive)return;if(!next.enabled)return refresh();data=next;}).catch(()=>refresh()).finally(()=>{checking=false;});}};
  toggle?.addEventListener('click',click);files?.addEventListener('click',openFiles);tick();if(data.enabled)timer=setInterval(tick,1000);
  current={dispose(){alive=false;if(timer!==null)clearInterval(timer);toggle?.removeEventListener('click',click);files?.removeEventListener('click',openFiles);}};return current;
 }
 const api={render,mount,dispose(){current?.dispose();current=null;}};if(root)root.TitanRootAccess=api;if(typeof module==='object')module.exports=api;
})(typeof window==='undefined'?null:window);
