'use strict';
const assert=require('node:assert/strict'),explorer=require('../titan/web/file_browser.js'),{fixture,Element}=require('./desktop_test_dom.cjs');
const saved=new Map(),storage={getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)};
global.localStorage=storage;
const add=Element.prototype.addEventListener;Element.prototype.addEventListener=function(type,fn,options=false){const capture=typeof options==='object'?!!options.capture:options;add.call(this,type,fn,capture);options?.signal?.addEventListener('abort',()=>this.removeEventListener(type,fn,capture),{once:true});};
function mount(owner='alice'){
 const f=fixture(),ctx={owner,share:'private',path:'',shares:[{name:'private'}],writable:true,entries:[{name:'visible',readable:true},{name:'.hidden',readable:true}],targets:[],actions:{},fetch:async()=>({ok:false})};
 f.surface.innerHTML=explorer.render(ctx);const browser=f.surface.querySelector('[data-file-browser]');browser.style.setProperty=function(key,value){this[key]=value;};for(const checkbox of browser.querySelectorAll('[data-file-select]'))checkbox.remove();
 const instance=explorer.mount(f.surface,ctx);return {...f,browser,instance,dispatch:(node,type)=>f.doc.dispatch(node,type),option:name=>browser.querySelector(`[data-fb-preference="${name}"]`)};
}
try{
 const rootBar='<div data-root-access class="root-access-bar"><button data-root-toggle>Root aktivieren</button></div>';
 let markup=explorer.render({owner:'root-test',share:'@system',path:'',shares:[],entries:[],rootAccess:false,rootAccessMarkup:rootBar});
 let dom=fixture();dom.surface.innerHTML=markup;assert(dom.surface.querySelector('[data-root-access]').closest('.fb-layout-menu'),'Protected NAS root action lives in the view menu');assert(!dom.surface.querySelector('.fb-system-note'),'Normal mode does not consume a permanent warning row');
 markup=explorer.render({owner:'root-test',share:'@system',path:'',shares:[],entries:[],rootAccess:true,rootAccessMarkup:rootBar});dom=fixture();dom.surface.innerHTML=markup;assert(!dom.surface.querySelector('[data-root-access]').closest('.fb-layout-menu'),'An active root session remains visible outside closed menus');assert(dom.surface.querySelector('.fb-system-note'));
 let filtered=fixture();filtered.surface.innerHTML=explorer.render({owner:'filtered',share:'private',path:'',shares:[],entries:[],filters:{recursive:true}});assert.equal(filtered.surface.querySelector('[data-file-browser]').dataset.filters,'true');assert.equal(filtered.surface.querySelector('[data-fb-filters]').getAttribute('aria-expanded'),'true');
 let f=mount();const uploader=f.browser.querySelector('#file-upload');let uploadChoices=0;uploader.click=()=>uploadChoices++;f.dispatch(f.browser.querySelector('[data-fb-upload]'),'click');assert.equal(uploadChoices,1,'Upload is a keyboard-accessible button that opens the native picker');assert.equal(f.browser.dataset.view,'grid');assert.equal(f.browser.dataset.pathVisible,'true');assert.equal(f.browser.querySelector('[data-fb-index="1"]').hidden,true);
 const icon=f.option('iconSize');icon.value='200';f.dispatch(icon,'input');assert.equal(f.browser.style['--fb-icon-size'],'88px');assert.equal(explorer.readPreferences('alice').iconSize,88);
 const gap=f.option('gap');gap.value='6';f.dispatch(gap,'input');assert.equal(f.browser.style['--fb-grid-gap'],'6px');
 const path=f.option('showPath');path.checked=false;f.dispatch(path,'change');assert.equal(f.browser.dataset.pathVisible,'false');assert.equal(explorer.readPreferences('alice').showPath,false);
 const sizes=f.option('showSizes');sizes.checked=false;f.dispatch(sizes,'change');assert.equal(f.browser.dataset.sizesVisible,'false');
 f.dispatch(f.browser.querySelector('[data-fb-hidden]'),'click');assert.equal(f.browser.querySelector('[data-fb-index="1"]').hidden,false);
 const menuList=f.browser.querySelector('.fb-menu-view-switch').querySelector('[data-fb-view="list"]');f.dispatch(menuList,'click');assert.equal(f.browser.dataset.view,'list');assert.equal(explorer.readPreferences('alice').view,'list');assert(f.browser.querySelectorAll('[data-fb-view="list"]').every(button=>button.getAttribute('aria-pressed')==='true'));assert(f.browser.querySelectorAll('[data-fb-view="grid"]').every(button=>button.getAttribute('aria-pressed')==='false'));
 const sort=f.browser.querySelector('[data-fb-sort]');sort.value='name-desc';f.dispatch(sort,'change');assert.equal(explorer.readPreferences('alice').order,'name-desc');
 const menu=f.browser.querySelector('.fb-layout-options');menu.open=true;f.dispatch(f.doc.body,'pointerdown');assert.equal(menu.open,false);menu.open=true;f.doc.dispatch(menu,'keydown',{key:'Escape'});assert.equal(menu.open,false);assert.equal(f.doc.activeElement,menu.querySelector('summary'));
 explorer.dispose();f=mount('bob');assert.equal(f.browser.dataset.view,'grid');assert.equal(f.browser.dataset.pathVisible,'true');assert.equal(f.browser.querySelector('[data-fb-index="1"]').hidden,true,'Other users do not inherit hidden-file settings');
 explorer.dispose();f=mount('alice');assert.equal(f.browser.dataset.view,'list');assert.equal(f.browser.dataset.pathVisible,'false');assert.equal(f.browser.dataset.sizesVisible,'false');assert.equal(f.browser.querySelector('[data-fb-index="1"]').hidden,false);
 assert.equal(explorer.normalizePreferences({iconSize:-2,gap:99,order:'<script>',view:'bad'}).iconSize,32);assert.equal(explorer.normalizePreferences({gap:99}).gap,36);assert.equal(explorer.normalizePreferences({order:'<script>'}).order,'name');
 assert.equal(explorer.readPreferences('blocked',{getItem(){throw Error('blocked');}}).view,'grid');saved.set('titan-file-view','list');assert.equal(explorer.readPreferences('legacy').view,'list','Old view choice migrates without mixing new per-user preferences');
 console.log('File view: per-user icon size/spacing/path/sizes/sort/hidden/view persistence, legacy migration, popover outside/Escape focus, invalid storage and preference bounds passed.');
}finally{explorer.dispose();delete global.localStorage;}
