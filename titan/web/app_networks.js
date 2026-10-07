'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const states=new Map();
 const modes={default:'Standard · eigenes App-Netz',bridge:'Bridge · Docker-Standardnetz',host:'Host · Netzwerk des NAS'};
 function choices(data){return (data.networks||[]).filter(item=>item.selectable&&item.driver==='bridge'&&item.name!=='bridge');}
 function options(data){return Object.entries(modes).map(([value,label])=>`<option value="${value}">${label}</option>`).join('')+choices(data).map(item=>`<option value="network:${esc(item.name)}">${esc(item.name)} · Bridge${item.internal?' · intern':''}</option>`).join('');}
 const networkIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="8" y="3" width="8" height="5" rx="1.2"/><path d="M12 8v5M5 13h14M5 13v3m14-3v3"/><rect x="2" y="16" width="6" height="5" rx="1.2"/><rect x="16" y="16" width="6" height="5" rx="1.2"/></svg>';
 function createFields(required=true){return `<label class="field">Netzwerkname<input name="name" data-network-name maxlength="63" ${required?'required':''} placeholder="z. B. meine-apps" autocomplete="off" ${required?'pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}"':''}></label><p class="hint">Bridge-Netzwerk · Apps in diesem Netz können sich über ihren Containernamen erreichen. Titan wählt automatisch ein freies privates Subnetz.</p><details class="network-create-advanced"><summary>Erweiterte Einstellungen</summary><div class="form-grid"><label class="field">IPv4-Subnetz<input name="subnet" data-network-subnet placeholder="Automatisch · z. B. 172.30.50.0/24" autocomplete="off"></label><label class="field">Gateway<input name="gateway" data-network-gateway placeholder="Automatisch" autocomplete="off"></label></div><label class="network-check"><input type="checkbox" name="internal" data-network-internal> Nur interne Kommunikation · kein normaler Internetzugang</label><p class="hint">Ein eigenes Subnetz darf sich nicht mit dem LAN, VPN oder vorhandenen Docker-Netzen überschneiden. Titan prüft diese Überschneidungen vor dem Anlegen.</p></details>`;}
 function createArguments(values){const name=String(values.get('name')||'').trim(),subnet=String(values.get('subnet')||'').trim(),gateway=String(values.get('gateway')||'').trim();if(!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/.test(name))throw Error('Bitte einen Netzwerknamen aus 1–63 Buchstaben, Ziffern, Punkt, _ oder - wählen.');if(gateway&&!subnet)throw Error('Ein eigenes Gateway benötigt ein IPv4-Subnetz.');return {name,...(subnet?{subnet}:{}),...(gateway?{gateway}:{}),internal:values.has('internal')};}
 function createDialog(ctx,onCreated=()=>{}){ctx.dialog('Netzwerk erstellen',`<form>${createFields()}<div class="form-actions"><button type="button" class="button" data-action="close">Abbrechen</button><button type="submit" class="button primary">Erstellen</button></div></form>`,async values=>{const result=await ctx.action('app_network_create',createArguments(values),{wait:true});await onCreated(result);return result;});}
 function installFields(app,data){return `<details class="network-advanced" data-network-install><summary><span>Netzwerk anpassen</span><small>Optional · Standard funktioniert ohne weitere Angaben</small></summary><div class="network-install-body"><div class="field"><label for="app-network-mode">Netzwerk</label><select id="app-network-mode" name="network_mode" data-network-mode>${options(data)}</select></div><div class="field" data-network-ip-field hidden><label for="app-network-ip">Feste Container-IPv4</label><input id="app-network-ip" name="network_ipv4" data-network-ip autocomplete="off" placeholder="Automatisch vergeben" maxlength="15"><small>Optional. Die Adresse muss frei sein und im Subnetz des gewählten Netzes liegen.</small></div><p class="hint" data-network-description role="status"></p><details class="network-create"><summary>Eigenes Bridge-Netz erstellen</summary>${createFields(false)}<button type="button" class="button small" data-network-create>Netz erstellen und auswählen</button><p class="hint" data-network-create-status role="status" aria-live="polite"></p></details>${(data.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}</div></details>`;}
 function installArguments(app,data){
  const selected=String(data.get('network_mode')||'default'),ip=String(data.get('network_ipv4')||'').trim();
  if(selected==='default')return {};
  if(selected==='host')return {network:{mode:'host'}};
  if(selected==='bridge')return {network:{mode:'bridge'}};
  if(!selected.startsWith('network:')||!selected.slice(8))throw new Error('Bitte ein verfügbares Docker-Netz auswählen.');
  const network={mode:'bridge',name:selected.slice(8)};
  if(ip){if(!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)||ip.split('.').some(part=>Number(part)>255))throw new Error('Bitte eine gültige Container-IPv4-Adresse eingeben.');network.ipv4_address=ip;}
  return {network};
 }
 function disposeWithin(root){for(const [widget,state] of states)if(root===widget||root?.contains?.(widget)){state.dispose();states.delete(widget);}}
 function mountInstall(root,app,inventory,ctx){
  const widget=root.querySelector('[data-network-install]');if(!widget)return;
  let data=inventory,disposed=false,creating=false;
  const query=selector=>widget.querySelector(selector),select=query('[data-network-mode]'),ip=query('[data-network-ip]'),ipField=query('[data-network-ip-field]'),description=query('[data-network-description]');
  const form=widget.closest('form'),port=form.querySelector('[name="port"]'),create=query('[data-network-create]'),status=query('[data-network-create-status]');
  let mappedPort=port?.value||'';
  function reflect(){
   const host=select.value==='host',network=choices(data).find(item=>select.value==='network:'+item.name),staticAddress=Boolean(network?.static_ipv4);
   if(port){const wasReadOnly=port.readOnly;
    if(!wasReadOnly)mappedPort=port.value;
    port.readOnly=host&&!app.dynamic_web_port;port.min=host?'1':'1024';
    if(port.readOnly)port.value=String(app.port);else if(!host&&(wasReadOnly||Number(port.value)<1024))port.value=mappedPort;
   }
   ip.disabled=!staticAddress;ipField.hidden=!staticAddress;
   const subnets=network?.subnets?.map(item=>item.subnet+(item.gateway?' · Gateway '+item.gateway:'')).join(', ');
   description.textContent=host?`Die App verwendet direkt das NAS-Netz. Sie besitzt keine eigene Container-IP; Portweiterleitungen entfallen. Webport: ${port?.value||'Keiner · Hintergrunddienst'}. Benötigte Ports müssen auf dem NAS frei sein.`:network?`Netz: ${network.name}. ${subnets||'Kein IPv4-Subnetz bekannt.'}${network.internal?' Internes Netz: Internetzugriff ist eingeschränkt.':''}`:select.value==='bridge'?'Docker vergibt die Container-IP automatisch im eingebauten Bridge-Netz. Apps werden über den veröffentlichten NAS-Port geöffnet.':'Titan erstellt das übliche eigene App-Netz. Docker vergibt die Container-IP automatisch; du öffnest die App über den NAS-Port.';
  }
  const onChange=()=>reflect();select.addEventListener('change',onChange);port?.addEventListener('input',onChange);select.value=app.default_network||'default';reflect();
  const onCreate=async()=>{
   if(creating)return;
   const name=query('[data-network-name]').value.trim(),subnet=query('[data-network-subnet]').value.trim(),gateway=query('[data-network-gateway]').value.trim();
   if(!name){status.textContent='Bitte einen Netzwerknamen angeben.';return;}
   const submit=form.querySelector('button[type="submit"]');creating=true;create.disabled=true;if(submit)submit.disabled=true;status.textContent='Netz wird angelegt …';
   try{
    const result=await ctx.api('/api/actions',{operation:'app_network_create',arguments:{name,...(subnet?{subnet}:{}),...(gateway?{gateway}:{}),internal:query('[data-network-internal]').checked}});
    const deadline=Date.now()+120000;
    while(!disposed){
     const jobs=await ctx.api('/api/jobs'),job=jobs.find(item=>item.id===result.job);
     if(job?.status==='failed')throw new Error(job.result?.error||'Netz konnte nicht angelegt werden.');
     if(job?.status==='completed')break;
     if(Date.now()>deadline)throw new Error('Das Anlegen läuft noch. Prüfe den Auftrag und lade die Netzliste später erneut.');
     await new Promise(resolve=>setTimeout(resolve,1000));
    }
    if(disposed)return;
    data=await ctx.api('/api/app-networks');if(disposed)return;
    select.innerHTML=options(data);select.value='network:'+name;
    if(select.value!=='network:'+name)throw new Error('Das erstellte Netz ist noch nicht verfügbar. Installation erneut öffnen.');
    reflect();status.textContent=`${name} ist erstellt und ausgewählt.`;
   }catch(error){if(!disposed)status.textContent=error.message;}
   finally{creating=false;if(!disposed){create.disabled=false;if(submit)submit.disabled=false;}}
  };
  create.addEventListener('click',onCreate);
  states.set(widget,{dispose(){disposed=true;select.removeEventListener('change',onChange);port?.removeEventListener('input',onChange);create.removeEventListener('click',onCreate);}});
 }
 function safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:'';}catch{return '';}}
 function connection(app){app=app.container||app;if(app.web_available===false||app.web_state&&app.web_state!=='ready')return '';const remote=app.titan_public_origin&&window.location?.origin===app.titan_public_origin;const endpoint=(app.endpoints||[]).find(item=>item.scope===(remote?'public':'lan')&&safeUrl(item.url));return endpoint?safeUrl(endpoint.url):'';}
 function summary(app){
  app=app.container||app;
  const nets=app.networks||[],ips=nets.flatMap(item=>[item.ipv4,item.ipv6].filter(Boolean));
  if(app.network_mode==='host'||app.network?.mode==='host')return 'Host-Netz · NAS-Adressen';
  return ips.length?ips.join(' · '):app.state==='running'?'Container-IP nicht verfügbar':'Container-IP nach dem Start';
 }
 function details(app){
  const networks=app.networks||[],addresses=app.host_addresses||[],endpoints=app.endpoints||[];
  return `<section class="app-network-details"><div class="panel-heading"><h3>Netzwerk und Erreichbarkeit</h3><span class="pill gray">${esc(app.network_mode||'Docker')}</span></div><div class="network-address-grid"><article><h4>Container-Adressen</h4>${app.network_mode==='host'?'<p>Host-Netz · die App verwendet die Adressen des NAS.</p>':networks.length?networks.map(item=>`<div class="network-address"><strong>${esc(item.name)}</strong><small>${esc(item.driver||'Docker-Netz')}${item.internal?' · intern':''}</small><code>${esc(item.ipv4||'IPv4 noch nicht vergeben')}</code>${item.ipv6?`<code>${esc(item.ipv6)}</code>`:''}${item.gateway?`<small>Gateway ${esc(item.gateway)}</small>`:''}</div>`).join(''):'<p>Aktuell keine Container-Adresse verfügbar.</p>'}</article><article><h4>NAS-Adressen</h4>${addresses.length?addresses.map(item=>`<div class="network-address"><code>${esc(item.address)}</code><small>${esc(item.interface||'Netzwerkschnittstelle')} · ${esc(item.family||'IP')}</small></div>`).join(''):'<p>Keine NAS-Adresse gemeldet.</p>'}</article></div><h4>App öffnen</h4>${app.web_message?`<p class="hint" role="status">${esc(app.web_message)}</p>`:''}<div class="network-endpoints">${endpoints.filter(item=>['lan','public'].includes(item.scope)).map(item=>{const url=app.web_available!==false&&(!app.web_state||app.web_state==='ready')?safeUrl(item.url):'';return url?`<a class="button small" href="${esc(url)}" target="_blank" rel="noopener">${item.scope==='public'?'Öffentlich · ':''}${esc(url)} ↗</a>`:'';}).join('')||'<p class="hint">Kein erreichbarer Webzugang gemeldet. Bei internen Netzen oder gestoppten Apps ist das normal.</p>'}</div><p class="hint">Öffentliche Internet-IP: ${app.public_ip?esc(app.public_ip):'Nicht ermittelt'}. NAS- und Container-Adressen bedeuten keine automatische Erreichbarkeit aus dem Internet.</p></section>`;
 }
 function removable(item){return item.removable===true||(item.removable===undefined&&item.managed&&item.driver==='bridge'&&!['bridge','host','none','ingress','docker_gwbridge'].includes(item.name)&&!(item.containers||[]).length&&!(item.used_by||[]).length);}
 function deletionReason(item){return item.deletion_reason||(!item.managed?'System- oder App-Netzwerk':(item.containers||[]).length||(item.used_by||[]).length?'Wird noch von Containern oder einem App-Paket verwendet':'');}
 function inventoryPanel(data,{toolbar=true,selected=null}={}){const networks=data.networks||[],item=networks.find(value=>value.name===selected);return `<section class="network-manager" data-network-manager>${toolbar?`<div class="network-manager-toolbar"><strong>Netzwerke</strong><div><button type="button" class="button small primary" data-network-action="create" ${data.available===false?'disabled':''}>Erstellen</button><button type="button" class="button small" data-network-action="refresh">Aktualisieren</button></div></div>`:''}<p class="hint network-manager-description">Wähle ein Netzwerk für Details. Eigene Bridge-Netze stehen beim Erstellen eines Containers oder bei der App-Installation zur Auswahl.</p><div class="network-table-wrap"><table class="network-table"><thead><tr><th>Name</th><th>Treiber</th><th>Subnetz</th><th>Verwendung</th><th><span class="sr-only">Aktionen</span></th></tr></thead><tbody>${networks.map(value=>`<tr class="${value.name===selected?'is-selected':''}"><td><button type="button" class="network-select" data-network-action="select" data-name="${esc(value.name)}" aria-pressed="${value.name===selected}">${networkIcon}<span><strong>${esc(value.name)}</strong><small>${value.managed?'Eigenes Netz':'System / App'}${value.internal?' · intern':''}</small></span></button></td><td data-label="Treiber">${esc(value.driver||'—')}</td><td data-label="Subnetz"><code>${esc((value.subnets||[]).map(subnet=>subnet.subnet).join(', ')||'Kein eigenes Subnetz')}</code></td><td data-label="Verwendung">${(value.containers||[]).length} Container${(value.used_by||[]).length?` · ${value.used_by.length} Apps`:''}</td><td class="network-table-actions"><button type="button" class="button small danger" data-network-action="remove" data-name="${esc(value.name)}" ${!removable(value)||data.available===false?'disabled':''} title="${esc(deletionReason(value)||'Ungenutztes eigenes Netz entfernen')}">Entfernen</button>${deletionReason(value)?`<small>${esc(deletionReason(value))}</small>`:''}</td></tr>`).join('')||'<tr><td colspan="5">Keine Netzwerke vorhanden.</td></tr>'}</tbody></table></div>${item?`<section class="network-selected-detail"><div class="panel-heading"><h3>${networkIcon}${esc(item.name)}</h3><button type="button" class="button small" data-network-action="close">Details schließen</button></div><dl><dt>Modus</dt><dd>${esc(item.driver)}${item.internal?' · nur interne Kommunikation':' · externe Verbindungen erlaubt'}</dd><dt>IP-Vergabe</dt><dd>${(item.subnets||[]).map(value=>`<span>${esc(value.subnet)}${value.gateway?` · Gateway ${esc(value.gateway)}`:''}</span>`).join('')||'Verwendet das NAS-Netz bzw. keine eigene Adresse'}</dd><dt>Container</dt><dd>${(item.containers||[]).map(value=>`<span><strong>${esc(value.name)}</strong> ${esc(value.ipv4||value.ipv6||'Adresse nach dem Start')}${value.state==='exited'?' · gestoppt':''}</span>`).join('')||'Keine Container verbunden'}</dd><dt>App-Pakete</dt><dd>${esc((item.used_by||[]).join(', ')||'Keine App-Pakete zugeordnet')}</dd></dl>${deletionReason(item)?`<p class="hint">${esc(deletionReason(item))}. Zugeordnete Container oder App-Pakete zuerst entfernen oder mit einem anderen Netz neu erstellen.</p>`:''}</section>`:'<p class="network-selection-hint">Ein Netzwerk anklicken, um Gateway und verbundene Container zu sehen.</p>'}${(data.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}<p class="network-manager-status" role="status" aria-live="polite" data-network-manager-status></p></section>`;}
 function mountInventory(root,inventory,ctx,{toolbar=true,selected=null,onSelect=()=>{},onChanged=()=>{}}={}){let widget=root.querySelector('[data-network-manager]');if(!widget)return;let data=inventory,chosen=selected,busy=false,disposed=false,message='';
  function render(){if(disposed)return;const wrapper=widget.parentElement;widget.outerHTML=inventoryPanel(data,{toolbar,selected:chosen});widget=wrapper.querySelector('[data-network-manager]');const status=widget.querySelector('[data-network-manager-status]');if(status)status.textContent=message;root.querySelectorAll('[data-network-action]').forEach(node=>{if(busy)node.disabled=true;});}
  async function refresh(){data=await ctx.api('/api/app-networks');if(disposed)return;if(!data.networks?.some(value=>value.name===chosen))chosen=null;render();await onChanged(data);}
  const click=async event=>{const control=event.target.closest?.('[data-network-action]');if(!control||!root.contains(control)||busy||control.disabled)return;const op=control.dataset.networkAction,name=control.dataset.name;message='';try{
   if(op==='select'||op==='close'){chosen=op==='select'?name:null;onSelect(chosen);render();return;}
   if(op==='create'){createDialog(ctx,async result=>{chosen=result.network?.name||null;onSelect(chosen);await refresh();});return;}
   if(op==='remove'){const item=(data.networks||[]).find(value=>value.name===name);if(!item||!removable(item))throw Error(deletionReason(item||{})||'Dieses Netzwerk kann nicht entfernt werden.');if(!await ctx.askYesNo(`Das ungenutzte Netzwerk „${name}“ entfernen?`))return;busy=true;render();await ctx.action('app_network_remove',{name,confirmation:name},{wait:true});}
   await refresh();
  }catch(error){message=error.message;ctx.toast(error.message,true);if(!disposed){const status=root.querySelector('[data-network-manager-status]');if(status)status.textContent=error.message;}}finally{busy=false;if(!disposed)render();}};
  root.addEventListener('click',click);states.set(root,{dispose(){disposed=true;root.removeEventListener('click',click);}});
 }
 window.TitanNetworks={installFields,installArguments,mountInstall,disposeWithin,details,inventoryPanel,mountInventory,createDialog,createArguments,removable,deletionReason,summary,connection,safeUrl,options};
})();
