'use strict';
const assert=require('node:assert/strict');
const desktop=require('../titan/web/desktop.js');
class Element{
 constructor(){this.dataset={};this.attrs={};this.events=new Map();this.textContent='';this.style={};}
 addEventListener(type,fn){this.events.set(type,fn);}
 removeEventListener(type,fn){if(this.events.get(type)===fn)this.events.delete(type);}
 setAttribute(key,value){this.attrs[key]=value;}
 click(){this.events.get('click')?.();}
}
function fixture(storage=new Map()){
 const shell=new Element(),button=new Element(),label=new Element(),frame=new Element();
 const nodes={'#shell':shell,'[data-window-size]':button,'[data-window-size-label]':label,'.nas-window':frame};
 const store={getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)};
 return{shell,button,label,frame,nodes,root:{querySelector:s=>nodes[s],defaultView:{localStorage:store}},storage,store};
}
const f=fixture();let state=desktop.mount({root:f.root,user:{name:'alice'},page:'vms'});
assert.equal(state.expanded,false);assert.equal(f.label.textContent,'Maximieren');f.button.click();
f.frame.style.width='730px';f.frame.style.height='530px';
assert.equal(f.shell.dataset.windowExpanded,'true');assert.equal(f.button.attrs['aria-pressed'],'true');assert.equal(f.label.textContent,'Wiederherstellen');
desktop.dispose();assert.equal(f.button.events.size,0);assert.equal(f.shell.dataset.windowExpanded,undefined);
f.frame.style={};state=desktop.mount({root:f.root,user:{name:'alice'},page:'vms'});assert.equal(state.expanded,true);assert.equal(f.frame.style.width,'730px');assert.equal(f.frame.style.height,'530px');
desktop.dispose();f.frame.style={};state=desktop.mount({root:f.root,user:{name:'alice'},page:'docker'});assert.equal(state.expanded,false);assert.equal(f.frame.style.width,undefined);
state=desktop.mount({root:f.root,user:{name:'bob'},page:'vms'});assert.equal(state.expanded,false);
// Corrupt or denied local preferences never prevent navigation or resizing.
f.store.getItem=()=>{throw Error('private mode');};f.store.setItem=()=>{throw Error('private mode');};
state=desktop.mount({root:f.root,user:{name:'alice'},page:'files'});f.button.click();assert.equal(state.expanded,true);
delete f.nodes['[data-window-size]'];assert.equal(desktop.mount({root:f.root,page:'dashboard'}),null);assert.equal(f.shell.dataset.windowExpanded,undefined);assert.equal(f.button.events.size,0);
const escape=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;');
const admin=desktop.launcher({user:{role:'admin'},esc:escape,icon:()=>'<svg></svg>'});
assert.equal((admin.match(/class="desktop-app-link"/g)||[]).length,12);
const user=desktop.launcher({user:{role:'user'},esc:escape,icon:()=>''});assert(user.includes('#files'));assert(!user.includes('#settings'));assert(!user.includes('#vms'));
const win=desktop.application({page:'vms',title:'Virtuelle Maschinen',icon:()=>'',user:{role:'admin'}});assert(win.includes('>Schließen<'));assert(win.includes('>Maximieren<'));assert(win.includes('href="#dashboard"'));
assert(desktop.application({page:'files',title:'Dateimanager',icon:()=>'',user:{role:'user'}}).includes('href="#files"'));
console.log('Desktop windows: visible controls, per-user/per-app maximize persistence, denied storage, cleanup and role-aware menu passed.');
