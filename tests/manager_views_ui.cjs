'use strict';
const assert=require('node:assert/strict');
const manager=require('../titan/web/manager_views.js');
class Element {
 constructor(attributes={}) {this.attributes={...attributes};this.dataset={};this.children=[];this.events=new Map();this.hidden=Object.hasOwn(attributes,'hidden');this.value=attributes.value||'';this.textContent='';this.tabIndex=Number(attributes.tabindex||0);for(const [name,value] of Object.entries(attributes))if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value;}
 append(...elements){for(const element of elements){element.parent=this;element.document=this.document;this.children.push(element);}}
 matches(selector){const match=selector.match(/^\[([^=\]]+)(?:="([^\"]*)")?\]$/);return Boolean(match&&Object.hasOwn(this.attributes,match[1])&&(match[2]===undefined||this.attributes[match[1]]===match[2]));}
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 closest(selector){return this.matches(selector)?this:this.parent?.closest(selector)||null;}
 contains(target){return this===target||this.children.some(child=>child.contains(target));}
 setAttribute(name,value){this.attributes[name]=value;}
 getAttribute(name){return this.attributes[name]??null;}
 focus(){this.document.activeElement=this;}
 addEventListener(type,handler){const handlers=this.events.get(type)||new Set();handlers.add(handler);this.events.set(type,handlers);}
 removeEventListener(type,handler){const handlers=this.events.get(type);handlers?.delete(handler);if(!handlers?.size)this.events.delete(type);}
 dispatch(type,attributes={}){const event={target:this,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...attributes};for(let current=this;current;current=current.parent)for(const handler of [...(current.events.get(type)||[])])handler(event);return event;}
}
function fixture(key,owner='owner') {
 const root=new Element(),document={activeElement:null};root.document=document;
 const widget=new Element({'data-manager':key});root.append(widget);
 const ids=key==='vms'?['overview','machines','media','host']:['overview','containers'],active=ids[1];
 const tabs=ids.map(id=>new Element({'data-manager-tab':id,'aria-selected':String(id===active)})),panels=ids.map(id=>new Element({'data-manager-panel':id,...(id===active?{}:{hidden:''})}));widget.append(...tabs,...panels);
 const search=new Element({'data-manager-search-input':''}),status=new Element({'data-manager-state-filter':''}),count=new Element({'data-manager-count':''}),none=new Element({'data-manager-no-results':''}),shortcut=new Element({'data-manager-select':active});
 const items=[new Element({'data-manager-item':'','data-manager-search':'ubuntu server linux cpu 0','data-manager-state':'running'}),new Element({'data-manager-item':'','data-manager-search':'windows workstation microsoft','data-manager-state':'stopped'})];widget.append(search,status,count,none,shortcut,...items);
 const instance=manager.mount(root,{owner});return {root,widget,tabs,panels,search,status,count,none,shortcut,items,document,instance};
}
const session={user:{role:'admin',name:'admin'}};
const vm=(extra={})=>({id:'vm-id',name:'Server',state:'shut off',cpus:2,memory_mb:2048,disk_gb:32,disk_path:'/var/lib/titan/server.qcow2',cpu_ids:[0,2],iso:'ubuntu.iso',boot:'hd',...extra});
const data={available:true,vms:[vm(),vm({id:'running',name:'Active',state:'running',cpus:4,memory_mb:4096,virtual_size:16*1024**3}),vm({id:'paused',state:'paused'})]};
const library={items:[{name:'ubuntu.iso',size:9876,used_by:['Server']},{name:'free.iso',size:42,used_by:[]}]};
const vmHtml=manager.renderVMs({data,library,session,options:{cpu_topology:{cpus:[{id:2,core_type:'efficiency',core_id:1,siblings:[2]},{id:0,core_type:'performance',core_id:0,siblings:[0,1]},{id:1,online:false,core_type:'unknown',siblings:[0,1]}]},storage:[{id:'system',label:'Systemlaufwerk',available:true,path:'/var/lib/titan/vms',free_bytes:42*1024**3}]},status:{memory_total:16*1024**3,cpus:3}});
assert.match(vmHtml,/data-manager="vms"/);assert.match(vmHtml,/role="tablist"/);assert.match(vmHtml,/aria-controls="mv-vms-panel-host"/);assert.match(vmHtml,/data-manager-panel="machines"[^>]*>/);
assert.match(vmHtml,/aria-orientation="horizontal"/);
const cards=[...vmHtml.matchAll(/<article class="vm-list-row vm-machine-card"[\s\S]*?<\/article>/g)].map(match=>match[0]);
assert.equal(cards.length,3);for(const card of cards){assert.match(card,/data-vm-live-compact/);assert.match(card,/CPU live/);assert.match(card,/RAM auf NAS \(RSS\)/);assert.doesNotMatch(card,/vm-row-configuration|vm-row-path|Laufwerk belegt|Laufwerk lesen|vm-sparkline/);assert.match(card,/aria-label="[^"]+: Details öffnen"/);}
assert.match(cards[1],/Messung läuft/);assert.match(cards[1],/<strong>—<\/strong>/,'Unknown resident RAM remains unknown');assert.match(vmHtml,/Aktualisierung alle 5 Sekunden/);
assert.deepEqual(manager.vmResourceSummary(data.vms),{cpus:8,memory:null,disk:80*1024**3,running:1});
assert.match(vmHtml,/Zugewiesene CPUs/);assert.match(vmHtml,/Virtuelle Größe; keine Belegungsmessung/);assert.match(vmHtml,/Ausgeschaltete VMs verbrauchen 0 B/);assert(!vmHtml.includes('data-percent'));assert(!vmHtml.includes('CPU 100%'));
for(const action of ['vm-create','refresh','vm-console','vm-edit','vm-media','vm-backup','vm-remove','vm-backups','vm-force-off','iso-remove'])assert(vmHtml.includes(`data-action="${action}"`),action);
for(const command of ['start','shutdown','reboot','resume','autostart'])assert(vmHtml.includes(`data-command="${command}"`),command);
assert.match(vmHtml,/data-action="iso-remove" data-name="ubuntu.iso" disabled/);assert.match(vmHtml,/data-action="iso-remove" data-name="free.iso" /);assert.match(vmHtml,/id="iso-upload"/);assert.match(vmHtml,/accept="\.iso"/);
assert.match(vmHtml,/data-id="vm-id" data-command="start" /);assert.match(vmHtml,/data-id="running" data-command="shutdown" /);assert.match(vmHtml,/data-id="paused" data-command="resume" /);assert.match(vmHtml,/data-action="vm-edit" data-id="running" disabled/);assert.match(vmHtml,/data-action="vm-remove" data-id="running" disabled/);
assert.match(vmHtml,/P-Kern/);assert.match(vmHtml,/E-Kern/);assert.match(vmHtml,/Typ nicht gemeldet · Offline/);assert.match(vmHtml,/SMT: CPU 1/);assert.match(vmHtml,/42 GiB frei/);
const bad=manager.renderVMs({session,data:{available:false,error:'<script>bad()</script>',warnings:['<img onerror=bad>'],vms:[vm({id:'bad" onclick="bad()',name:'<script>name()</script>',disk_path:'<img src=x onerror=bad>',iso:'<svg onload=bad>',cpu_ids:['<bad>']})]},library:{items:[{name:'"><script>media()</script>',size:1,used_by:['<bad>']} ]}});
assert(!bad.includes('<script>'));assert(!bad.includes('<img'));assert(!bad.includes('onclick="bad'));assert.match(bad,/&lt;script&gt;bad\(\)&lt;\/script&gt;/);assert.match(bad,/data-action="vm-create" disabled/);assert.match(bad,/data-id="bad&quot; onclick=&quot;bad\(\)" data-command="start" disabled/);assert.match(bad,/data-action="component-install" data-component="vms"/);
assert(!manager.renderVMs({data,session:{user:{role:'user'}}}).includes('data-action='));
assert.match(manager.renderVMs({data:{available:true,vms:[]},library:{items:[]},session}),/Noch keine virtuellen Maschinen/);
assert.match(manager.renderVMs({data:{available:true,vms:[]},library:{items:[]},session}),/Keine CPU-Topologie gemeldet/);
const demo=manager.renderVMs({data:{available:true,vms:[vm({state:'running'})]},library,session:{...session,demo:true}});assert.match(demo,/data-action="vm-console" data-id="vm-id" disabled/);
const appData={available:true,installed:[{id:'jellyfin',name:'Jellyfin',state:'running',port:8096,status:'healthy',container:{image:'lscr.io/linuxserver/jellyfin',network_mode:'bridge',networks:[{ipv4:'172.20.0.2'}]}},{id:'cloud',name:'Cloud',state:'exited',port:8443},{id:'failed',name:'Broken',phase:'failed',state:'missing',last_error:'<unsafe>'}]};
const appHtml=manager.renderApps({data:appData,session,connection:app=>app.id==='jellyfin'?'http://192.168.1.2:8096/':'',networkSummary:app=>app.container?.networks?.[0]?.ipv4||'Noch keine Adresse'});
assert.match(appHtml,/data-manager="docker"/);assert.match(appHtml,/href="#apps"/);assert.match(appHtml,/172\.20\.0\.2/);assert.match(appHtml,/href="http:\/\/192\.168\.1\.2:8096\/" target="_blank" rel="noopener"/);assert.match(appHtml,/data-action="app-manage" data-id="jellyfin"/);assert.match(appHtml,/data-action="app-networks"/);assert.match(appHtml,/Fehlgeschlagene Installationen/);assert.match(appHtml,/&lt;unsafe&gt;/);
for(const command of ['start','stop','restart','backup','update','remove'])assert(appHtml.includes(`data-command="${command}"`));
assert.match(appHtml,/data-id="cloud" data-command="restart" disabled/);assert.match(appHtml,/data-id="cloud" data-command="start" /);assert.match(appHtml,/data-id="jellyfin" data-command="stop" /);
const failedRunning=manager.renderApps({data:{available:true,installed:[{id:'broken-running',name:'Broken',phase:'failed',state:'running'}]},session});assert.match(failedRunning,/data-id="broken-running" data-command="start" >Erneut versuchen/);assert.match(failedRunning,/data-id="broken-running" data-command="start" >Starten/);
for(const malicious of ['javascript:alert(1)','https://user:pass@example.org','data:text/html,<svg onload=bad>']){const html=manager.renderApps({data:appData,session,connection:()=>malicious});assert(!html.includes(`href="${malicious}`));}
assert.equal(manager.safeUrl('http://[::1]:80/'),'http://[::1]/');assert.equal(manager.safeUrl('https://example.org/path'),'https://example.org/path');assert.equal(manager.safeUrl('javascript:alert(1)'),'');
const appBad=manager.renderApps({data:{available:false,error:'<script>docker()</script>',installed:[{id:'x" onclick="bad()',name:'<script>name()</script>',state:'running',status:'<bad>',port:'"><img>',container:{network_mode:'<svg>',image:'<img>'}}]},session,connection:()=> 'http://example.org/?x="<img>'});assert(!appBad.includes('<script>'));assert(!appBad.includes('<img>'));assert(!appBad.includes('onclick="bad'));assert.match(appBad,/data-command="stop" disabled/);assert.match(appBad,/Docker-Dienste reparieren/);
assert(!manager.renderApps({data:appData,session:{user:{role:'user'}}}).includes('data-action='));assert.match(manager.renderApps({data:{available:true,installed:[]},session}),/Noch keine Apps installiert/);
// Real listeners switch panels without requests/mutations, filter by all words, and respect keyboard focus.
const first=fixture('vms');assert.equal(first.widget.dataset.managerView,'machines');assert.equal(first.panels[1].hidden,false);assert.equal(first.count.textContent,'2 von 2');assert.equal(first.none.hidden,true);
first.tabs[2].dispatch('click');assert.equal(first.widget.dataset.managerView,'media');assert.equal(first.panels[1].hidden,true);assert.equal(first.panels[2].hidden,false);assert.equal(first.tabs[2].attributes['aria-selected'],'true');assert.equal(first.tabs[2].tabIndex,0);assert.equal(first.tabs[1].tabIndex,-1);
first.tabs[2].dispatch('keydown',{key:'ArrowDown'});assert.equal(first.widget.dataset.managerView,'host');assert.equal(first.document.activeElement,first.tabs[3]);first.tabs[3].dispatch('keydown',{key:'ArrowRight'});assert.equal(first.widget.dataset.managerView,'overview');first.tabs[0].dispatch('keydown',{key:'End'});assert.equal(first.widget.dataset.managerView,'host');first.tabs[3].dispatch('keydown',{key:'Home'});assert.equal(first.widget.dataset.managerView,'overview');assert(!first.tabs[0].dispatch('keydown',{key:'x'}).defaultPrevented);
first.shortcut.dispatch('click');assert.equal(first.widget.dataset.managerView,'machines');assert.equal(first.document.activeElement,first.tabs[1]);
first.search.value='SERVER linux';first.search.dispatch('input');assert.equal(first.count.textContent,'1 von 2');assert.equal(first.items[0].hidden,false);assert.equal(first.items[1].hidden,true);first.status.value='stopped';first.status.dispatch('change');assert.equal(first.count.textContent,'0 von 2');assert.equal(first.none.hidden,false);first.search.value='';first.search.dispatch('input');assert.equal(first.count.textContent,'1 von 2');assert.equal(first.items[0].hidden,true);assert.equal(first.items[1].hidden,false);
// Refresh keeps the same user's selected tab and filters; another user receives defaults.
first.tabs[3].dispatch('click');const second=fixture('vms');assert.equal(first.widget.events.size,0);assert.equal(first.search.events.size,0);assert.equal(second.widget.dataset.managerView,'host');assert.equal(second.status.value,'stopped');assert.equal(second.count.textContent,'1 von 2');const other=fixture('vms','another-user');assert.equal(other.widget.dataset.managerView,'machines');assert.equal(other.status.value,'');assert.equal(other.count.textContent,'2 von 2');
const docker=fixture('docker');assert.equal(docker.widget.dataset.managerView,'containers');assert.equal(docker.count.textContent,'2 von 2');docker.search.value='CPU 0';docker.search.dispatch('input');assert.equal(docker.count.textContent,'1 von 2');assert.equal(docker.instance.select('missing'),false);assert.equal(docker.widget.dataset.managerView,'containers');manager.dispose();assert.equal(docker.widget.events.size,0);assert.equal(docker.search.events.size,0);assert.equal(docker.status.events.size,0);assert.equal(docker.instance.select('overview'),false);assert.equal(manager.mount(new Element()),null);
console.log('Manager VM/Docker rendering, genuine resource summaries, controls and state guards, ISO assignments, hardware topology, text/URL escaping, tabs, keyboard focus, filters, account isolation and listener disposal checks passed.');
