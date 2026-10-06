'use strict';
// Exercise navigation boundaries and async upload behavior without a privileged host/browser.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const callbacks={},nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,open:false,style:{},handlers:{},classList:{remove(){},toggle(){}},addEventListener(type,callback){this.handlers[type]=callback;},append(){},querySelectorAll:()=>[],setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(selector);};
const document={querySelector:node,querySelectorAll:()=>[],addEventListener:(name,callback)=>callbacks[name]=callback,createElement:()=>({remove(){}})};
const window={getSelection:()=>({toString:()=>''}),addEventListener(){}};
window.TitanFileBrowser=require('../titan/web/file_browser.js');
const context=vm.createContext({document,window,location:{hostname:'nas',hash:'#files'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},fetch(){throw Error('Unexpected request');},URLSearchParams,FormData,AbortController,Uint8Array,TextEncoder,TextDecoder,atob:value=>Buffer.from(value,'base64').toString('binary'),btoa:value=>Buffer.from(value,'binary').toString('base64'),console});
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(fs.readFileSync('titan/web/location_controls.js','utf8'),context);
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);
(async()=>{
 const row={dataset:{openAction:'folder-open',path:'Documents'}};
 const event={target:{closest:selector=>selector==='.file-row'?row:null}};
 context.event=event;
 assert.equal(evaluate('fileRowTarget(event).dataset.path'),'Documents');
 for(const interactive of ['a','button','input','select','textarea','label']){
  event.target.closest=selector=>selector.includes(interactive)?{}:row;
  assert.equal(evaluate('fileRowTarget(event)'),null);
 }
 event.target.closest=selector=>selector==='.file-row'?row:null;
 window.getSelection=()=>({toString:()=> 'selected text'});
 assert.equal(evaluate('fileRowTarget(event)'),null);
 window.getSelection=()=>({toString:()=>''});
 assert.match(evaluate("button('Test','close')"),/type="button"/);
 // A file upload must retain its original share/folder across an in-flight navigation.
 evaluate("session={user:{csrf:'synthetic-csrf',role:'admin',system_user:'titan-files'}}; currentShare='original'; currentPath='folder';");
 const requests=[];
 context.fetch=async(url,options)=>{const body=JSON.parse(options.body);requests.push({url,body});evaluate("currentShare='other'; currentPath='changed';");return {ok:true,json:async()=>({offset:body.offset+Buffer.from(body.data,'base64').length})};};
 context.file={name:'big.bin',size:1048577,slice:(start,end)=>({arrayBuffer:async()=>new Uint8Array(Math.min(end,1048577)-start).buffer})};
 await evaluate('upload(file,false)');
 assert.equal(requests.length,2);
 for(const {body} of requests){assert.equal(body.share,'original');assert.equal(body.path,'folder/big.bin');}
 assert.equal(evaluate('activeUpload'),null);
 // ISO uploads explicitly finalize total size and reuse the server-issued upload token.
 requests.length=0;
 context.file.name='test.iso';
 context.fetch=async(url,options)=>{const body=JSON.parse(options.body);requests.push({url,body});return {ok:true,json:async()=>({offset:body.offset+Buffer.from(body.data,'base64').length,upload_id:'a'.repeat(32),complete:body.offset>0})};};
 await evaluate('upload(file,true)');
 assert.equal(requests[0].body.total,1048577);
 assert.equal(requests[1].body.upload_id,'a'.repeat(32));
 // Plain-text preview escapes HTML and keeps its download target if navigation changes.
 evaluate("currentShare='original';currentPath='folder';");
 context.fetch=async()=>{evaluate("currentShare='other'");return {ok:true,headers:{get:()=>null},arrayBuffer:async()=>new TextEncoder().encode('<script>bad</script>').buffer};};
 context.target={dataset:{path:'folder/example.html'}};
 await evaluate("actions['file-preview'](target)");
 const html=node('#dialog-body').innerHTML;
 assert(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
 assert(html.includes('share=original&amp;path=folder%2Fexample.html'));
 // Unknown suffixes use content-based previews and retain an explicitly captured share.
 context.target={dataset:{share:'original',path:'folder/settings.custom'}};
 await evaluate("actions['file-preview'](target)");
 assert(node('#dialog-body').innerHTML.includes('&lt;script&gt;bad&lt;/script&gt;'));
 assert(node('#dialog-body').innerHTML.includes('share=original&amp;path=folder%2Fsettings.custom'));
 // The dedicated editor receives immutable scope/revision and does not use the
 // generic dialog submit handler, which closes ordinary forms after a save.
 const mounts=[];let permittedClose=true,disposed=0;
 window.TitanFileEditor={render:options=>'EDITOR '+options.path,mount:(body,options)=>mounts.push(options),canCloseWithin:()=>permittedClose,disposeWithin:()=>disposed++};
 context.target={dataset:{share:'original',path:'folder/settings.custom'}};
 context.fetch=async()=>({ok:true,json:async()=>({data:Buffer.from('old\r\n').toString('base64'),total:5,revision:'a'.repeat(64)})});
 await evaluate("actions['file-edit'](target)");
 assert.equal(mounts.at(-1).share,'original');assert.equal(mounts.at(-1).path,'folder/settings.custom');assert.equal(mounts.at(-1).text,'old\r\n');
 assert.equal(mounts.at(-1).file.revision,'a'.repeat(64));
 assert.equal(node('#dialog form').handlers.submit,undefined);
 // Only the latest requested file may open, even when the earlier response is last.
 const pending=new Map();
 context.fetch=async(url,options)=>new Promise(resolve=>pending.set(JSON.parse(options.body).path,resolve));
 context.targetA={dataset:{share:'original',path:'A.custom'}};context.targetB={dataset:{share:'original',path:'B.custom'}};
 const openingA=evaluate("actions['file-edit'](targetA)"),openingB=evaluate("actions['file-edit'](targetB)");
 const reply={ok:true,json:async()=>({data:Buffer.from('safe').toString('base64'),total:4,revision:'b'.repeat(64)})};
 pending.get('B.custom')(reply);await openingB;const accepted=mounts.length;
 pending.get('A.custom')(reply);await openingA;assert.equal(mounts.length,accepted);assert.equal(mounts.at(-1).path,'B.custom');
 const openingCancelled=evaluate("actions['file-edit'](targetA)");evaluate('generation++');pending.get('A.custom')(reply);await openingCancelled;assert.equal(mounts.length,accepted);
 // Dirty/busy editors may refuse closing or replacement, including Escape.
 permittedClose=false;evaluate('actions.close()');assert.equal(node('#dialog').open,true);
 const preserved=node('#dialog-body').innerHTML;assert.equal(evaluate("dialog('Replacement','discarded')"),false);assert.equal(node('#dialog-body').innerHTML,preserved);
 let prevented=false;node('#dialog').handlers.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);
 const beforeDispose=disposed;node('#dialog').handlers.close();assert.equal(disposed,beforeDispose); // Old queued close event must not dispose a new dialog.
 permittedClose=true;evaluate('actions.close()');node('#dialog').handlers.close();assert.equal(disposed,beforeDispose+1);
 delete window.TitanFileEditor;
 // Admin controls remain available for shares without service-account membership.
 context.fetch=async url=>({ok:true,json:async()=>url==='/api/storage-locations'?{default_storage:'system',storage:[{id:'system',label:'Interner Speicher',path:'/var/srv/titan',available:true,capabilities:['files','apps','shares','vms']}]}:url==='/api/shares'?[{name:'private',readers:[],writers:['someone-else']}]:{entries:[],total:0,limit:200,offset:0}});
 const adminHtml=await evaluate('pages.files()');
 assert(adminHtml.includes('data-action="folder-create"'));
 assert(adminHtml.includes('file-upload'));
 assert(adminHtml.includes('Interner Speicher'));assert(!adminHtml.includes('System /'));assert(!adminHtml.includes('data-fb-path="etc"'));assert.equal(evaluate('currentPath'),'var/srv/titan');evaluate('navigate=()=>{};actions["file-up"]()');assert.equal(evaluate('currentPath'),'var/srv/titan');
 const fullCatalog={default_storage:'system',storage:[{id:'system',label:'Interner Speicher',kind:'internal',path:'/var/srv/titan',available:true,status:'full',free_bytes:0,capabilities:['files','apps','shares','vms']},{id:'pool:offline',label:'Offline Archiv',kind:'pool',path:'/srv/offline',available:false,status:'offline',capabilities:['files','apps']}]};context.fullCatalog=fullCatalog;const offlineRequests=[];context.fetch=async url=>{offlineRequests.push(url);return {ok:true,json:async()=>url==='/api/storage-locations'?fullCatalog:url==='/api/shares'?[]:{entries:[],total:0,limit:200,offset:0}};};evaluate("currentShare='@system';currentPath='srv/offline';");const offlineHtml=await evaluate('pages.files()');assert(offlineHtml.includes('momentan nicht verfügbar'));assert(offlineHtml.includes('Interner Speicher'));assert(!offlineRequests.some(url=>url.startsWith('/api/files')));assert(!offlineHtml.includes('data-action="folder-create"'));evaluate("currentShare='@system';currentPath='var/srv/titan';");const fullHtml=await evaluate('pages.files()');assert(fullHtml.includes('data-action="folder-create" disabled'));assert(fullHtml.includes('id="file-upload" type="file" hidden multiple disabled'));assert(fullHtml.includes('ansehen und löschen'));assert(offlineRequests.some(url=>url.startsWith('/api/files')),'A full filesystem remains browsable for cleanup');
 // A missing configured data disk never opens an OS root or silently selects
 // internal storage. The sidebar remains available for an explicit new choice.
 const missingRequests=[],missingCatalog={...fullCatalog,default_storage:'volume:gone'};context.fetch=async url=>{missingRequests.push(url);return {ok:true,json:async()=>url==='/api/storage-locations'?missingCatalog:url==='/api/shares'?[]:{entries:[],total:0,limit:200,offset:0}};};evaluate("currentShare='@system';currentPath='etc';");const missingHtml=await evaluate('pages.files()');assert.equal(evaluate('currentPath'),'');assert(!missingRequests.some(url=>url.startsWith('/api/files')));assert(missingHtml.includes('value="@storage:volume:gone" selected disabled'));assert(missingHtml.includes('Gewählter Speicher · Nicht verfügbar'));assert(!missingHtml.includes('value="@storage:system" selected'));assert(missingHtml.includes('Interner Speicher'));
 // Edit requests retain the original path, revision, UTF-8 and CRLF even if navigation changes.
 evaluate("currentShare='@system';currentPath='var/srv/titan';dialog=(title,html,submit)=>{globalThis.editorHtml=html;globalThis.editorSubmit=submit;};");
 context.target={dataset:{path:'var/srv/titan/settings.txt'}};
 context.fetch=async(url,options)=>{const body=JSON.parse(options.body);requests.push({url,body});evaluate("currentShare='other';currentPath='changed';");return {ok:true,json:async()=>({data:Buffer.from('old\r\n').toString('base64'),total:5,revision:'original-version'})};};
 await evaluate("actions['file-edit'](target)");
 assert(context.editorHtml.includes('/var/srv/titan/settings.txt'));
 context.editData={get:()=> 'neu ä\n'};
 context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({ok:true})};};
 await evaluate('editorSubmit(editData)');
 const saved=requests.at(-1).body;
 assert.equal(saved.share,'@system');assert.equal(saved.path,'var/srv/titan/settings.txt');assert.equal(saved.revision,'original-version');
 assert.equal(Buffer.from(saved.data,'base64').toString('utf8'),'neu ä\r\n');
 evaluate("session.user.role='user';currentShare='private';");
 context.fetch=async url=>({ok:true,json:async()=>url==='/api/shares'?[{name:'private',readers:['titan-files'],writers:[]}]:{entries:[],total:0,limit:200,offset:0}});
 const userHtml=await evaluate('pages.files()');assert(!userHtml.includes('System /'));assert(!userHtml.includes('file-edit'));
 console.log('Web UI: row isolation, upload targets, escaped previews, system scope, editor revision and preserved UTF-8/CRLF passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
