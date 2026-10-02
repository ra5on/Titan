'use strict';
(() => {
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const states=new Map();
 const modes={default:'Standard · eigenes App-Netz',bridge:'Bridge · Docker-Standardnetz',host:'Host · Netzwerk des NAS'};
 function choices(data){return (data.networks||[]).filter(item=>item.selectable&&item.driver==='bridge'&&item.name!=='bridge');}
 function options(data){return Object.entries(modes).map(([value,label])=>`<option value="${value}">${label}</option>`).join('')+choices(data).map(item=>`<option value="network:${esc(item.name)}">${esc(item.name)} · Bridge${item.internal?' · intern':''}</option>`).join('');}
 function installFields(app,data){return `<details class="network-advanced" data-network-install><summary><span>Netzwerk anpassen</span><small>Optional · Standard funktioniert ohne weitere Angaben</small></summary><div class="network-install-body"><div class="field"><label for="app-network-mode">Netzwerk</label><select id="app-network-mode" name="network_mode" data-network-mode>${options(data)}</select></div><div class="field" data-network-ip-field hidden><label for="app-network-ip">Feste Container-IPv4</label><input id="app-network-ip" name="network_ipv4" data-network-ip autocomplete="off" placeholder="Automatisch vergeben" maxlength="15"><small>Optional. Die Adresse muss frei sein und im Subnetz des gewählten Netzes liegen.</small></div><p class="hint" data-network-description role="status"></p><details class="network-create"><summary>Eigenes Bridge-Netz erstellen</summary><div class="form-grid"><div class="field"><label for="network-create-name">Netzname</label><input id="network-create-name" data-network-name maxlength="63" placeholder="z. B. titan-meine-apps" autocomplete="off"></div><div class="field"><label for="network-create-subnet">IPv4-Subnetz</label><input id="network-create-subnet" data-network-subnet placeholder="z. B. 172.30.50.0/24" autocomplete="off"></div><div class="field"><label for="network-create-gateway">Gateway</label><input id="network-create-gateway" data-network-gateway placeholder="Automatisch · erste nutzbare Adresse" autocomplete="off"></div></div><label class="network-check"><input type="checkbox" data-network-internal> Internes Netz · kein normaler Internetzugang für die App</label><p class="hint">Der Netzname beginnt mit titan-. Wähle ein Subnetz, das sich nicht mit deinem LAN, VPN oder einem vorhandenen Docker-Netz überschneidet.</p><button type="button" class="button small" data-network-create>Netz erstellen und auswählen</button><p class="hint" data-network-create-status role="status" aria-live="polite"></p></details>${(data.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}</div></details>`;}
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
  let mappedPort=port.value;
  function reflect(){
   const host=select.value==='host',network=choices(data).find(item=>select.value==='network:'+item.name),staticAddress=Boolean(network?.static_ipv4);
   const wasReadOnly=port.readOnly;
   if(!wasReadOnly)mappedPort=port.value;
   port.readOnly=host&&!app.dynamic_web_port;port.min=host?'1':'1024';
   if(port.readOnly)port.value=String(app.port);else if(!host&&(wasReadOnly||Number(port.value)<1024))port.value=mappedPort;
   ip.disabled=!staticAddress;ipField.hidden=!staticAddress;
   const subnets=network?.subnets?.map(item=>item.subnet+(item.gateway?' · Gateway '+item.gateway:'')).join(', ');
   description.textContent=host?`Die App verwendet direkt das NAS-Netz. Sie besitzt keine eigene Container-IP; Portweiterleitungen entfallen. Webport: ${port.value}. Benötigte Ports müssen auf dem NAS frei sein.`:network?`Netz: ${network.name}. ${subnets||'Kein IPv4-Subnetz bekannt.'}${network.internal?' Internes Netz: Internetzugriff ist eingeschränkt.':''}`:select.value==='bridge'?'Docker vergibt die Container-IP automatisch im eingebauten Bridge-Netz. Apps werden über den veröffentlichten NAS-Port geöffnet.':'Titan erstellt das übliche eigene App-Netz. Docker vergibt die Container-IP automatisch; du öffnest die App über den NAS-Port.';
  }
  const onChange=()=>reflect();select.addEventListener('change',onChange);port.addEventListener('input',onChange);reflect();
  const onCreate=async()=>{
   if(creating)return;
   const name=query('[data-network-name]').value.trim(),subnet=query('[data-network-subnet]').value.trim(),gateway=query('[data-network-gateway]').value.trim();
   if(!name||!subnet){status.textContent='Bitte Netzname und IPv4-Subnetz angeben.';return;}
   const submit=form.querySelector('button[type="submit"]');creating=true;create.disabled=true;if(submit)submit.disabled=true;status.textContent='Netz wird angelegt …';
   try{
    const result=await ctx.api('/api/actions',{operation:'app_network_create',arguments:{name,subnet,...(gateway?{gateway}:{}),internal:query('[data-network-internal]').checked}});
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
  states.set(widget,{dispose(){disposed=true;select.removeEventListener('change',onChange);port.removeEventListener('input',onChange);create.removeEventListener('click',onCreate);}});
 }
 function safeUrl(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:'';}catch{return '';}}
 function connection(app){app=app.container||app;const endpoint=(app.endpoints||[]).find(item=>item.scope==='lan'&&safeUrl(item.url));return endpoint?safeUrl(endpoint.url):'';}
 function summary(app){
  app=app.container||app;
  const nets=app.networks||[],ips=nets.flatMap(item=>[item.ipv4,item.ipv6].filter(Boolean));
  if(app.network_mode==='host'||app.network?.mode==='host')return 'Host-Netz · NAS-Adressen';
  return ips.length?ips.join(' · '):app.state==='running'?'Container-IP nicht verfügbar':'Container-IP nach dem Start';
 }
 function details(app){
  const networks=app.networks||[],addresses=app.host_addresses||[],endpoints=app.endpoints||[];
  return `<section class="app-network-details"><div class="panel-heading"><h3>Netzwerk und Erreichbarkeit</h3><span class="pill gray">${esc(app.network_mode||'Docker')}</span></div><div class="network-address-grid"><article><h4>Container-Adressen</h4>${app.network_mode==='host'?'<p>Host-Netz · die App verwendet die Adressen des NAS.</p>':networks.length?networks.map(item=>`<div class="network-address"><strong>${esc(item.name)}</strong><small>${esc(item.driver||'Docker-Netz')}${item.internal?' · intern':''}</small><code>${esc(item.ipv4||'IPv4 noch nicht vergeben')}</code>${item.ipv6?`<code>${esc(item.ipv6)}</code>`:''}${item.gateway?`<small>Gateway ${esc(item.gateway)}</small>`:''}</div>`).join(''):'<p>Aktuell keine Container-Adresse verfügbar.</p>'}</article><article><h4>NAS-Adressen</h4>${addresses.length?addresses.map(item=>`<div class="network-address"><code>${esc(item.address)}</code><small>${esc(item.interface||'Netzwerkschnittstelle')} · ${esc(item.family||'IP')}</small></div>`).join(''):'<p>Keine NAS-Adresse gemeldet.</p>'}</article></div><h4>App öffnen</h4><div class="network-endpoints">${endpoints.map(item=>{const url=safeUrl(item.url);return url?`<a class="button small" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)} ↗${item.scope==='loopback'?' · nur auf dem NAS':''}</a>`:'';}).join('')||'<p class="hint">Kein erreichbarer Webzugang gemeldet. Bei internen Netzen oder gestoppten Apps ist das normal.</p>'}</div><p class="hint">Öffentliche Internet-IP: ${app.public_ip?esc(app.public_ip):'Nicht ermittelt'}. NAS- und Container-Adressen bedeuten keine automatische Erreichbarkeit aus dem Internet.</p></section>`;
 }
 function inventoryPanel(data){return `<section class="panel"><div class="panel-heading"><h2>Docker-Netzwerke</h2><span class="hint">${(data.networks||[]).length} Netze</span></div><p class="hint">Vorhandene Netze lassen sich bei der App-Installation auswählen. Neue Bridge-Netze legst du dort im Bereich „Netzwerk anpassen“ an.</p><div class="network-inventory">${(data.networks||[]).map(item=>`<article class="network-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.driver)}${item.internal?' · intern':''}${item.managed?' · von Titan angelegt':''}</small></div><div><code>${esc((item.subnets||[]).map(value=>value.subnet).join(', ')||'Kein eigenes Subnetz')}</code><small>${(item.containers||[]).length} Container</small></div>${item.managed?`<button type="button" class="button small danger" data-action="app-network-remove" data-name="${esc(item.name)}" ${(item.containers||[]).length?'disabled':''}>Entfernen</button>`:''}</article>`).join('')||'<p>Keine Netze vorhanden.</p>'}</div>${(data.warnings||[]).map(message=>`<p class="hint">${esc(message)}</p>`).join('')}</section>`;}
 window.TitanNetworks={installFields,installArguments,mountInstall,disposeWithin,details,inventoryPanel,summary,connection,safeUrl,options};
})();
