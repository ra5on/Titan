'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/workspace.js');
const allowed=['files','docker','updates'];
assert.deepEqual(ui.preferences({pins:['files','files','root'],windows:[{id:'files'},{id:'files'},{id:'root'}],theme:'injected'},allowed).pins,['files']);
assert.equal(ui.preferences(null,allowed).theme,'sky');
assert.deepEqual(ui.desktopPreferences(),{color_mode:'light',background_click:'none',transparency:40});
for(const transparency of [-1,101,40.5,'70',true,NaN])assert.equal(ui.desktopPreferences({transparency}).transparency,40);
assert.deepEqual(ui.desktopPreferences({background_click:'javascript',transparency:0}),{color_mode:'light',background_click:'none',transparency:0});
assert.equal(ui.desktopPreferences({background_click:'minimize',transparency:100}).transparency,100);
assert.equal(ui.preferences({windows:[{id:'root'}]},allowed).windows.length,0);
const limited=ui.geometry({width:9000,height:9000,x:-200,y:9000},{width:390,height:700});
assert.deepEqual(limited,{width:390,height:700,x:0,y:0});
assert.equal(ui.geometry({x:0,y:0},{width:1200,height:800}).x,0);
assert(ui.defaultGeometry('apps',{width:1600,height:950}).width>ui.defaultGeometry('security',{width:1600,height:950}).width,'Catalog starts wider than personal security');
assert.deepEqual(ui.defaultGeometry('files',{width:390,height:700}),{width:358,height:668,x:16,y:16},'Default windows reclaim the viewport with small margins');

class Element{
 constructor(){this.dataset={};this.style={setProperty(k,v){this[k]=v;},removeProperty(k){delete this[k];}};this.nodes={};this.events={};this.hidden=false;this.attrs={};this.children=[];this.clientWidth=1200;this.clientHeight=700;this.classList={toggle(){},add(){},remove(){}};}
 set innerHTML(value){this.html=value;if(value.includes('desktop-app-frame'))for(const selector of ['[data-frame-pin]','[data-frame-minimize]','[data-frame-maximize]','[data-frame-close]','header','[data-frame-resize]','iframe'])this.nodes[selector]=new Element();if(this.nodes.iframe)this.nodes.iframe.contentWindow={messages:[],postMessage(value,origin){this.messages.push({value,origin});}};}
 get innerHTML(){return this.html||'';}
 querySelector(selector){return this.nodes[selector]||null;}
 querySelectorAll(){return [];}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 matches(selector){return this.selector===selector;}
 closest(selector){return this.closestMap?.[selector]||null;}
 append(node){this.children.push(node);node.parent=this;}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
 addEventListener(type,fn){this.events[type]=fn;}
 removeEventListener(type,fn){if(this.events[type]===fn)delete this.events[type];}
 setAttribute(key,value){this.attrs[key]=value;}
 getBoundingClientRect(){return{height:64};}
 close(){this.open=false;}
 focus(){this.focused=true;}
}
function fixture(saved){const doc=new Element();doc.body=new Element();doc.documentElement=new Element();doc.defaultView=new Element();const values=new Map(saved?[['titan-desktop-v2:alice',JSON.stringify(saved)]]:[]);const view=doc.defaultView;view.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};view.history={replaceState(){}};view.location={origin:'https://nas:5000'};view.matchMedia=()=>({matches:false});doc.createElement=()=>new Element();for(const id of ['#shell','.workspace','#main','#desktop-tasks','.topbar','#show-desktop','#desktop-surface','#profile'])doc.nodes[id]=new Element();return{doc,view,values,layer:()=>doc.nodes['.workspace'].children[0]};}
(async()=>{
 const f=fixture();let appearance,answer=false,confirmations=0;f.view.TitanTheme={set:value=>appearance={...value}};
 const options={doc:f.doc,user:{name:'alice',role:'admin'},tools:allowed.map(id=>[id,id,'tool']),icon:()=>'',esc:String,api:async()=>({installed:[]}),confirm:async()=>{confirmations++;return answer;},system(){},logout(){}};
 const desk=ui.mount(options);assert.equal(f.doc.documentElement.style['--desktop-glass-opacity'],'0.6');desk.route('#files');desk.route('#docker');assert.equal(f.layer().children.length,2);
 const file=f.layer().children[0],iframe=file.nodes.iframe;
 const desktop=f.doc.nodes['#desktop-surface'];
 f.doc.events.click({target:desktop,button:0});assert(!file.hidden,'Default free-desktop click leaves windows visible');
 let written,allowBackground=true;
 desk.setShortcuts({desktop:()=>({background_click:'minimize',transparency:75}),desktopWritable:()=>true,setDesktop:value=>{written={...value};},backgroundClickAllowed:()=>allowBackground});
 assert.equal(f.doc.documentElement.style['--desktop-glass-opacity'],'0.25','Server account settings override local cache');
 assert.match(desk.controls(),/value="75"/);assert.match(desk.controls(),/value="minimize" selected/);
 const account=f.doc.body.children[1],profile=f.doc.nodes['#profile'];profile.id='profile';profile.closestMap={'button,a':profile,'#profile':profile};
 const profileAction=new Element();account.nodes.button=profileAction;
 f.doc.events.click({target:profile,button:0});assert(!account.hidden);assert(profileAction.focused);
 assert.equal(appearance.color_mode,'light');const mode=new Element();mode.dataset.desktopColorChoice='dark';mode.closestMap={'button,a':mode};account.append(mode);f.doc.events.click({target:mode,button:0,preventDefault(){}});assert.equal(appearance.color_mode,'dark');assert.equal(written.color_mode,'dark');assert.match(desk.controls(),/data-desktop-color-choice="dark" aria-pressed="true"/);assert(!account.hidden,'Mode buttons keep appearance controls open');assert.match(account.innerHTML,/data-widgets-picker/,'The account panel always offers the widget gallery');
 const slider=new Element();account.append(slider);slider.selector='[data-desktop-transparency]';slider.value='100';f.doc.events.click({target:slider,button:0});assert(!account.hidden,'Slider clicks keep the account menu open');f.doc.events.input({target:slider,type:'input'});
 assert.equal(f.doc.documentElement.style['--desktop-glass-opacity'],'0');assert.equal(written.transparency,100);
 assert.equal(JSON.parse(f.values.get('titan-desktop-v2:alice')).desktop.transparency,100);
 f.doc.events.keydown({key:'Escape'});assert(account.hidden);assert(profile.focused,'Escape restores focus to account trigger');
 const control=new Element();control.closestMap={'button,a':control};control.id='irrelevant';control.classList.contains=()=>false;control.hasAttribute=()=>false;
 f.doc.events.click({target:control,button:0});assert(!file.hidden,'A control never triggers background minimization');
 allowBackground=false;f.doc.events.click({target:desktop,button:0});assert(!file.hidden,'Drag-ending clicks cannot minimize windows');allowBackground=true;
 f.doc.events.click({target:desktop,button:2});assert(!file.hidden,'Right-click keeps windows visible');
 f.doc.events.click({target:desktop,button:0});assert(file.hidden);assert.equal(f.doc.nodes['#show-desktop'].focused,true);desk.route('#files');
 desk.setDesktopPreferences({color_mode:'light',background_click:'none',transparency:0});assert.equal(written.background_click,'none');assert.equal(f.doc.documentElement.style['--desktop-glass-opacity'],'1');
 desk.route('#files');assert.equal(file.nodes.iframe,iframe,'Switching apps must retain the document');assert.equal(file.dataset.mobileActive,'true');
 file.nodes['[data-frame-minimize]'].onclick();assert(file.hidden);desk.route('#files');assert(!file.hidden);assert.equal(file.nodes.iframe,iframe);
 file.nodes['[data-frame-pin]'].onclick({currentTarget:file.nodes['[data-frame-pin]']});assert.deepEqual(JSON.parse(f.values.get('titan-desktop-v2:alice')).pins,[],'Core dock items can be unpinned');
 file.nodes['[data-frame-maximize]'].onclick();assert.equal(file.nodes['[data-frame-maximize]'].attrs['aria-pressed'],'true');
 desk.route('#docker?app=jellyfin');const dockerFrame=f.layer().children.find(node=>node.dataset.frame==='docker').nodes.iframe;assert.equal(dockerFrame.contentWindow.messages.length,0,'App details wait for embedded boot');desk.route('#docker?app=syncthing');f.view.events.message({origin:'https://attacker',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.equal(dockerFrame.contentWindow.messages.length,0);f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.deepEqual(dockerFrame.contentWindow.messages,[{value:{type:'titan-manage-app',id:'syncthing',requestId:2},origin:'https://nas:5000'}],'The latest requested app opens after the trusted frame becomes ready');dockerFrame.events.load();assert.equal(dockerFrame.contentWindow.messages.at(-1).value.type,'titan-request-app-ready');desk.route('#docker?app=jellyfin');assert.equal(dockerFrame.contentWindow.messages.length,2);f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.equal(dockerFrame.contentWindow.messages.at(-1).value.id,'jellyfin','Reloaded frames also wait for readiness');const accepted=dockerFrame.contentWindow.messages.at(-1).value.requestId;f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-route-accepted',requestId:accepted}});const delivered=dockerFrame.contentWindow.messages.length;f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.equal(dockerFrame.contentWindow.messages.length,delivered,'Accepted routes are not repeated');desk.route('#docker?app=syncthing');const pending=dockerFrame.contentWindow.messages.at(-1).value;dockerFrame.events.load();f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.deepEqual(dockerFrame.contentWindow.messages.at(-1).value,pending,'A route dropped during direct iframe reload is retried until accepted');f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-route-accepted',requestId:accepted}});const beforeRetry=dockerFrame.contentWindow.messages.length;f.view.events.message({origin:'https://nas:5000',source:dockerFrame.contentWindow,data:{type:'titan-app-ready'}});assert.equal(dockerFrame.contentWindow.messages.length,beforeRetry+1,'An older ACK cannot clear the latest route');
 desk.route('#not-allowed');assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://attacker',source:iframe.contentWindow,data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://nas:5000',source:{},data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://nas:5000',source:iframe.contentWindow,data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,3);
 iframe.contentWindow.titanHasUnsavedWork=()=>true;await file.nodes['[data-frame-close]'].onclick();assert.equal(confirmations,1);assert.equal(f.layer().children.length,3);answer=true;await file.nodes['[data-frame-close]'].onclick();assert.equal(f.layer().children.length,2);
 const menu=f.doc.body.children[0];const appearanceChoice=new Element();account.nodes['[data-desktop-color-choice]']=appearanceChoice;menu.open=true;f.doc.events['titan-desktop-preferences']();assert(!menu.open);assert(!account.hidden);assert(appearanceChoice.focused,'Desktop context opens and focuses personal appearance controls');f.doc.events.keydown({key:'Escape'});menu.getBoundingClientRect=()=>({left:100,right:800,top:100,bottom:600});menu.open=true;
 menu.events.click({target:menu,clientX:110,clientY:120});assert(menu.open,'Clicking dialog padding is not an outside click');
 menu.events.click({target:menu,clientX:30,clientY:120});assert(!menu.open,'Clicking the backdrop closes the main menu');assert(f.layer().children.every(node=>node.hidden),'Outside click shows desktop by minimizing, not destroying applications');
 desk.route('#docker');const retained=f.layer().children.find(node=>node.dataset.frame==='docker');assert(!retained.hidden);menu.open=true;let canceled=false;
 menu.events.cancel({preventDefault(){canceled=true;}});assert(canceled);assert(!menu.open);assert(retained.hidden,'Native Escape/cancel also returns to the desktop');
 desk.desktop();assert(f.layer().children.every(node=>node.hidden));const persisted=JSON.parse(f.values.get('titan-desktop-v2:alice'));assert(persisted.windows.every(row=>row.minimized));desk.destroy();assert.equal(f.doc.documentElement.style['--desktop-glass-opacity'],undefined);assert.equal(Object.keys(f.view.events).length,0);assert.equal(f.doc.nodes['.workspace'].children.length,0);
 const restored=fixture({windows:[{id:'files',geometry:{width:720,height:420,x:80,y:90}},{id:'docker',geometry:{width:600,height:400,x:120,y:100},minimized:true}],pins:['files']});const restoredDesk=ui.mount({...options,doc:restored.doc});assert.equal(restored.layer().children.length,2);assert.equal(restored.layer().children[1].style.left,'120px');assert(restored.layer().children[1].hidden);restoredDesk.destroy();
 const denied=fixture();denied.view.localStorage={getItem(){throw Error('denied');},setItem(){throw Error('denied');}};const privateDesk=ui.mount({...options,doc:denied.doc});privateDesk.route('#files');assert.equal(denied.layer().children.length,1);privateDesk.destroy();
 const bob=fixture();bob.values.set('titan-desktop-v2:alice',JSON.stringify({desktop:{transparency:98,background_click:'minimize'}}));const bobDesk=ui.mount({...options,doc:bob.doc,user:{name:'bob',role:'user'}});assert.deepEqual(bobDesk.desktopPreferences(),{color_mode:'light',background_click:'none',transparency:40},'Another account never receives cached preferences');bobDesk.setShortcuts({desktop:()=>({transparency:80}),desktopWritable:()=>false});bobDesk.setDesktopPreferences({transparency:70});assert.equal(bobDesk.desktopPreferences().transparency,40,'Failed server loads prevent overwriting remote preferences');assert.match(bobDesk.controls(),/disabled/);bobDesk.destroy();
 const vf=fixture(),pinned=[],vmId='12345678-1234-1234-1234-123456789abc';let vmRefreshes=0;const vd=ui.mount({...options,doc:vf.doc,toast(){},tools:[['vms','VMs',''],['terminal','Terminal','']]});
 vd.setShortcuts({desktop:()=>({}),desktopWritable:()=>true,add:key=>{pinned.push(key);return key==='tool:terminal'||key==='vm:'+vmId;},contains:()=>false,refreshVMs:async()=>{vmRefreshes++;}});
 vd.route('#vms?vm='+vmId+'&tab=console');const vn=vf.layer().children[0],vi=vn.nodes.iframe;assert.match(vn.innerHTML,/vm=12345678-1234-1234-1234-123456789abc&tab=console/);
 vf.view.events.message({origin:'https://nas:5000',source:vi.contentWindow,data:{type:'titan-app-ready'}});vd.route('#vms?vm='+vmId+'&tab=console');assert.equal(vi.contentWindow.messages.at(-1).value.type,'titan-open-vm');assert.equal(vi.contentWindow.messages.at(-1).value.id,vmId);
 vf.view.events.message({origin:'https://evil.test',source:vi.contentWindow,data:{type:'titan-pin-shortcut',key:'tool:terminal'}});vf.view.events.message({origin:'https://nas:5000',source:{},data:{type:'titan-pin-shortcut',key:'tool:terminal'}});await Promise.resolve();assert.equal(pinned.length,0);
 vf.view.events.message({origin:'https://nas:5000',source:vi.contentWindow,data:{type:'titan-pin-shortcut',key:'vm:'+vmId}});await Promise.resolve();await Promise.resolve();assert.deepEqual(pinned,['vm:'+vmId]);assert.equal(vmRefreshes,1);vd.destroy();
 const af=fixture(),ad=ui.mount({...options,doc:af.doc});ad.route('#files');const animated=af.layer().children[0],animations=[];
 animated.getBoundingClientRect=()=>({left:40,top:90,width:800,height:500});af.doc.nodes['.workspace'].children[1].getBoundingClientRect=()=>({left:400,top:650,width:320,height:60});
 animated.animate=(keyframes,options)=>{let resolve,reject;const item={keyframes,options,cancelled:false,finished:new Promise((yes,no)=>{resolve=yes;reject=no;}),finish(){resolve();},cancel(){this.cancelled=true;reject(Error('cancelled'));}};animations.push(item);return item;};
 const retainedDocument=animated.nodes.iframe;animated.nodes['[data-frame-minimize]'].onclick();assert(!animated.hidden,'Minimizing keeps the frame until its animation finishes');assert.match(animations[0].keyframes[1].transform,/scale\(\.12\)/);
 ad.route('#files');assert(animations[0].cancelled,'An immediate restore cancels the pending hide');animations[0].finish();animations[1].finish();await Promise.resolve();assert(!animated.hidden,'A stale minimize completion cannot hide a restored app');assert.equal(animated.nodes.iframe,retainedDocument,'Restore never recreates the app or its console');
 animated.nodes['[data-frame-minimize]'].onclick();animations.at(-1).finish();await Promise.resolve();assert(animated.hidden,'Minimize hides the document only after transition completion');ad.route('#files');animations.at(-1).finish();await Promise.resolve();
 const animationCount=animations.length;af.view.matchMedia=query=>({matches:query.includes('prefers-reduced-motion')});animated.nodes['[data-frame-minimize]'].onclick();assert(animated.hidden);assert.equal(animations.length,animationCount,'Reduced motion applies the state directly');ad.route('#files');assert(!animated.hidden);assert.equal(animations.length,animationCount);
 af.view.matchMedia=()=>({matches:false});await animated.nodes['[data-frame-close]'].onclick();assert.equal(af.layer().children.length,1,'Closing waits for the exit animation');animations.at(-1).finish();await Promise.resolve();assert.equal(af.layer().children.length,0);ad.destroy();
 const emptyDock=fixture({dock_version:1,pins:[]}),ed=ui.mount({...options,doc:emptyDock.doc});ed.route('#files');assert.deepEqual(JSON.parse(emptyDock.values.get('titan-desktop-v2:alice')).pins,[],'An intentionally empty dock remains empty after the one-time migration');ed.destroy();
 const changed=fixture(),cd=ui.mount({...options,doc:changed.doc,tools:[['apps','Apps','tool'],['docker','Docker','tool']]});
 cd.route('#apps');cd.route('#docker');
 const appFrame=changed.layer().children.find(node=>node.dataset.frame==='apps').nodes.iframe;
 const sourceFrame=changed.layer().children.find(node=>node.dataset.frame==='docker').nodes.iframe;
 changed.view.events.message({origin:'https://attacker',source:sourceFrame.contentWindow,data:{type:'titan-apps-changed'}});
 changed.view.events.message({origin:'https://nas:5000',source:{},data:{type:'titan-apps-changed'}});
 assert.equal(appFrame.contentWindow.messages.length,0,'Untrusted messages cannot invalidate the Store');
 changed.view.events.message({origin:'https://nas:5000',source:sourceFrame.contentWindow,data:{type:'titan-apps-changed'}});
 assert.deepEqual(appFrame.contentWindow.messages,[{value:{type:'titan-apps-invalidated'},origin:'https://nas:5000'}],'Docker changes refresh the retained App Store window');
 assert.equal(sourceFrame.contentWindow.messages.length,0,'The mutation source is not reloaded');
 cd.destroy();
 console.log('Desktop workspace: simultaneous retained documents, minimize/maximize/pin, per-user restore, bounds, role allowlist, trusted frame messages, unsaved-close confirmation and cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
