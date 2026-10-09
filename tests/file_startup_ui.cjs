'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/app.js','utf8');
const body=source.slice(source.indexOf(' async files() {'),source.indexOf(' async vms()'));
// Execute the production page loader with an unavailable share, then recover
// through another share without replacing the whole application with an error.
const method=body.slice(0,body.lastIndexOf('},')+1);
(async()=>{
 let rendered,fail=true;
 const shares=[{name:'Daten',writers:['admin'],readers:[]},{name:'Andere',writers:['admin'],readers:[]}];
 const context={session:{user:{role:'user',system_user:'admin',name:'test'}},currentShare:'',currentPath:'',fileOffset:0,fileSearch:'',fileFilters:{},fileStorageData:{},rootAccessData:{},filesView:null,
  api:async path=>path==='/api/shares'?shares:fail?Promise.reject(Error('[Errno 2] No such file or directory: Daten')):{entries:[],total:0,limit:200,offset:0},
  fileLocations:value=>value,fileQuery:()=>'',heading:()=>'',fileBreadcrumbs:()=>'',uploadStatus:()=>'',esc:String,bytes:String,date:String,fileUrl:()=>'',
  window:{TitanLocations:{resources:()=>[]},TitanFileBrowser:{render:value=>{rendered=value;return 'file-browser';}}}};
 vm.createContext(context);vm.runInContext('var pages={'+method+'};',context);
 assert.equal(await context.pages.files(),'file-browser');assert.equal(rendered.writable,false);assert.match(rendered.data.error,/Daten/);assert.equal(rendered.shares.length,2);
 context.currentShare='Andere';fail=false;await context.pages.files();assert.equal(rendered.writable,true);assert.equal(rendered.data.error,undefined);
 console.log('File startup: missing share retains navigation, disables writes and recovers after selecting a valid share.');
})().catch(error=>{console.error(error);process.exitCode=1;});
