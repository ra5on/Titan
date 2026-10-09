'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),node=selector=>{if(!nodes.has(selector))nodes.set(selector,{innerHTML:'',hidden:false,open:false,addEventListener(){},querySelectorAll:()=>[],querySelector:node,showModal(){this.open=true;},close(){this.open=false;},focus(){},textContent:'',append(){}});return nodes.get(selector);};
let replies={},requests=[],timers=[],cleared=[];
const context={window:{addEventListener(){}},document:{hidden:false,querySelector:node,querySelectorAll:()=>[],addEventListener(){},createElement(){return {innerHTML:'',querySelector:node};}},location:{hash:'#updates',hostname:'nas.local'},URL,URLSearchParams,FormData,console,setTimeout:()=>0,setInterval:(fn,delay)=>{timers.push({fn,delay});return timers.length;},clearInterval:id=>cleared.push(id),fetch:async(path,options)=>{requests.push({path,options});assert(Object.hasOwn(replies,path),'Unexpected API '+path);return {ok:true,json:async()=>replies[path]};}};
vm.createContext(context);vm.runInContext(fs.readFileSync("titan/web/web_updates.js","utf8"),context);vm.runInContext(fs.readFileSync('titan/web/settings_center.js','utf8'),context);vm.runInContext(fs.readFileSync('titan/web/update_controls.js','utf8'),context);vm.runInContext(fs.readFileSync('titan/web/app.js','utf8').replace(/boot\(\)\.catch\(error=>toast\(error.message,true\)\);\s*$/,''),context);const evaluate=code=>vm.runInContext(code,context);
const previous={version:'0.4.1',digest:'sha256:'+'a'.repeat(64),image:'ghcr.io/ra5on/titan@sha256:'+'a'.repeat(64)},current={version:'0.4.2',digest:'sha256:'+'b'.repeat(64),image:'ghcr.io/ra5on/titan@sha256:'+'b'.repeat(64)};
const ui=context.window.TitanUpdates;
 for(const [choice,version,twoFactor,protections] of [[{version:'v0.4.9-alpha.1'},'0.4.9',true,true],[{version:'0.5.2'},'0.5.2',false,true],[{version:'0.5.3-alpha.1'},'0.5.3',false,false],[{version:'0.5.10-system.1'},'0.5.10',false,false],[{version:'1.0.0'},'1.0.0',false,false],[{version:'0.9.0-system.1',titan_version:'0.5.2'},'0.5.2',false,true],[{version:'0.9.0-system.1',release_metadata:{titan_version:'0.4.9'}},'0.4.9',true,true],[{version:'Unbekannt'},null,false,false]]){const protection=ui.rollbackSecurity(choice);assert.equal(protection.appVersion,version);assert.equal(protection.legacyTwoFactor,twoFactor);assert.equal(protection.legacyProtections,protections);}
assert.equal(ui.progress({status:'idle'}),'');
assert(ui.progress({status:'running',phase:'download',received:512,total:1024}).includes('value="50"'));
assert(!ui.progress({status:'running',phase:'writing'}).includes('<progress'));
assert(ui.progress({status:'interrupted',phase:'writing',message:'<script>'}).includes('&lt;script&gt;'));
assert.equal(ui.rollbackChoices({rollback:previous}).length,1);assert.equal(ui.rollbackChoices({rollback_options:[{digest:'bad'}]}).length,0);let html=ui.panel({booted:current,rollback:null,rollback_available:false,rollback_reason:'Noch kein Update durchgeführt.'});assert(html.includes('Keine Version'));assert(html.includes('id="rollback-version" disabled'));assert(html.includes('Kein vorheriger Systemstand verfügbar'));assert(html.includes('Noch kein Update'));assert(/data-action="update-rollback" disabled/.test(html));html=ui.panel({booted:current,rollback:previous,rollback_available:true,rollback_queued:true,reboot_required:true,next_boot:previous});assert(html.includes('Neustart erforderlich'));assert(html.includes('v0.4.1'));assert(html.includes('Datensicherung'));assert(!html.includes('<script>'));assert(ui.panel({},'Fehler <script>').includes('Fehler &lt;script&gt;'));
const older={version:'0.4.0',digest:'sha256:'+'c'.repeat(64),slot:'B',installed_at:1790841600};
html=ui.panel({booted:current,rollback_options:[previous,older],rollback_available:true});
assert(html.includes('v0.4.0'));assert(html.includes('Slot B'));
assert(html.includes('damaligen Sicherheitsstand'));assert(html.includes('Neuere Schutzfunktionen und Sicherheitskorrekturen können dabei entfallen'));
assert.equal((html.match(/<option value=/g)||[]).length,2);
html=ui.panel({booted:current,rollback_options:[],rollback_available:true});
assert(/data-action="update-rollback" disabled/.test(html),'No usable versions means no rollback action, even with a stale availability flag');
html=ui.panel({booted:current,rollback_options:[older],rollback_available:true,reboot_scheduled:true});
assert(html.includes('id="rollback-version" disabled'));
assert(/data-action="update-rollback" disabled/.test(html));
html=ui.offer('system',{channel:'alpha',selection_kind:'system',signed:true,available:true,latest:'v0.5.2-system.1',titan_version:'0.5.2',system_revision:0,latest_system_revision:1,security_summary:{security_packages:2,total_packages:3},package_changes:[{name:'openssl<script>',old_version:'1',new_version:'2',security:true}]},{channel:'alpha'},{version:'0.5.2',stage:'alpha'},{});
assert(html.includes('2 Sicherheitskorrekturen'));assert(html.includes('openssl&lt;script&gt;'));assert(html.includes('Debian 13 · Stand 0'));assert(html.includes('Systemstand 1'));assert(html.includes('data-update-kind="system"'));assert(html.includes('data-update-available="true"'));
assert(ui.offer('titan',{channel:'beta',selection_kind:'titan',signed:true,available:true,latest:'v9.0'},{channel:'alpha'},{version:'0.5.2'},{}).includes('data-update-available="false"'));
assert(!ui.offer('system',{channel:'alpha',selection_kind:'titan',signed:true,available:true,latest:'v9.0'},{channel:'alpha'},{version:'0.5.2'},{}).includes('v9.0'));
assert(!ui.panel({booted:current},'',{split:true}).includes('data-action="update-install"'),'Split cards own their preparation controls');
(async()=>{
 evaluate('session={version:"0.4.2",stage:"alpha",demo:false,user:{role:"admin"}}');
 replies['/api/security?all=1']={two_factor_user_count:0};
 replies['/api/settings']={channel:'alpha',repository:'ra5on/Titan',installation:'manual'};replies['/api/updates']={channel:'alpha',selection_kind:'all',release_kind:'system',latest:'v0.4.3',latest_titan_version:'0.4.3',available:true,signed:true};replies['/api/updates/system']={booted:current,rollback:previous,rollback_available:true,next_boot:current};
 let replaced=false;const originalCreate=context.document.createElement;
 context.document.createElement=()=>({innerHTML:'',querySelector:()=>({id:'updated-offer'})});
 node('#update-offer-all').replaceWith=()=>{replaced=true;};node('#settings-form').innerHTML='unsaved settings';
 evaluate("page='updates'");await evaluate('refreshUpdateOffer()');assert(replaced);assert.equal(node('#settings-form').innerHTML,'unsaved settings');
 context.document.createElement=originalCreate;
 const page=await evaluate('pages.updates()');assert(page.includes('Systemversionen'));assert(page.includes('Update vorbereiten'));assert(!page.includes('Titan-Update vorbereiten'));assert(!page.includes('Systemupdate vorbereiten'));assert(page.includes('data-update-kind="all"'));assert.equal((page.match(/data-action="update-check"/g)||[]).length,1);assert.equal((page.match(/data-action="update-install"/g)||[]).length,1);assert(!requests.some(item=>item.path.includes('?kind=')));assert(page.includes('System &amp; Sicherheit'));assert(requests.some(item=>item.path==='/api/updates/system'));
 replies['/api/updates/system'].reboot_required=true;const pending=await evaluate('pages.updates()');assert(/data-update-available="false" disabled/.test(pending),'A live pending deployment disables an obsolete cached offer');
 await evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "a".repeat(64)})})})');assert(node('#dialog-body').innerHTML.includes('>Ja</button>')&&node('#dialog-body').innerHTML.includes('>Nein</button>'));assert(!node('#dialog-body').innerHTML.includes('name="confirmation"'));assert(node('#dialog-body').innerHTML.includes('v0.4.1'));
 replies['/api/updates/system']={booted:current,rollback_options:[previous,older],rollback_available:true,next_boot:current};
 await evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "c".repeat(64)})})})');assert(node('#dialog-body').innerHTML.includes('v0.4.0'),'Confirmation must use the selected version, not the first option');
 replies['/api/security?all=1'].two_factor_user_count=1;
 await evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "c".repeat(64)})})})');
 assert(node('#dialog-body').innerHTML.includes('prüft er beim Login nur das Passwort'),'Rolling back to an old login implementation must explain the authentication change');
 assert(node('#dialog-body').innerHTML.includes('neuen Anmeldeschutz und die neue Schutzgrenze für Systemdateien nicht'));
 // A later OS maintenance number can still contain the earlier application.
 // The selected application's identity drives both warnings, not the first
 // dropdown item or the overall bundle version.
 for(const [appVersion,loginWarning,boundaryWarning] of [['0.4.9',true,true],['0.5.2',false,true],['0.5.3',false,false]]){
  const chosen={version:'0.9.0-system.1',titan_version:appVersion,digest:'sha256:'+'d'.repeat(64)};replies['/api/updates/system'].rollback_options=[previous,chosen];await evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "d".repeat(64)})})})');const confirmation=node('#dialog-body').innerHTML;assert(confirmation.includes('damalige Sicherheitsstand'));assert.equal(confirmation.includes('prüft er beim Login nur das Passwort'),loginWarning);assert.equal(confirmation.includes('neuen Anmeldeschutz und die neue Schutzgrenze für Systemdateien nicht'),boundaryWarning);
 }
 replies['/api/updates/system'].rollback_options=[previous];
 await assert.rejects(evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "c".repeat(64)})})})'),/nicht mehr verfügbar/);
 await evaluate('actions["system-reboot"]()');assert(node('#dialog-body').innerHTML.includes('>Ja</button>')&&node('#dialog-body').innerHTML.includes('>Nein</button>'));assert(!node('#dialog-body').innerHTML.includes('name="confirmation"'));assert(node('#dialog-body').innerHTML.includes('nicht zwangsweise'));
 replies['/api/updates/system']={rollback_available:false,rollback_reason:'Keine vorherige Version.'};await assert.rejects(evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "a".repeat(64)})})})'),/Keine vorherige/);
 replies['/api/updates/check']={job:'stream-check'};await evaluate('actions["update-check"]({dataset:{updateKind:"system"}})');assert.deepEqual(JSON.parse(requests.at(-1).options.body),{update_kind:'system'});
 let captured;context.dialog=(title,body,submit)=>{captured={title,body,submit};};
 const mutations=[];context.action=async(operation,args)=>mutations.push({operation,args});
 replies['/api/updates/system']={booted:current,rollback:previous,rollback_available:true,next_boot:current};
 await evaluate('actions["system-reboot"]()');assert.equal(mutations.length,0,'Opening confirmation must not reboot');
 await captured.submit(new Map());assert.equal(mutations[0].operation,'system_reboot');assert.equal(mutations[0].args.expected_digest,current.digest);assert.equal(mutations[0].args.confirmation,'NEUSTART');
 await evaluate('actions["update-rollback"]({closest:()=>({querySelector:()=>({value:"sha256:"+ "a".repeat(64)})})})');assert.equal(mutations.length,1,'Opening confirmation must not stage rollback');
 await captured.submit(new Map());assert.equal(mutations[1].operation,'update_rollback');assert.equal(mutations[1].args.expected_digest,previous.digest);assert.equal(mutations[1].args.confirmation,'ROLLBACK');
 await evaluate('actions["update-install"]({dataset:{version:"v0.5.2-system.1",updateKind:"system"}})');assert(captured.body.includes('Deine Titan-Version bleibt erhalten.'));const before=mutations.length;await captured.submit(new Map());assert.equal(mutations[before].operation,'update_install');assert.equal(mutations[before].args.update_kind,'system');assert.equal(mutations[before].args.expected_version,'v0.5.2-system.1');
 await evaluate('actions["update-check"]({dataset:{updateKind:"all"}})');assert.deepEqual(JSON.parse(requests.at(-1).options.body),{update_kind:'all'});await evaluate('actions["update-install"]({dataset:{version:"v0.5.3",updateKind:"all"}})');await captured.submit(new Map());assert.equal(mutations.at(-1).args.update_kind,'all');
 const previousFetch=context.fetch;context.fetch=async()=>({ok:false,status:429,json:async()=>({error:'Anmeldung vorübergehend gesperrt.',retry_after:900})});await assert.rejects(evaluate('api("/api/login",{})'),failure=>failure.status===429&&failure.retryAfter===900);context.fetch=previousFetch;
 const root={querySelector:()=>({})};ui.mount(root,{api:async()=>({})});assert.equal(timers.at(-1).delay,3000);ui.dispose();assert(cleared.length);
 console.log('Update UI: live deployments, initial no-rollback state, cached-offer suppression, captured rollback/reboot confirmation and polling disposal passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
