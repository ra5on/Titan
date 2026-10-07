'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/workspace.js');
const allowed=['files','docker','updates'];
assert.deepEqual(ui.preferences({pins:['files','files','root'],windows:[{id:'files'},{id:'files'},{id:'root'}],theme:'injected'},allowed).pins,['files']);
assert.equal(ui.preferences(null,allowed).theme,'sky');
assert.equal(ui.preferences({windows:[{id:'root'}]},allowed).windows.length,0);
const limited=ui.geometry({width:9000,height:9000,x:-200,y:9000},{width:390,height:700});
assert.deepEqual(limited,{width:390,height:700,x:0,y:0});
assert.equal(ui.geometry({x:0,y:0},{width:1200,height:800}).x,0);
assert(ui.defaultGeometry('apps',{width:1600,height:950}).width>ui.defaultGeometry('security',{width:1600,height:950}).width,'Catalog starts wider than personal security');
assert.deepEqual(ui.defaultGeometry('files',{width:390,height:700}),{width:358,height:668,x:16,y:16},'Default windows reclaim the viewport with small margins');

class Element{
 constructor(){this.dataset={};this.style={};this.nodes={};this.events={};this.hidden=false;this.attrs={};this.children=[];this.clientWidth=1200;this.clientHeight=700;this.classList={toggle(){},add(){},remove(){}};}
 set innerHTML(value){this.html=value;if(value.includes('desktop-app-frame'))for(const selector of ['[data-frame-pin]','[data-frame-minimize]','[data-frame-maximize]','[data-frame-close]','header','[data-frame-resize]','iframe'])this.nodes[selector]=new Element();if(this.nodes.iframe)this.nodes.iframe.contentWindow={};}
 get innerHTML(){return this.html||'';}
 querySelector(selector){return this.nodes[selector]||null;}
 append(node){this.children.push(node);node.parent=this;}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
 addEventListener(type,fn){this.events[type]=fn;}
 removeEventListener(type,fn){if(this.events[type]===fn)delete this.events[type];}
 setAttribute(key,value){this.attrs[key]=value;}
 getBoundingClientRect(){return{height:64};}
 close(){this.open=false;}
 focus(){}
}
function fixture(saved){const doc=new Element();doc.body=new Element();doc.defaultView=new Element();const values=new Map(saved?[['titan-desktop-v2:alice',JSON.stringify(saved)]]:[]);const view=doc.defaultView;view.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};view.history={replaceState(){}};view.location={origin:'https://nas:5000'};view.matchMedia=()=>({matches:false});doc.createElement=()=>new Element();for(const id of ['#shell','.workspace','#main','#desktop-tasks','.topbar','#show-desktop'])doc.nodes[id]=new Element();return{doc,view,values,layer:()=>doc.nodes['.workspace'].children[0]};}
(async()=>{
 const f=fixture();let answer=false,confirmations=0;
 const options={doc:f.doc,user:{name:'alice',role:'admin'},tools:allowed.map(id=>[id,id,'tool']),icon:()=>'',esc:String,api:async()=>({installed:[]}),confirm:async()=>{confirmations++;return answer;},system(){},logout(){}};
 const desk=ui.mount(options);desk.route('#files');desk.route('#docker');assert.equal(f.layer().children.length,2);
 const file=f.layer().children[0],iframe=file.nodes.iframe;
 desk.route('#files');assert.equal(file.nodes.iframe,iframe,'Switching apps must retain the document');assert.equal(file.dataset.mobileActive,'true');
 file.nodes['[data-frame-minimize]'].onclick();assert(file.hidden);desk.route('#files');assert(!file.hidden);assert.equal(file.nodes.iframe,iframe);
 file.nodes['[data-frame-pin]'].onclick({currentTarget:file.nodes['[data-frame-pin]']});assert.deepEqual(JSON.parse(f.values.get('titan-desktop-v2:alice')).pins,['files']);
 file.nodes['[data-frame-maximize]'].onclick();assert.equal(file.nodes['[data-frame-maximize]'].attrs['aria-pressed'],'true');
 desk.route('#not-allowed');assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://attacker',source:iframe.contentWindow,data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://nas:5000',source:{},data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,2);
 f.view.events.message({origin:'https://nas:5000',source:iframe.contentWindow,data:{type:'titan-open',hash:'#updates'}});assert.equal(f.layer().children.length,3);
 iframe.contentWindow.titanHasUnsavedWork=()=>true;await file.nodes['[data-frame-close]'].onclick();assert.equal(confirmations,1);assert.equal(f.layer().children.length,3);answer=true;await file.nodes['[data-frame-close]'].onclick();assert.equal(f.layer().children.length,2);
 const menu=f.doc.body.children[0];menu.getBoundingClientRect=()=>({left:100,right:800,top:100,bottom:600});menu.open=true;
 menu.events.click({target:menu,clientX:110,clientY:120});assert(menu.open,'Clicking dialog padding is not an outside click');
 menu.events.click({target:menu,clientX:30,clientY:120});assert(!menu.open,'Clicking the backdrop closes the main menu');assert(f.layer().children.every(node=>node.hidden),'Outside click shows desktop by minimizing, not destroying applications');
 desk.route('#docker');const retained=f.layer().children.find(node=>node.dataset.frame==='docker');assert(!retained.hidden);menu.open=true;let canceled=false;
 menu.events.cancel({preventDefault(){canceled=true;}});assert(canceled);assert(!menu.open);assert(retained.hidden,'Native Escape/cancel also returns to the desktop');
 desk.desktop();assert(f.layer().children.every(node=>node.hidden));const persisted=JSON.parse(f.values.get('titan-desktop-v2:alice'));assert(persisted.windows.every(row=>row.minimized));desk.destroy();assert.equal(Object.keys(f.view.events).length,0);assert.equal(f.doc.nodes['.workspace'].children.length,0);
 const restored=fixture({windows:[{id:'files',geometry:{width:720,height:420,x:80,y:90}},{id:'docker',geometry:{width:600,height:400,x:120,y:100},minimized:true}],pins:['files']});const restoredDesk=ui.mount({...options,doc:restored.doc});assert.equal(restored.layer().children.length,2);assert.equal(restored.layer().children[1].style.left,'120px');assert(restored.layer().children[1].hidden);restoredDesk.destroy();
 const denied=fixture();denied.view.localStorage={getItem(){throw Error('denied');},setItem(){throw Error('denied');}};const privateDesk=ui.mount({...options,doc:denied.doc});privateDesk.route('#files');assert.equal(denied.layer().children.length,1);privateDesk.destroy();
 console.log('Desktop workspace: simultaneous retained documents, minimize/maximize/pin, per-user restore, bounds, role allowlist, trusted frame messages, unsaved-close confirmation and cleanup passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
