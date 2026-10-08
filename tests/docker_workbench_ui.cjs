'use strict';
const assert=require('node:assert/strict');const ui=require('../titan/web/docker_workbench.js');
assert.deepEqual(ui.containerStorageConfig('system'),{storage_id:'system'});assert.deepEqual(ui.containerStorageConfig('volume:photos'),{storage_id:'volume:photos'});assert.deepEqual(ui.containerStorageConfig('@docker-volume:photos'),{volume:'photos'});assert.deepEqual(ui.containerStorageConfig(''),{});assert.throws(()=>ui.containerStorageConfig('/etc'),/gültigen Speicher/);
assert.deepEqual(ui.parsePorts('8080:80\n8443:443/tcp\n5353:5353/udp'),[{published:8080,target:80,protocol:'tcp'},{published:8443,target:443,protocol:'tcp'},{published:5353,target:5353,protocol:'udp'}]);
assert.deepEqual(ui.parsePorts('65535:1/udp'),[{published:65535,target:1,protocol:'udp'}]);
for(const port of ['0:80','80:0','65536:80','80:65536'])assert.throws(()=>ui.parsePorts(port),/zwischen 1 und 65535/);
assert.throws(()=>ui.parsePorts('$(id)'));assert.throws(()=>ui.parseEnv('SECRET=a\nSECRET=b'));
const env=ui.parseEnv('KEY=a=b\n__proto__=safe');assert.equal(env.KEY,'a=b');assert.equal(env.__proto__,'safe');assert.equal(Object.getPrototypeOf(env),Object.prototype);
assert.match(ui.ports({'80/tcp':[{'HostIp':'0.0.0.0','HostPort':'8080'}]}),/8080 → 80/);
assert.match(ui.metric({cpu_percent:0,memory_bytes:0},String),/RAM <strong>0/);
assert.match(ui.metric({},String),/RAM <strong>—/);
const live=require('../titan/web/vm_live.js');const render=vm=>live.render(vm,{bytes:v=>String(v),esc:String});
const stopped=render({state:'shut off',cpus:2,memory_mb:4096,metrics:{cpu_percent:97,memory_resident_bytes:9999999,memory_guest_used_bytes:9999999}});
assert.match(stopped,/CPU live[^]*?<strong>0 %/);assert.match(stopped,/RAM auf NAS \(RSS\)<\/small><strong>0<\/strong>/);assert(!stopped.includes('9999999'));assert(!stopped.includes('zugewiesen'));
assert.match(render({state:'running',cpus:2,memory_mb:4096,metrics:{memory_resident_bytes:12345,memory_guest_used_bytes:1}}),/strong>12345/);
console.log('Docker workbench parser and stopped VM resource regressions passed.');
const containers=[{id:'a',name:'Alpha',image:'nginx',state:'running',project:'web',health:'healthy',networks:[]},{id:'b',name:'Beta',image:'redis',state:'exited',project:'web',networks:[]},{id:'c',name:'Gamma',image:'busybox',state:'running',health:'unhealthy',networks:[]}];
assert.deepEqual(ui.filtered(containers,'web','all','za').map(c=>c.id),['b','a']);
assert.deepEqual(ui.filtered(containers,'','stopped').map(c=>c.id),['b']);
assert.deepEqual(ui.filtered(containers,'','unhealthy').map(c=>c.id),['c']);
assert.equal(ui.stacks(containers)[0][1].length,2);
assert.equal(ui.totals(containers,{a:{memory_bytes:100},b:{memory_bytes:999},c:{memory_bytes:50}}).memory,150);
assert.equal(ui.totals(containers,{a:{memory_bytes:100}}).memory,null);
assert.equal(ui.totals([containers[1]],{}).memory,0);
console.log('Docker filters, Compose grouping and actual RAM totals passed.');

const web={state:'running',managed_app:'syncthing',web_port:8384,web_available:true,web_state:'ready',endpoints:[{scope:'lan',url:'http://192.168.10.18:18084'}],ports:{'22000/tcp':[{HostPort:'22000',HostIp:'0.0.0.0'}],'8384/tcp':[{HostPort:'18084',HostIp:'0.0.0.0'}]}};
assert.equal(ui.webLink(web,'tunnel.example'),'http://192.168.10.18:18084/');
assert.equal(ui.webLink({...web,network_mode:'host',ports:{},endpoints:[{scope:'lan',url:'http://192.168.10.18:8384'}]},'tunnel.example'),'http://192.168.10.18:8384/');
assert.equal(ui.webLink({...web,network_mode:'host',ports:{},endpoints:[{scope:'lan',url:'http://[fd00::18]:9090'}]},'tunnel.example'),'http://[fd00::18]:9090/');
assert.equal(ui.webLink({...web,state:'exited'},'nas.local'),'');
assert.equal(ui.webLink({...web,web_available:false,web_state:'initializing'},'nas.local'),'');
assert.equal(ui.webLink({...web,endpoints:[{scope:'loopback',url:'http://127.0.0.1:8384'}]},'nas.local'),'');
assert.equal(ui.webLink({...web,web_port:null,web_available:false,web_state:'background'},'nas.local'),'');
assert.equal(ui.webLink({...web,endpoints:[{scope:'lan',url:'javascript:alert(1)'}]},'nas.local'),'');
assert.equal(ui.webLink({state:'running',ports:{'80/tcp':[{HostPort:'8080',HostIp:'0.0.0.0'}]}},'tunnel.example'),'');
console.log('Docker confirmed endpoints, headless/initializing states and no guessed tunnel links passed.');
// Reveal only the navigation's selected tab; never scroll the page/window.
let tabBounds={left:450,right:540};
const nav={scrollWidth:600,clientWidth:300,scrollLeft:0,getBoundingClientRect:()=>({left:0,right:300}),querySelector:()=>({getBoundingClientRect:()=>tabBounds})};
ui.revealSelectedTab(nav);assert.equal(nav.scrollLeft,240);
tabBounds={left:-90,right:0};ui.revealSelectedTab(nav);assert.equal(nav.scrollLeft,150);
tabBounds={left:30,right:120};ui.revealSelectedTab(nav);assert.equal(nav.scrollLeft,150);
nav.clientWidth=600;ui.revealSelectedTab(nav);assert.equal(nav.scrollLeft,150);
console.log('Selected mobile Docker tab remains visible without global page scrolling.');
// Keyboard navigation is shared by the vertical sidebar and compact mobile tabs.
// Inventory polling retains the selected tab or action focus without moving scroll.
async function keyboardAndFocus(){
 const vm=require('node:vm'),fs=require('node:fs'),{fixture}=require('./desktop_test_dom.cjs'),f=fixture(),container=f.doc.createElement('section');f.doc.body.append(container);let poll,horizontal=false;
 const originalQuery=container.querySelector.bind(container);container.querySelector=selector=>selector.startsWith('.engine-navigation ')?originalQuery('.engine-navigation')?.querySelector(selector.slice('.engine-navigation '.length)):originalQuery(selector);
 const originalRects=f.Element.prototype.getClientRects;f.Element.prototype.getClientRects=()=>[{}];f.win.getComputedStyle=()=>({flexDirection:horizontal?'row':'column'});f.win.TitanArtwork={render:()=>''};
 const data={available:true,containers:[{id:'a',name:'Alpha',state:'running',health:'healthy',image:'nginx',networks:[],ports:{}}],images:[],volumes:[],networks:[]};
 const sandbox={window:f.win,location:{hostname:'nas.local'},setInterval:callback=>{poll=callback;return 1;},clearInterval:()=>{poll=null;},Map,Set,Number,String,Object,Promise};vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/docker_workbench.js'),'utf8'),sandbox);
 const controller=f.win.TitanDocker,selected=()=>container.querySelectorAll('[role="tab"]').find(node=>node.getAttribute('aria-selected')==='true');
 try{
  await controller.mount(container,{api:async path=>path==='/api/docker-engine'?JSON.parse(JSON.stringify(data)):{containers:{}},action:async()=>({ok:true}),dialog(){},askYesNo:async()=>true,toast(){},bytes:String});
  assert.match(container.innerHTML,/Läuft · Bereit/);assert.doesNotMatch(container.innerHTML,/>[^<]*healthy/);let tab=selected();assert.equal(tab.dataset.engineTab,'overview');assert.equal(tab.getAttribute('tabindex'),'0');assert.equal(container.querySelectorAll('[role="tab"]').filter(node=>node.getAttribute('tabindex')==='0').length,1);assert.equal(container.querySelector('[role="tabpanel"]').getAttribute('aria-labelledby'),'engine-tab-overview');assert.equal(container.querySelector('[role="tablist"]').getAttribute('aria-orientation'),'vertical');
  tab.focus();assert(f.doc.dispatch(tab,'keydown',{key:'ArrowDown'}).defaultPrevented);assert.equal(selected().dataset.engineTab,'stacks');assert.equal(f.doc.activeElement,selected());
  const content=container.querySelector('.engine-content');content.scrollTop=123;data.images.push({Repository:'busybox',Tag:'stable'});await poll();assert.equal(f.doc.activeElement,selected(),'Changed inventory preserves tab focus');assert.equal(container.querySelector('.engine-content').scrollTop,123,'Focus restoration never resets workspace scroll');
  horizontal=true;f.doc.dispatch(selected(),'keydown',{key:'End'});assert.equal(selected().dataset.engineTab,'volumes');assert.equal(container.querySelector('[role="tablist"]').getAttribute('aria-orientation'),'horizontal');f.doc.dispatch(selected(),'keydown',{key:'ArrowRight'});assert.equal(selected().dataset.engineTab,'overview','Arrow navigation wraps');f.doc.dispatch(selected(),'keydown',{key:'ArrowLeft'});assert.equal(selected().dataset.engineTab,'volumes');f.doc.dispatch(selected(),'keydown',{key:'Home'});assert.equal(selected().dataset.engineTab,'overview');
  const refresh=container.querySelectorAll('[data-engine-action]').find(node=>node.dataset.engineAction==='refresh');refresh.focus();await poll();assert.equal(f.doc.activeElement,refresh,'An unchanged inventory does not replace action buttons');data.images.push({Repository:'alpine',Tag:'stable'});await poll();assert.equal(f.doc.activeElement.dataset.engineAction,'refresh','A changed inventory restores action focus');assert.equal(f.doc.activeElement.disabled,false);
  controller.dispose();assert.equal(container.events.get('keydown').length,0);
 }finally{controller.dispose();if(originalRects)f.Element.prototype.getClientRects=originalRects;else delete f.Element.prototype.getClientRects;}
 console.log('Docker keyboard tabs, roving focus, pane labels, responsive orientation and polling focus/scroll preservation passed.');
}
keyboardAndFocus().catch(error=>{console.error(error);process.exitCode=1;});
