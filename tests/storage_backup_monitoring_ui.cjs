'use strict';
const assert=require('node:assert/strict');
const storage=require('../titan/web/storage_view.js'),backup=require('../titan/web/backup_center.js'),monitor=require('../titan/web/monitoring_center.js'),resources=require('../titan/web/resources.js');
const esc=v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),bytes=v=>v===null?'—':v+' B',button=(label,action,attrs='')=>`<button data-action="${action}" ${attrs}>${label}</button>`,pill=(label)=>`<span>${esc(label)}</span>`,date=n=>String(n);
let html=storage.render({disks:[{name:'/dev/sda',size:1000,type:'disk',model:'SSD <script>'}],volumes:[],pools:[],datasets:[]},[],{data:{disk:'/dev/sda'}},{esc,bytes,button,pill,systemPanel:()=>'<section>Systemdisk 1000</section>'});
for(const title of ['Speicherbereiche','Laufwerke','Wartung','Systemdisk 1000','Systemlaufwerk','SMART-Selbsttests'])assert(html.includes(title),title);
assert(!html.includes('<script>'));assert(!html.includes('ZFS-Prüfstatus'));assert(!html.includes('NaN'));assert(html.includes('Für Ext4 und XFS'));
html=storage.render({disks:[],volumes:[{name:'offline',filesystem:'ext4',mounted:false}],pools:[{name:'tank',health:'ONLINE',used:100,size:1000,free:900}],datasets:[]},[{name:'tank/data@point',created:1000,used:20}],{},{esc,bytes,button,pill});
assert(html.includes('Nicht eingehängt · keine Messwerte'));assert(html.includes('data-storage-command="restore"'));assert(html.includes('data-storage-command="remove-snapshot"'));assert(html.includes('Aktuellen')===false);assert(!html.includes('max="undefined"'));
const schedule=storage.scheduleForm({disks:[{name:'/dev/sda',type:'disk'}],pools:[],datasets:[]});assert(schedule.includes('SMART-Selbsttest'));assert(!schedule.includes('<option value="snapshot"'));assert(!schedule.includes('<option value="scrub"'));
const settings={target:'/media/usb',shares:['docs'],include_config:true,interval:'daily',window_day:0,window_hour:3,retention:7};
html=backup.render({items:[{id:'b-1',type:'shares',created:1000,shares:['docs'],include_config:true,bytes:20}]},settings,[{name:'docs'}],{items:[{path:'/media/usb',label:'USB',backup_eligible:true},{path:'/',label:'System',backup_eligible:false}]},{bytes,date,button});
assert(html.includes('data-backup-wizard'));assert(html.includes('data-backup-command="browse"'));assert(html.includes('value="/media/usb"'));assert(!html.includes('value="/"'));assert(!html.includes('name="confirmation"'));
const delegated=backup.render({items:[{id:'b-1',type:'shares',created:1000,shares:['docs'],include_config:true,bytes:20}]},{...settings,delegated:true,configuration_editable:false},[{name:'docs'}],{items:[]},{bytes,date,button});assert(!delegated.includes('data-backup-wizard'));assert(!delegated.includes('data-action="backup-config-restore"'));assert(delegated.includes('data-backup-command="browse"'));
assert(backup.summary({...settings,auto_backup:true}, {items:[{path:'/media/usb',label:'USB <script>'}]}).includes('&lt;script&gt;'));
 const backupDisk={id:'pool:archive',kind:'pool',label:'Archiv <privat>',path:'/srv/archive',backup_path:'/srv/archive/backups',available:true,status:'ready',free_bytes:4096,capabilities:['files','backups'],backup_eligible:true},localDisk={id:'system',kind:'internal',label:'Interner Speicher',path:'/var/srv/titan',available:true,backup_eligible:false,capabilities:['files']},catalog={storage:[localDisk,backupDisk],items:[localDisk,backupDisk]};
 const nested={...settings,target:'/srv/archive/backups/2026'};html=backup.render({},nested,[{name:'docs'}],catalog,{bytes,date,button});assert.match(html,/value="\/srv\/archive\/backups\/2026" selected >Archiv &lt;privat&gt; \/ 2026/);assert(html.includes('value="/srv/archive/backups"'));assert(!html.includes('value="/srv/archive"'));assert(!html.includes('value="/var/srv/titan"'));assert(backup.summary(nested,catalog).includes('Archiv &lt;privat&gt; / 2026'));
 assert(backup.summary({...settings,target:'/srv/archive/backups-other'},catalog).includes('Kein Ziel ausgewählt'));
 const ineligible={storage:[{...backupDisk,backup_eligible:false}],items:[{...backupDisk,backup_eligible:false}]};html=backup.render({},nested,[],ineligible,{bytes,date,button});assert.match(html,/value="\/srv\/archive\/backups\/2026" selected disabled/);assert(html.includes('Archiv &lt;privat&gt; / 2026 · Nicht verfügbar'));
const alerts=[{id:'resolved',active:false,severity:'critical',last_seen:9999},{id:'warn',active:true,severity:'warning',last_seen:20},{id:'error',active:true,severity:'error',last_seen:10}];
assert.deepEqual(monitor.sortedAlerts(alerts).map(a=>a.id),['error','warn','resolved']);assert(monitor.matches(alerts[0],'resolved'));assert(!monitor.matches(alerts[0],'active'));assert(monitor.matches(alerts[1],'active','warning'));assert(!monitor.matches(alerts[1],'active','error'));
html=monitor.render({alerts:[{...alerts[2],title:'<img src=x>',detail:'Secret <script>',route:'javascript:alert(1)'},{...alerts[1],route:'storage'}],services:{docker:{installed:true,relevant:true,active:true},zfs:{installed:true,relevant:false,active:false}},disks:[]},{password:'never-render-this',password_set:true},{date,button,pill});
assert(!html.includes('<img src=x>'));assert(!html.includes('javascript:'));assert(!html.includes('never-render-this'));assert(html.includes('href="#storage"'));assert(!html.includes('<strong>ZFS</strong>'));assert(html.includes('Gesamter Verlauf'));assert(html.includes('value="starttls"'));assert(!html.includes('value="plain"'));
const status={cpu_percent:10,memory_total:100,memory_occupied:50,storage:{total:1000,used:100,scope:'system'},network_interfaces:[{name:'eth0',receive_bps:1024,transmit_bps:2048}],disk_devices:[{name:'sda',read_bps:2048,write_bps:1024}],network_receive_bps:1024,network_transmit_bps:2048,disk_read_bps:2048,disk_write_bps:1024,status_history:[{time:1000,network_receive_bps:null,network_transmit_bps:null},{time:1005,network_receive_bps:1024,network_transmit_bps:2048},{time:1010,network_receive_bps:null,network_transmit_bps:null},{time:1015,network_receive_bps:2048,network_transmit_bps:1024}]};
html=resources.resourceMetrics(status,{bytes});assert(html.includes('Systemspeicher belegt'));assert(html.includes('Laufwerksaktivität'));assert(html.includes('Netzwerkanschlüsse'));assert(!html.includes('NaN'));assert(!html.includes('Infinity'));assert((resources.ioChart(status.status_history,'network_receive_bps','network_transmit_bps',{bytes}).match(/<circle/g)||[]).length===4,'missing counter samples leave gaps');
assert(!resources.ioMetrics({disk_devices:[],network_interfaces:[]}).includes('metrics-io-panel'));
console.log('Storage/backup/monitoring UI: active hardware, filesystem limits, safe restoration, priority/history filters, hidden SMTP secrets and real I/O charts passed.');
// Exercise the wizard's state transitions and protected refresh guard without
// browser drivers; FormData receives an isolated fixture instead of host DOM.
class Node {
 constructor(dataset={}){this.dataset=dataset;this.hidden=false;this.disabled=false;this.textContent='';this.innerHTML='';this.events=new Map();this.nodes={};this.lists={};this.classes=new Set();this.classList={toggle:(k,v)=>v?this.classes.add(k):this.classes.delete(k)};}
 querySelector(s){return this.nodes[s]||null;}querySelectorAll(s){return this.lists[s]||[];}
 addEventListener(n,f){this.events.set(n,f);}removeEventListener(n,f){if(this.events.get(n)===f)this.events.delete(n);}contains(){return true;}
 hasAttribute(n){return n==='data-backup-next'&&this.next||n==='data-backup-previous'&&this.previous;}closest(){return this;}
 dispatch(n,event={}){return this.events.get(n)?.(event);}
}
(async()=>{
 const original=global.FormData;global.FormData=class{constructor(form){this.values=form.values;}get(k){const v=this.values[k];return Array.isArray(v)?v[0]??null:v??null;}getAll(k){const v=this.values[k];return Array.isArray(v)?v:v===undefined?[]:[v];}has(k){return Object.hasOwn(this.values,k);}};
 try{
  const main=new Node(),surface=new Node(),form=new Node(),status=new Node(),summary=new Node(),previous=new Node(),next=new Node(),save=new Node();next.next=true;previous.previous=true;
  form.values={target:'',shares:[],interval:'daily',window_day:'6',window_hour:'3',retention:'7'};
  main.nodes['[data-backup-center]']=surface;surface.nodes['[data-backup-wizard]']=form;
  form.nodes={'[data-backup-wizard-status]':status,'[data-backup-summary]':summary,'[data-backup-previous]':previous,'[data-backup-next]':next,'[data-backup-save]':save};
  form.lists={'[data-backup-step]':Array.from({length:4},(_,i)=>new Node({backupStep:String(i)})),'[data-backup-step-label]':Array.from({length:4},(_,i)=>new Node({backupStepLabel:String(i)}))};
  let request,refresh=0;const ctx={locations:{items:[{path:'/media/usb',label:'USB'}]},api:async(url,body)=>request={url,body},toast(){},refresh:async()=>{refresh++;}};
  backup.mount(main,ctx);assert(!backup.isEditing());await surface.dispatch('click',{target:next});assert(status.textContent.includes('Mindestens'));assert(!backup.isEditing());
  form.values.shares=['docs'];await surface.dispatch('click',{target:next});assert(backup.isEditing());assert.equal(form.lists['[data-backup-step]'][1].hidden,false);
  await surface.dispatch('click',{target:next});assert(status.textContent.includes('Sicherungsziel'));form.values.target='/media/usb';await surface.dispatch('click',{target:next});
  form.values.retention='0';await surface.dispatch('click',{target:next});assert(status.textContent.includes('365'));form.values.retention='2';await surface.dispatch('click',{target:next});assert(!save.hidden);assert(summary.innerHTML.includes('USB'));
  await form.dispatch('submit',{preventDefault(){}});assert.equal(request.url,'/api/backup/settings');assert.equal(request.body.retention,2);assert.deepEqual(request.body.shares,['docs']);assert.equal(refresh,1);backup.dispose();assert(!backup.isEditing());assert(!form.events.has('submit'));
  const delegatedMain=new Node(),delegatedSurface=new Node();delegatedMain.nodes['[data-backup-center]']=delegatedSurface;backup.mount(delegatedMain,ctx);assert(!backup.isEditing());backup.dispose();
  console.log('Backup wizard state: source/target/retention validation, steps, exact save contract, refresh protection, delegated absence and cleanup passed.');
 }finally{global.FormData=original;}
})().catch(error=>{console.error(error);process.exitCode=1;});
