'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
 constructor(tag='div',className=''){this.tagName=tag.toUpperCase();this.className=className;this.children=[];this.dataset={};this.attributes={};this.events=new Map();this.hidden=false;this.id='';}
 setAttribute(name,value){this.attributes[name]=value;}
 append(...nodes){for(const node of nodes){node.remove();node.parentElement=this;node.ownerDocument=this.ownerDocument;this.children.push(node);}}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);this.parentElement=null;}
 matches(selector){return selector.startsWith('.')?this.className.split(' ').includes(selector.slice(1)):selector==='[data-section-layout]'?Object.hasOwn(this.dataset,'sectionLayout'):false;}
 querySelectorAll(selectors){return [...new Set(selectors.split(',').flatMap(selector=>{selector=selector.trim();const direct=selector.startsWith(':scope > ');if(direct)selector=selector.slice(9);return this.children.flatMap(node=>[...(node.matches(selector)?[node]:[]),...(direct?[]:node.querySelectorAll(selector))]);}))];}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 addEventListener(name,handler){this.events.set(name,handler);}
 click(){this.events.get('click')?.();}
}
const doc={createElement:tag=>{const node=new Element(tag);node.ownerDocument=doc;return node;}};
function fixture(){const scope=doc.createElement('div'),content=doc.createElement('div');content.className='nas-window-content';scope.append(content);const heading=doc.createElement('header');heading.className='page-heading';const actions=doc.createElement('div');actions.className='catalog-window-actions';heading.append(actions);const status=doc.createElement('div');status.className='catalog-status';const warning=doc.createElement('div');warning.className='notice';const installed=doc.createElement('section');installed.className='app-installed-section';const discover=doc.createElement('section');discover.className='app-discover-section';const search=doc.createElement('input');search.className='search';search.value='photos';discover.append(search);content.append(heading,status,warning,installed,discover);return{scope,content,heading,actions,status,warning,installed,discover,search};}
const browser={};vm.runInNewContext(fs.readFileSync('titan/web/section_layout.js','utf8'),{window:browser});const ui=browser.TitanSectionLayout;
const first=fixture();ui.mount(first.scope,'apps');
const shell=first.content.querySelector('.sl-manager'),toolbar=shell.querySelector('.sl-toolbar'),nav=toolbar.querySelector('.sl-nav'),main=shell.querySelector('.sl-content');
assert.deepEqual(first.content.children,[shell],'Every catalog control and notice belongs to the one scrolling workspace');assert.equal(toolbar.children[1],first.actions,'Catalog actions share the compact navigation row');assert.deepEqual(shell.children,[toolbar,first.status,first.warning,main]);assert.equal(shell.attributes['aria-label'],'App Store');assert.deepEqual(main.children,[first.installed,first.discover]);assert.equal(first.installed.hidden,true);assert.equal(first.discover.hidden,false);assert.equal(first.discover.children[0],first.search,'Search input is moved, not replaced');assert.equal(first.search.value,'photos');
nav.children[0].click();assert.equal(first.installed.hidden,false);assert.equal(first.discover.hidden,true);nav.children[1].click();assert.equal(first.discover.hidden,false);assert.equal(first.search.value,'photos','Switching catalog sections preserves the current query');
ui.mount(first.scope,'apps');assert.equal(first.content.children.length,1,'Mounting twice does not create duplicate catalog navigation');nav.children[0].click();const second=fixture();ui.mount(second.scope,'apps');assert.equal(second.installed.hidden,false,'The selected section survives a workspace refresh');
const unaffected=fixture();ui.mount(unaffected.scope,'vms');assert.equal(unaffected.content.querySelector('.sl-manager'),null,'Other managers keep their own layout');
const css=fs.readFileSync('titan/web/compact_ui.css','utf8');assert.match(css,/\.sl-manager\{[^}]*overflow:auto/);assert.match(css,/\.sl-content\{[^}]*overflow:visible/);assert.match(css,/\.catalog-commandbar\{position:static/);
console.log('App Store workspace: one scrolling area, compact moved navigation/actions/notices, unstuck search, retained filters and section selection passed.');
