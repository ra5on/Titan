'use strict';
// Exercise navigation boundaries and async upload behavior without a privileged host/browser.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const callbacks={},nodes=new Map();
const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',textContent:'',hidden:false,open:false,style:{},classList:{remove(){},toggle(){}},elements:{name:{value:'Neue Datei'},file_type:{value:'txt'},extension:{value:''}},querySelectorAll:()=>[],querySelector:node,addEventListener(){},removeEventListener(){},append(){},setAttribute(){},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(selector);};
const document={querySelector:node,querySelectorAll:()=>[],addEventListener:(name,callback)=>callbacks[name]=callback,createElement:()=>({remove(){}})};
const window={TitanFileTypes:require('../titan/web/file_types.js'),getSelection:()=>({toString:()=>''}),addEventListener(){}};
const context=vm.createContext({document,window,location:{hostname:'nas',hash:'#files'},setTimeout:()=>0,setInterval:()=>0,clearInterval(){},fetch(){throw Error('Unexpected request');},URLSearchParams,FormData,AbortController,Uint8Array,TextEncoder,TextDecoder,atob:value=>Buffer.from(value,'base64').toString('binary'),btoa:value=>Buffer.from(value,'binary').toString('base64'),console});
const source=fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,'');
vm.runInContext(source,context);
const evaluate=expression=>vm.runInContext(expression,context);

(async()=>{
 evaluate("session={user:{name:'admin',csrf:'fixture',role:'admin',system_user:'titan-files'}};");
 context.fixture={components:{docker:{available:false,installed:false,missing:['docker'],error:'CLI <missing>'},vms:{available:false,installed:true,kvm:false,error:'KVM fehlt'}},repair:{running:true,phase:'Installation <phase>',error:'<script>bad</script>'}};
 const html=evaluate('componentPanel(fixture)');
 assert(html.includes('Systemkomponenten'));
 assert(html.includes('data-component="all" disabled'));
 assert(html.includes('CLI &lt;missing&gt;'));
 assert(!html.includes('<script>bad</script>'));
 assert(html.includes('KVM fehlt'));
 const requests=[];
 context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({job:'job-fixture'})};};
 context.target={dataset:{component:'vms'}};
 await evaluate("actions['component-install'](target)");
 assert.equal(requests[0].url,'/api/components/install');
 assert.equal(requests[0].body.component,'vms');
 assert(evaluate("watched.has('job-fixture')"));
 context.target.dataset.component='arbitrary command';
 await assert.rejects(evaluate("actions['component-install'](target)"),/Ungültige/);
 assert.equal(requests.length,1);
 const details=evaluate("jobDetails({action:'component_install',status:'completed',result:{message:'ready',warnings:['KVM <absent>'],output:'APT <log>'}})");
 assert(details.includes('KVM &lt;absent&gt;'));assert(details.includes('APT &lt;log&gt;'));
 // New text file and folder dialogs retain their initial target and validate names.
 evaluate("currentShare='private';currentPath='Documents';dialog=(title,html,submit)=>{globalThis.formHtml=html;globalThis.submitFile=submit;};");
 evaluate("actions['file-create']()");
 assert(context.formHtml.includes('Dateiname'));assert(context.formHtml.includes('Dateityp'));assert(context.formHtml.includes('Word-Dokument (.docx)'));assert(context.formHtml.includes('Excel-Tabelle (.xlsx)'));assert(context.formHtml.includes('data-file-create-preview'));
 evaluate("currentShare='other';currentPath='changed';page='settings';");
 context.data={get:key=>key==='name'?'Notiz':key==='file_type'?'txt':key==='extension'?'':'Grüße 🌍\n'};
 await evaluate('submitFile(data)');
 const create=requests.at(-1).body;
 assert.equal(create.action,'create');assert.equal(create.share,'private');assert.equal(create.path,'Documents/Notiz.txt');
 assert.equal(Buffer.from(create.data,'base64').toString('utf8'),'Grüße 🌍\n');
 for(const extension of ['docx','xlsx','odt','ods']){context.data={get:key=>({name:extension==='xlsx'?'Budget':'Dokument',file_type:extension,extension:'',content:'THIS-TEXT-MUST-NOT-BECOME-AN-OFFICE-DOCUMENT'})[key]};await evaluate('submitFile(data)');const payload=requests.at(-1).body;assert.equal(payload.action,'create_document');assert.equal(payload.document_type,extension);assert.equal(payload.share,'private');assert.equal(payload.path,'Documents/'+(extension==='xlsx'?'Budget':'Dokument')+'.'+extension);assert(!Object.hasOwn(payload,'data'),'Office documents must use valid backend templates, not empty/text bytes');}
 for(const name of ['', '..', 'folder/new.txt','bad\0name']){context.badname=name;assert.throws(()=>evaluate('fileLeafName(badname)'));}
 assert.equal(evaluate("fileCopyPath('Ordner/datei.tar.gz')"),'Ordner/datei.tar-Kopie.gz');
 assert.equal(evaluate("fileCopyPath('Ordner/.hidden')"),'Ordner/.hidden-Kopie');
 console.log('Component UI and file creation: repair enum/status escaping, captured targets and filename validation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
