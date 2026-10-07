'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ui=require('../titan/web/remote_access.js');
const {fixture:domFixture}=require('./desktop_test_dom.cjs');
const data={revision:'revision-one',remote:{enabled:true,public_origin:'https://nas.example.de',connector:'cloudflare',service_url:'http://172.30.0.1:5102',sources:['172.30.0.0/24'],app_urls:{}},connectors:[{id:'cloudflare',name:'Cloudflare <Web>'}],apps:[{id:'photos',name:'Photos <private>'}]};
const state=(phase,extra={})=>({...data,...extra,setup:{phase,running:false,connector:'cloudflare',cloudflare_connected:true,...extra.setup}});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};

// Mount the actual rendered forms. Exact selector matching is important: a
// catch-all matches() mock sends the Advanced form through the token workflow.
function fixture(initial=data){
 const f=domFixture(),scope=f.doc.createElement('section'),calls=[],waits=[],toasts=[],replacements=[];
 f.doc.body.append(scope);let markup=ui.render(initial);
 function hydrate(){
  const panel=scope.querySelector('[data-remote-access]');
  for(const form of panel.querySelectorAll('form')){
   form.elements={};
   for(const control of form.querySelectorAll('input,select')){
    control.value=control.getAttribute('value')||'';control.checked=control.hasAttribute('checked');
    if(control.tagName==='SELECT')control.value=control.querySelector('option[selected]')?.getAttribute('value')||'';
    if(control.getAttribute('name'))form.elements[control.getAttribute('name')]=control;
   }
  }
  Object.defineProperty(panel,'outerHTML',{set(value){markup=value;replacements.push(value);scope.innerHTML=value;hydrate();}});
  const progress=panel.querySelector('[data-tunnel-progress]');
  Object.defineProperty(progress,'outerHTML',{set(value){progress.innerHTML=value;}});
 }
 scope.innerHTML=markup;hydrate();
 const api=(path,body,options)=>{const pending=deferred();calls.push({path,body,options,...pending});return pending.promise;};
 const waitForJob=(accepted,options)=>{const pending=deferred();waits.push({accepted,options,...pending});return pending.promise;};
 const query=selector=>scope.querySelector(selector);
 const submit=selector=>f.doc.dispatch(query(selector),'submit');
 const click=selector=>f.doc.dispatch(query(selector),'click');
 const mount=(extra={})=>ui.mount(scope,{api,waitForJob,toast:message=>toasts.push(message),...extra});
 return {...f,scope,calls,waits,toasts,replacements,query,submit,click,mount,get markup(){return markup;},get controls(){return query('[data-remote-access]').querySelectorAll('button,input,select');}};
}
function request(f,index,path,body){const call=f.calls[index];assert(call,`Missing request ${index}: ${path}`);assert.equal(call.path,path);assert.deepEqual(call.body,body);assert(call.options.signal instanceof AbortSignal);return call;}
async function reply(f,index,value){f.calls[index].resolve(value);await settle();}

async function renderSafety(){
 const markup=ui.render(data);
 assert.match(markup,/http:\/\/172\.30\.0\.1:5102/);assert.match(markup,/Cloudflare &lt;Web&gt;/);assert.match(markup,/Photos &lt;private&gt;/);assert.match(markup,/data-remote-app="photos"/);
 assert.match(ui.render({...data,demo:true}),/name="enabled" checked disabled/);
 assert.match(ui.checks({checked_at:1,checks:[{name:'<route>',ok:false,message:'<blocked>'}]}),/&lt;blocked&gt;/);
 assert.match(ui.progress({phase:'checking',running:true,message:'<checking>'}),/&lt;checking&gt;/);
 const initial=fixture(),configured=fixture(state('needs_route'));
 assert.equal(initial.query('[data-tunnel-form]').elements.public_origin.getAttribute('type'),'url');
 assert.equal(initial.query('[data-tunnel-domain-form]'),null);
 assert.equal(configured.query('[data-tunnel-form]').elements.public_origin.getAttribute('type'),'hidden');
 assert(configured.query('[data-tunnel-domain-form]'),'An existing connector must always offer an editable public address');
 assert.equal(initial.query('[name="token"]').getAttribute('value'),null,'Saved settings must never prefill the token');
 const unsafe=fixture({...data,remote:{...data.remote,public_origin:'https://user:secret@nas.example.de'}});
 assert.equal(unsafe.query('a.button'),null,'An authenticated URL must not become the public access link');
}

async function advancedSave(){
 let f=fixture();f.mount();
 const form=f.query('[data-remote-form]');form.elements.public_origin.value=' https://nas.example.de ';
 f.query('[data-remote-app="photos"]').value=' https://photos.example.de/ ';
 const unused=f.doc.createElement('input');unused.setAttribute('data-remote-app','unused');unused.value=' ';form.append(unused);
 assert(f.submit('[data-remote-form]').defaultPrevented);f.submit('[data-remote-form]');
 assert.equal(f.calls.length,1,'Saving twice must not race firewall and proxy changes');
 request(f,0,'/api/remote-access',{enabled:true,public_origin:'https://nas.example.de',connector:'cloudflare',app_urls:{photos:'https://photos.example.de/'},expected_revision:'revision-one'});
 assert(f.controls.every(node=>node.disabled));
 ui.dispose();assert.equal(f.scope.events.get('submit').length,0);assert.equal(f.scope.events.get('click').length,0);assert(f.calls[0].options.signal.aborted);
 await reply(f,0,data);assert.equal(f.replacements.length,0,'An obsolete save response must not repaint another settings view');
 f=fixture();f.mount();f.submit('[data-remote-form]');f.calls[0].reject(Error('Revision geändert'));await settle();
 assert.equal(f.query('[data-remote-error]').textContent,'Revision geändert');assert.equal(f.query('[data-remote-error]').hidden,false);assert(f.controls.every(node=>!node.disabled));
 const unrelated=f.doc.createElement('form');f.scope.append(unrelated);assert.equal(f.doc.dispatch(unrelated,'submit').defaultPrevented,false);assert.equal(f.calls.length,1,'Unrelated forms must not trigger a remote-access mutation');ui.dispose();
}

async function connectThenAddDomain(){
 const f=fixture({...data,remote:{...data.remote,enabled:false,public_origin:''}});f.mount();
 const token='private-tunnel-token-123',form=f.query('[data-tunnel-form]');form.elements.token.value=` ${token} `;form.elements.public_origin.value=' ';
 assert(f.submit('[data-tunnel-form]').defaultPrevented);f.submit('[data-tunnel-form]');
 request(f,0,'/api/remote-access/tunnel',{token,public_origin:'',expected_revision:'revision-one'});
 assert.equal(f.calls.length,1,'Repeated submission must create only one installation job');
 assert.equal(form.elements.token.value,'','The sensitive input must be cleared synchronously before the POST settles');assert(!f.markup.includes(token));assert(f.controls.every(node=>node.disabled));
 const accepted={job:{id:'tunnel-job-1'}};await reply(f,0,accepted);
 request(f,1,'/api/remote-access',undefined);assert.equal(f.waits.length,0,'The initial progress read precedes job waiting');
 await reply(f,1,state('connecting',{setup:{running:true}}));
 assert.equal(f.waits.length,1);assert.deepEqual(f.waits[0].accepted,accepted);assert(f.waits[0].options.signal instanceof AbortSignal);
 assert.match(f.query('[data-tunnel-progress]').textContent,/öffentlicher Zugang noch nicht bestätigt/);
 f.waits[0].options.onProgress({state:'running'});f.waits[0].options.onProgress({state:'running'});
 assert.equal(f.calls.length,3,'Overlapping job callbacks must share the in-flight progress request');
 request(f,2,'/api/remote-access',undefined);await reply(f,2,state('checking',{setup:{running:true}}));
 assert.match(f.query('[data-tunnel-progress]').textContent,/Öffentlicher Zugang wird geprüft/);
 f.waits[0].resolve({state:'succeeded'});await settle();request(f,3,'/api/remote-access',undefined);
 await reply(f,3,state('needs_domain',{revision:'revision-two',remote:{...data.remote,enabled:false,public_origin:''},setup:{needs_domain:true}}));
 assert.match(f.query('[data-tunnel-progress]').textContent,/Öffentliche Adresse ergänzen/);assert(f.query('[data-tunnel-domain-form]'));assert.equal(f.query('[name="token"]').value,'');assert(!f.markup.includes(token));assert.equal(f.query('[data-remote-diagnose]').disabled,true);
 assert.match(f.toasts.at(-1),/Ergänze jetzt die öffentliche Adresse/);
 const domain=f.query('[data-tunnel-domain-form]');domain.elements.public_origin.value=' https://nas.example.de ';
 f.submit('[data-tunnel-domain-form]');f.submit('[data-tunnel-domain-form]');
 request(f,4,'/api/remote-access',{enabled:true,public_origin:'https://nas.example.de',connector:'cloudflare',app_urls:{},expected_revision:'revision-two'});assert.equal(f.calls.length,5);
 await reply(f,4,state('needs_route',{revision:'revision-three'}));request(f,5,'/api/remote-access/diagnose',{});
 const diagnosis={checked_at:1,message:'Zugang geprüft',checks:[{name:'<route>',ok:true,message:'<reachable>'}]};await reply(f,5,diagnosis);request(f,6,'/api/remote-access',undefined);
 await reply(f,6,state('ready',{revision:'revision-three'}));
 assert(f.query('[data-tunnel-progress]').classList.contains('is-ready'));assert.match(f.markup,/&lt;reachable&gt;/);assert.equal(f.query('a.button').getAttribute('href'),'https://nas.example.de/');assert(f.controls.every(node=>!node.disabled));assert(!f.markup.includes(token));ui.dispose();
}

async function directReadyAndDiagnosis(){
 const f=fixture(state('needs_route'));let defaultWait;
 f.win.TitanJobs={wait(api,job,options){assert.equal(api,f.api);defaultWait={job,options,...deferred()};return defaultWait.promise;}};
 // Exercise the production TitanJobs fallback rather than only the injected waiter.
 const api=(...args)=>{const pending=deferred();f.calls.push({path:args[0],body:args[1],options:args[2],...pending});return pending.promise;};f.api=api;f.mount({api,waitForJob:undefined});
 f.query('[name="token"]').value='renewed-private-token';f.submit('[data-tunnel-form]');
 request(f,0,'/api/remote-access/tunnel',{token:'renewed-private-token',public_origin:'https://nas.example.de',expected_revision:'revision-one'});
 await reply(f,0,{job:{id:'job-ready'}});await reply(f,1,state('checking',{setup:{running:true}}));assert.deepEqual(defaultWait.job,{id:'job-ready'});
 defaultWait.resolve({state:'succeeded'});await settle();await reply(f,2,state('ready',{revision:'ready-revision'}));
 assert(f.query('[data-tunnel-progress]').classList.contains('is-ready'));assert.match(f.toasts.at(-1),/öffentlicher Zugang geprüft/);
 f.click('[data-remote-diagnose]');request(f,3,'/api/remote-access/diagnose',{});await reply(f,3,{checked_at:1,message:'Noch einmal geprüft',checks:[]});request(f,4,'/api/remote-access',undefined);
 await reply(f,4,state('ready',{revision:'diagnosed-revision'}));assert.match(f.query('[data-tunnel-progress]').textContent,/Öffentlicher Zugang geprüft/);
 // The saved revision must come from the latest refresh, not the initial mount.
 f.submit('[data-remote-form]');assert.equal(f.calls[5].body.expected_revision,'diagnosed-revision');ui.dispose();f.calls[5].resolve(data);await settle();
}

async function tokenErrors(){
 const f=fixture();f.mount();const token='PRIVATE-secret-token';f.query('[name="token"]').value=token;f.submit('[data-tunnel-form]');
 f.calls[0].reject(Error(`Connector rejected ${token}; retry ${token} <script>oops</script>`));await settle();request(f,1,'/api/remote-access',undefined);
 await reply(f,1,state('failed'));
 const error=f.query('[data-remote-error]');assert.equal(error.hidden,false);assert.equal(error.textContent,'Connector rejected [Token ausgeblendet]; retry [Token ausgeblendet] <script>oops</script>');assert.equal(error.children.length,0,'Backend errors are text, never injected HTML');assert(!f.markup.includes(token));assert.equal(f.query('[name="token"]').value,'');assert(f.controls.every(node=>!node.disabled));
 f.query('[name="token"]').value=' ';f.submit('[data-tunnel-form]');assert.equal(f.calls.length,2,'An empty token must never create an installation job');
 f.query('[name="token"]').value='retry-secret';f.submit('[data-tunnel-form]');assert.equal(f.calls.length,3,'A failed attempt must allow an explicit retry');
 f.calls[2].reject(Object.assign(Error('aborted'),{name:'AbortError'}));await settle();assert.equal(f.calls.length,3);assert.equal(f.query('[data-remote-error]').hidden,true);ui.dispose();
 const preview=fixture({...data,demo:true});preview.mount();preview.query('[name="token"]').value='demo-token';preview.submit('[data-tunnel-form]');assert.equal(preview.calls.length,0);ui.dispose();
}

async function disposalAndResume(){
 let f=fixture();f.mount();f.query('[name="token"]').value='dispose-before-post';f.submit('[data-tunnel-form]');ui.dispose();await reply(f,0,{job:{id:'obsolete'}});assert.equal(f.calls.length,1);assert.equal(f.waits.length,0);assert.equal(f.replacements.length,0);assert(f.calls[0].options.signal.aborted);
 f=fixture();f.mount();f.query('[name="token"]').value='dispose-during-progress';f.submit('[data-tunnel-form]');await reply(f,0,{job:{id:'obsolete-progress'}});ui.dispose();await reply(f,1,state('checking',{setup:{running:true}}));assert.equal(f.waits.length,0,'Disposal during a progress read must not start a job waiter');assert.equal(f.replacements.length,0);assert(f.calls[1].options.signal.aborted);
 f=fixture();f.mount();f.query('[name="token"]').value='dispose-during-wait';f.submit('[data-tunnel-form]');await reply(f,0,{job:{id:'obsolete-wait'}});await reply(f,1,state('checking',{setup:{running:true}}));ui.dispose();f.waits[0].options.onProgress({state:'running'});f.waits[0].resolve({state:'succeeded'});await settle();assert.equal(f.calls.length,2,'Disposed callbacks must not refresh or repaint');assert(f.waits[0].options.signal.aborted);assert.equal(f.toasts.length,0);assert.equal(f.replacements.length,0);
 f=fixture(state('connecting',{setup:{running:true}}));f.mount();f.query('[name="token"]').value='already-running';f.submit('[data-tunnel-form]');assert.equal(f.calls.length,0,'A running setup must not start another installation');f.advance(1999);assert.equal(f.calls.length,0);f.advance(1);request(f,0,'/api/remote-access',undefined);await reply(f,0,state('ready'));assert(f.query('[data-tunnel-progress]').classList.contains('is-ready'));f.advance(10000);assert.equal(f.calls.length,1,'Polling stops when the resumed job finishes');ui.dispose();
 f=fixture(state('connecting',{setup:{running:true}}));f.mount();ui.dispose();f.advance(10000);assert.equal(f.calls.length,0,'Disposal clears the scheduled resume poll');
 f=fixture(state('connecting',{setup:{running:true}}));f.mount();f.advance(2000);ui.dispose();await reply(f,0,state('ready'));assert.equal(f.replacements.length,0,'An obsolete resume response must not repaint');assert(f.calls[0].options.signal.aborted);
}

function explicitLinks(){
 const context={window:{location:{origin:'http://192.168.1.2'}},URL,console,FormData,setInterval:()=>1,clearInterval(){},setTimeout};vm.createContext(context);vm.runInContext(fs.readFileSync('titan/web/app_networks.js','utf8'),context);
 const app={titan_public_origin:'https://nas.example.de',endpoints:[{scope:'lan',url:'http://192.168.1.2:8080/'},{scope:'public',url:'https://photos.example.de/'}]};
 assert.equal(context.window.TitanNetworks.connection(app),'http://192.168.1.2:8080/');context.window.location.origin='https://nas.example.de';assert.equal(context.window.TitanNetworks.connection(app),'https://photos.example.de/');
 assert.equal(context.window.TitanNetworks.connection({...app,endpoints:app.endpoints.slice(0,1)}),'','Remote clients must not receive an unusable private fallback');assert.equal(context.window.TitanNetworks.connection({...app,web_state:'stopped'}),'');
}

(async()=>{await renderSafety();await advancedSave();await connectThenAddDomain();await directReadyAndDiagnosis();await tokenErrors();await disposalAndResume();explicitLinks();console.log('Remote access UI: mounted token jobs, synchronous token clearing/redaction, duplicate protection, progress/domain/ready transitions, revision-bound Advanced save, polling/disposal and explicit LAN/public links passed.');})().catch(error=>{ui.dispose();console.error(error);process.exitCode=1;});
