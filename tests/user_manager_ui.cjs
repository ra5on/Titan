'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({window:{},setTimeout,console});
vm.runInContext(fs.readFileSync('titan/web/user_manager.js','utf8'),context);
const users=context.window.TitanUsers;
const plain=value=>JSON.parse(JSON.stringify(value));
const accounts={web:[{name:'admin',role:'admin',enabled:true,system_user:'admin',display_name:'Alice <Admin>',description:'NAS-Verwaltung'},{name:'reader',role:'user',enabled:false,system_user:'reader',display_name:'Bob',description:'Familie'}],system:[{name:'admin',smb_ready:true},{name:'reader',smb_ready:false},{name:'removed',removed:true}],service_user:'titan-files'};
const shares=[{name:'photos',path:'/srv/shares/photos',readers:['reader','guest'],writers:['admin','titan-files']},{name:'docs',path:'/srv/shares/docs',readers:[],writers:['reader','admin']}];
const helpers={field:(label,name,type,value,attributes,hint)=>`<label>${label}<input name="${name}" value="${String(value??'').replaceAll('<','&lt;')}" ${attributes}>${hint||''}</label>`,selectField:(label,name,options,value)=>`<label>${label}<select name="${name}">${options.map(([key,text])=>`<option value="${key}" ${String(key)===String(value)?'selected':''}>${text}</option>`).join('')}</select></label>`,formEnd:text=>`<button type="submit">${text}</button></form>`,currentName:'admin'};
(async()=>{
 assert(users.matches(accounts.web[1],'bob','user','blocked'));
 assert(users.matches(accounts.web[1],'famILIE','',''));
 assert(!users.matches(accounts.web[1],'','admin',''));
 assert(!users.matches(accounts.web[1],'','user','active'));
 assert(users.protectedAccount(accounts.web[0],accounts.web,'admin'));
 assert(users.protectedAccount(accounts.web[0],accounts.web,'reader'));
 assert(!users.protectedAccount(accounts.web[1],accounts.web,'admin'));
 const html=users.render(accounts,shares,{currentName:'admin'});
 assert(html.includes('data-um-search')&&html.includes('data-um-role')&&html.includes('data-um-status'));
 assert(html.includes('data-um-select="reader"'));
 assert(html.includes('Alice &lt;Admin&gt;')&&!html.includes('Alice <Admin>'));
 assert.match(html,/data-action="user-remove" data-name="admin" disabled/);
 assert(!html.includes('removed'));
 assert(!html.includes('Gruppen erstellen')&&!html.includes('Speicherkontingent'));
 const editor=users.editor(accounts.web[1],accounts,shares,helpers);
 assert(editor.includes('role="tablist"')&&editor.includes('data-um-panel="shares" hidden'));
 assert(editor.includes('name="display_name"')&&editor.includes('maxlength="96"')&&editor.includes('name="description"')&&editor.includes('maxlength="256"'));
 assert.match(editor,/name="share-photos"[\s\S]*?<option value="read" selected/);
 assert.match(editor,/name="share-docs"[\s\S]*?<option value="write" selected/);
 const changes=users.accountChanges(accounts.web[1],accounts.web,'admin',new Map([['display_name','Robert'],['description','Privat'],['role','user'],['enabled','true'],['password','']]));
 assert.deepEqual(plain(changes),{name:'reader',display_name:'Robert',description:'Privat',enabled:true},'Reactivating a blocked user must send enabled=true, without resending the unchanged role.');
 const profileOnly=users.accountChanges(accounts.web[0],accounts.web,'admin',new Map([['display_name','Alice'],['description','Profil bearbeitet'],['role','admin'],['enabled','true'],['password','']]));
 assert.deepEqual(plain(profileOnly),{name:'admin',display_name:'Alice',description:'Profil bearbeitet'},'Pure profile edits must not trigger account status or role updates and close SMB sessions.');
 const blockUser=users.accountChanges({...accounts.web[1],enabled:true},accounts.web,'admin',new Map([['display_name','Bob'],['description','Familie'],['role','user'],['enabled','false']]));
 assert.equal(blockUser.enabled,false,'A real account block must remain in the security update payload.');
 assert(!Object.hasOwn(blockUser,'role'),'Blocking an account does not change its role.');
 const promote=users.accountChanges(accounts.web[1],accounts.web,'admin',new Map([['display_name','Bob'],['description','Familie'],['role','admin'],['enabled','false']]));
 assert.equal(promote.role,'admin','A changed role must be sent to the backend.');
 assert(!Object.hasOwn(promote,'enabled'),'Promoting a blocked account does not reactivate it.');
 assert.throws(()=>users.accountChanges(accounts.web[0],accounts.web,'admin',new Map([['role','admin'],['enabled','false']])),/eigenes Konto/);
 assert.throws(()=>users.accountChanges(accounts.web[0],accounts.web,'other',new Map([['role','user'],['enabled','true']])),/weiteren aktiven Administrator/);
 assert.deepEqual(plain(users.permissionUpdate(shares[1],'reader','read')),{name:'docs',readers:['reader'],writers:['admin']});
 assert.throws(()=>users.permissionUpdate(shares[0],'reader','execute'),/Ungültige/);
 const legacy={...accounts.web[0],system_user:'titan-files'};
 assert(!users.editor(legacy,accounts,shares,helpers).includes('data-um-shares-form'));
 const requests=[],baseline=plain(shares),pending=new Map([['photos','write'],['docs','none']]);let jobCount=0,failSecond=true;
 const latest=[{...shares[0],readers:['reader','guest','new-user'],writers:['admin','titan-files']},{...shares[1]}];
 const api=async(path,body)=>{
  requests.push({path,body:plain(body||null)});
  if(path==='/api/managed-shares')return plain(latest);
  if(path==='/api/actions'){
   jobCount++;const update=body.arguments;
   assert.equal(body.operation,'share_user_permission');
   assert.deepEqual(Object.keys(update).sort(),['name','permission','user'],'Only the target account permission may cross the API boundary.');
   if(!(jobCount===2&&failSecond)){
    const target=latest.find(item=>item.name===update.name);
    // A concurrent administrator saves rights after the UI fetched its snapshot.
    if(jobCount===1){target.readers.push('late-reader');target.writers.push('late-writer');}
    const patched=users.permissionUpdate(target,update.user,update.permission);
    target.readers=patched.readers;target.writers=patched.writers;
   }
   return {job:'job-'+jobCount};
  }
  if(path==='/api/jobs')return [{id:'job-'+jobCount,status:jobCount===2&&failSecond?'failed':'completed',result:jobCount===2&&failSecond?{error:'SMB-Dienst nicht verfügbar'}:{}}];
  throw Error('Unexpected '+path);
 };
 await assert.rejects(users.savePermissions(accounts.web[1],baseline,pending,{api,serviceUser:'titan-files',waitOptions:{pause:async()=>{},attempts:1}}),/SMB-Dienst/);
 assert.equal(users.permission(baseline[0],'reader'),'write','Successfully saved rights must become the retry baseline.');
 assert.equal(users.permission(baseline[1],'reader'),'write','Failed rights must stay pending.');
 const first=requests.find(item=>item.path==='/api/actions').body.arguments;
 assert.deepEqual(first,{name:'photos',user:'reader',permission:'write'},'The UI must not send full rights arrays from an earlier snapshot.');
 assert.deepEqual(plain(latest[0].readers),['guest','new-user','late-reader'],'Concurrent read permissions saved after the snapshot must survive.');
 assert.deepEqual(plain(latest[0].writers),['admin','titan-files','late-writer','reader'],'Concurrent write permissions and the app service account must survive.');
 failSecond=false;requests.length=0;
 assert.equal(await users.savePermissions(accounts.web[1],baseline,pending,{api,serviceUser:'titan-files',waitOptions:{pause:async()=>{},attempts:1}}),1);
 assert.equal(requests.filter(item=>item.path==='/api/actions').length,1,'Retry only the failed share.');
 assert.equal(requests.find(item=>item.path==='/api/actions').body.arguments.name,'docs');
 assert.deepEqual(requests.find(item=>item.path==='/api/actions').body.arguments,{name:'docs',user:'reader',permission:'none'});
 assert.deepEqual(plain(latest[1].writers),['admin'],'Removing only the target user preserves other accounts.');
 await assert.rejects(users.savePermissions(legacy,baseline,pending,{api,serviceUser:'titan-files'}),/persönlichen SMB/);
 await assert.rejects(users.savePermissions(accounts.web[1],[shares[1]],new Map([['docs','read']]),{api:async()=>[],serviceUser:'titan-files'}),/nicht mehr verfügbar/);
 console.log('User manager: filters, escaped profiles, protected accounts, real SMB rights, fresh permissions and partial-failure retry passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
