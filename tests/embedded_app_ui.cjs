'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve};}

function fixture({hash='#docker?app=missing',signedIn=true,pauseNavigation=false,navigationError=false}={}){
 const nodes=new Map(),listeners=new Map(),messages=[],managed=[],toasts=[],requests=[],trace=[],auth=[];
 let navigationGate=pauseNavigation?deferred():null;
 function node(selector){if(!nodes.has(selector))nodes.set(selector,{dataset:{},classList:{toggle(){}},hidden:false,attributes:{},setAttribute(name,value){this.attributes[name]=value;},addEventListener(){}});return nodes.get(selector);}
 const location={hash,search:'?desktop-app=1',origin:'https://nas.test'};
 const parent={postMessage:(data,origin)=>{messages.push({data:JSON.parse(JSON.stringify(data)),origin});trace.push(data.type);}};
 const document={documentElement:{dataset:{}},querySelector:node,addEventListener(){}};
 const window={document,location,parent,addEventListener(type,callback){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(callback);},TitanControlPanel:{resolve:hash=>hash==='#settings?section=network'?{section:'network'}:null}};
 const context={document,window,location,URLSearchParams,console,setInterval:()=>1,setTimeout:()=>1,clearInterval(){},
  testApi:async path=>{requests.push(path);trace.push(path);if(path==='/api/session')return{user:signedIn?{name:'alice',role:'admin'}:null,permissions:{},version:'0.5.6',demo:true,setup_required:false};if(path==='/api/jobs')return[];throw Error('Unexpected API '+path);},
  testNavigate:async()=>{trace.push('navigate:start');if(navigationGate)await navigationGate.promise;if(navigationError)throw Error('Docker konnte nicht geladen werden');evaluate("page='docker'");trace.push('navigate:done');},
  testPollAlerts:async()=>trace.push('alerts'),
  testToast:(message,error)=>{toasts.push({message,error});trace.push('toast');},
  testManage:async target=>{managed.push(target.dataset.id);trace.push('manage:'+target.dataset.id);if(target.dataset.id==='missing')throw Error('App nicht gefunden');},
  testAuth:setup=>auth.push(setup)};
 vm.createContext(context);vm.runInContext(source,context);
 const evaluate=expression=>vm.runInContext(expression,context);
 const originalManage=evaluate("actions['app-manage']");
 evaluate("api=testApi;navigate=testNavigate;pollAlerts=testPollAlerts;toast=testToast;actions['app-manage']=testManage;renderAuth=testAuth");
 function message(data,overrides={}){for(const callback of listeners.get('message')||[])callback({origin:location.origin,source:parent,data,...overrides});}
 return{evaluate,node,window,parent,location,document,messages,managed,toasts,requests,trace,auth,message,context,originalManage,
  ready:()=>messages.filter(item=>item.data.type==='titan-app-ready'),
  acknowledgements:()=>messages.filter(item=>item.data.type==='titan-app-route-accepted'),
  resume:()=>navigationGate?.resolve(),
  pause(){navigationGate=deferred();},
  boot:()=>evaluate('boot()')};
}

(async()=>{
 const f=fixture({pauseNavigation:true});assert.equal(f.document.documentElement.dataset.desktopEmbedded,'true');
 // Trusted messages still cannot operate the document before boot completes.
 f.message({type:'titan-request-app-ready'});f.message({type:'titan-manage-app',id:'premature',requestId:1});f.message({type:'titan-navigate',hash:'#settings?section=network',requestId:2});
 assert.equal(f.ready().length,0);assert.equal(f.acknowledgements().length,0);assert.deepEqual(f.managed,[]);assert.equal(f.location.hash,'#docker?app=missing');
 const boot=f.boot();await turn();assert(f.trace.includes('navigate:start'));assert(!f.trace.includes('navigate:done'));
 f.message({type:'titan-request-app-ready'});f.message({type:'titan-manage-app',id:'still-premature',requestId:3});
 assert.equal(f.ready().length,0);assert.equal(f.acknowledgements().length,0);assert.deepEqual(f.managed,[],'No queued app request reaches an unfinished view');

 // The optional initial app lookup may fail; the containing app remains usable.
 f.resume();await boot;
 assert.deepEqual(f.requests,['/api/session','/api/jobs']);assert.deepEqual(f.managed,['missing']);
 assert.deepEqual(f.toasts,[{message:'App nicht gefunden',error:true}]);
 assert.equal(f.ready().length,1,'A missing initial ?app= must not block readiness');
 assert.deepEqual(f.ready()[0],{data:{type:'titan-app-ready'},origin:'https://nas.test'});
 assert(f.trace.indexOf('navigate:done')<f.trace.indexOf('manage:missing'));
 assert(f.trace.indexOf('toast')<f.trace.indexOf('titan-app-ready'));
 assert.equal(f.node('#shell').hidden,false);assert.equal(f.node('#auth').hidden,true);

 // Readiness queries and routes require both the real parent and exact origin.
 for(const overrides of [{origin:'https://evil.test'},{source:{}},{origin:'null',source:f.parent}]){
  f.message({type:'titan-request-app-ready'},overrides);
  f.message({type:'titan-manage-app',id:'untrusted',requestId:11},overrides);
  f.message({type:'titan-navigate',hash:'#settings?section=network',requestId:12},overrides);
 }
 await turn();assert.equal(f.ready().length,1);assert.equal(f.acknowledgements().length,0);assert.deepEqual(f.managed,['missing']);assert.equal(f.location.hash,'#docker?app=missing');
 f.message({type:'titan-request-app-ready',requestId:20});assert.equal(f.ready().length,2,'A restored parent can request readiness after boot');assert.equal(f.acknowledgements().length,0);
 f.message({type:'titan-manage-app',id:'nextcloud',requestId:37});await turn();assert.deepEqual(f.managed,['missing','nextcloud'],'A valid later app opens after the initial failure');
 assert.deepEqual(f.acknowledgements(),[{data:{type:'titan-app-route-accepted',requestId:37},origin:'https://nas.test'}],'The accepted route echoes the exact parent request ID');
 for(const id of ['', '../escape', 'app id', 'x'.repeat(65),null])f.message({type:'titan-manage-app',id,requestId:38});
 f.message({type:'unknown',id:'ignored',requestId:39});await turn();assert.deepEqual(f.managed,['missing','nextcloud']);assert.equal(f.acknowledgements().length,1);
 f.evaluate("page='files'");f.message({type:'titan-manage-app',id:'wrong-view',requestId:40});await turn();assert.deepEqual(f.managed,['missing','nextcloud']);assert.equal(f.acknowledgements().length,1);f.evaluate("page='docker'");
 f.message({type:'titan-navigate',hash:'#arbitrary',requestId:41});assert.equal(f.location.hash,'#docker?app=missing');assert.equal(f.acknowledgements().length,1);
 f.message({type:'titan-navigate',hash:'#settings?section=network',requestId:107});assert.equal(f.location.hash,'#settings?section=network');
 assert.deepEqual(f.acknowledgements().at(-1),{data:{type:'titan-app-route-accepted',requestId:107},origin:'https://nas.test'});
 for(const requestId of [undefined,0,-1,1.5,'108',Number.MAX_SAFE_INTEGER+1])f.message({type:'titan-navigate',hash:'#settings?section=network',requestId});
 assert.equal(f.acknowledgements().length,2,'Malformed serials cannot acknowledge a pending parent route');

 // Rebooting a document clears readiness until its new view finishes loading.
 f.location.hash='#docker';f.pause();const reboot=f.boot();await turn();const replies=f.ready().length;
 f.message({type:'titan-request-app-ready'});f.message({type:'titan-manage-app',id:'stale-ready',requestId:301});await turn();
 assert.equal(f.ready().length,replies);assert.equal(f.acknowledgements().length,2);assert.deepEqual(f.managed,['missing','nextcloud']);f.resume();await reboot;assert.equal(f.ready().length,replies+1);

 const failed=fixture({hash:'#docker',navigationError:true});await assert.rejects(failed.boot(),/Docker konnte nicht geladen werden/);
 failed.message({type:'titan-request-app-ready'});failed.message({type:'titan-manage-app',id:'invalid-view',requestId:401});await turn();assert.equal(failed.ready().length,0);assert.equal(failed.acknowledgements().length,0);assert.deepEqual(failed.managed,[]);
 const anonymous=fixture({signedIn:false});await anonymous.boot();anonymous.message({type:'titan-request-app-ready'});anonymous.message({type:'titan-manage-app',id:'anonymous',requestId:501});await turn();
 assert.deepEqual(anonymous.auth,[false]);assert.deepEqual(anonymous.requests,['/api/session']);assert.equal(anonymous.ready().length,0);assert.equal(anonymous.acknowledgements().length,0);assert.deepEqual(anonymous.managed,[]);

 // Exercise the original action: a slow response for A cannot replace newer B.
 const race=fixture({hash:'#docker'});await race.boot();const pending=new Map(),dialogs=[];
 race.context.raceApi=path=>{const id=new URL(path,'https://nas.test').searchParams.get('app'),gate=deferred();pending.set(id,gate);return gate.promise;};
 race.context.raceCatalog=async id=>({id,name:'App '+id});
 race.context.raceDialog=(title,html)=>{dialogs.push({title,html});return true;};
 race.evaluate('api=raceApi;catalogApp=raceCatalog;dialog=raceDialog');
 const details=id=>({app:{id,name:'App '+id,state:'exited'},warnings:[],config_path:'/apps/'+id,logs:'Logs '+id});
 const a=race.originalManage({dataset:{id:'a'}});await turn();assert(pending.has('a'));
 const b=race.originalManage({dataset:{id:'b'}});await turn();pending.get('b').resolve(details('b'));await b;
 assert.equal(dialogs.at(-1).title,'App b verwalten');pending.get('a').resolve(details('a'));await a;
 assert.deepEqual(dialogs.map(dialog=>dialog.title),['App b verwalten'],'A late detail response never replaces the latest selected app');

 // A late catalog lookup is discarded before it can request stale app details.
 const catalogGate=deferred();race.context.slowCatalog=id=>id==='slow-catalog'?catalogGate.promise:Promise.resolve({id,name:'App '+id});race.evaluate('catalogApp=slowCatalog');
 const oldCatalog=race.originalManage({dataset:{id:'slow-catalog'}}),newer=race.originalManage({dataset:{id:'c'}});await turn();pending.get('c').resolve(details('c'));await newer;
 catalogGate.resolve({id:'slow-catalog',name:'Old'});await oldCatalog;assert(!pending.has('slow-catalog'));assert.equal(dialogs.at(-1).title,'App c verwalten');

 // Package-center callbacks receive the same guard even after delegation.
 const packages=new Map();race.window.TitanPackageCenter={open:async(id,options)=>{const gate=deferred();packages.set(id,{gate,options});await gate.promise;return options.dialog(id+' package','Package '+id);}};
 const oldPackage=race.originalManage({dataset:{id:'titan-old'}}),newPackage=race.originalManage({dataset:{id:'titan-new'}});
 packages.get('titan-new').gate.resolve();assert.equal(await newPackage,true);packages.get('titan-old').gate.resolve();assert.equal(await oldPackage,false);
 assert.equal(dialogs.at(-1).title,'titan-new package');assert(!dialogs.some(dialog=>dialog.title==='titan-old package'));
 console.log('Embedded app: readiness and exact route ACK guards, missing initial app recovery, trusted parent, reboot/auth guards, original app-detail/catalog races and delegated package dialog guard passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
