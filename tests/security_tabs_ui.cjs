'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context=vm.createContext({window:{},setTimeout,Date,setInterval,clearInterval});
vm.runInContext(fs.readFileSync('titan/web/security_center.js','utf8'),context);
const ui=context.window.TitanSecurity,ids=['overview','protection','twofactor','sessions','history'];
const data={checks:[{ok:true,label:'HTTPS'}],two_factor:false,sessions:[],login_events:[],all_users:false};
const html=ui.render(data,{admin:true});
assert(html.includes('role="tablist"'));assert(html.includes('aria-controls="security-protection"'));
assert(html.includes('data-security-pane="overview" >'));assert(html.includes('data-security-pane="twofactor" hidden'));
class Node{
 constructor(dataset={}){this.dataset=dataset;this.attrs={};this.hidden=false;this.events=new Map();this.value='unsaved edit';}
 setAttribute(key,value){this.attrs[key]=value;}
 focus(){this.focused=true;}
 addEventListener(type,fn){this.events.set(type,fn);}
 removeEventListener(type,fn){if(this.events.get(type)===fn)this.events.delete(type);}
}
const center=new Node(),buttons=ids.map(id=>new Node({securityTab:id})),panes=ids.map(id=>new Node({securityPane:id}));
const enrollment=new Node();
center.querySelector=selector=>selector==='[data-security-enrollment]'?enrollment:buttons.find(node=>selector===`[data-security-tab="${node.dataset.securityTab}"]`)||null;
center.querySelectorAll=selector=>selector==='[data-security-tab]'?buttons:selector==='[data-security-pane]'?panes:[];
const root={querySelector:selector=>selector==='[data-security-center]'?center:null};
ui.mount(root,data,{protection:null,admin:true});
const choose=id=>center.events.get('click')({target:{closest:()=>({dataset:{securityTab:id}})}});
choose('protection');assert.equal(panes[1].hidden,false);assert(panes.filter((_,index)=>index!==1).every(node=>node.hidden));
assert.equal(buttons[1].attrs['aria-selected'],'true');assert.equal(buttons[1].tabIndex,0);assert.equal(buttons[0].tabIndex,-1);
choose('sessions');assert.equal(panes[1].value,'unsaved edit','Tab switch preserves form nodes and unsaved values');
buttons[3].matches=()=>true;let prevented=false;center.events.get('keydown')({target:buttons[3],key:'ArrowRight',preventDefault(){prevented=true;}});
assert(prevented);assert.equal(panes[4].hidden,false);assert(buttons[4].focused);
assert(ui.render(data,{admin:true}).includes('data-security-pane="history" >'),'Selected security tab survives refresh');
choose('protection');assert(ui.render(data,{admin:false}).includes('data-security-pane="overview" >'),'Administrative tab cannot persist into a normal user view');
ui.dispose();assert.equal(center.events.size,0,'Tab navigation listeners are disposed on leaving the page');
console.log('Security tabs: compact panels, administrative scope, retained form nodes, keyboard navigation, refresh persistence and cleanup passed.');
