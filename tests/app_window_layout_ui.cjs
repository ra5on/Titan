'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const ui=require('../titan/web/docker_workbench.js');
const css=fs.readFileSync('titan/web/app_window_layout.css','utf8');
assert.match(css,/\.storage-workspace \.storage-main\{[^}]*overflow:auto/);
assert.match(css,/\.storage-workspace \.storage-manager-content\{[^}]*overflow:visible/);
assert.match(css,/\.cp-content \.sc-save-actions\{position:static/);
assert.match(css,/\.um-manager \.um-toolbar\{position:static/);
assert.match(css,/@media\(max-height:480px\)/);
assert.doesNotMatch(css,/grid-template-columns|--titan-sidebar-width|--titan-inspector-width|\.desktop-window|\.topbar/,'Internal layout rules preserve desktop chrome and user sidebar widths');
const dockerCss=fs.readFileSync('titan/web/docker_workbench.css','utf8');
assert.match(dockerCss,/\.engine-workbench\.has-inspector \.engine-inspector\{[^}]*display:block;[^}]*overflow:auto/);
assert.match(dockerCss,/\.engine-inspector-scroll\{[^}]*overflow:visible/);

class Pane{
 constructor(kind,key){this.kind=kind;this.className=kind;this.dataset=kind==='engine-content'?{engineView:key}:{engineDetail:key};this.scrollTop=0;}
}
function fixture(){
 const events={},doc={hidden:false,activeElement:null,addEventListener:(type,fn)=>events[type]=fn,removeEventListener:type=>delete events[type]};
 const content={ownerDocument:doc,panes:[],controls:[],contains:node=>Boolean(node?.owned),addEventListener(){},removeEventListener(){},
  set innerHTML(value){this.html=value;this.panes=[];this.controls=[];const view=/class="engine-content" data-engine-view="([^"]+)"/.exec(value);if(view)this.panes.push(new Pane('engine-content',view[1]));const detail=/class="engine-inspector" data-engine-detail="([^"]+)"/.exec(value);if(detail)this.panes.push(new Pane('engine-inspector',detail[1]));for(const match of value.matchAll(/data-engine-action="([^"]+)" data-engine-id="([^"]*)"/g))this.controls.push({dataset:{engineAction:match[1],engineId:match[2]},owned:true,focus(options){doc.activeElement=this;this.focusOptions=options;},matches(){return false;}});},
  querySelectorAll(selector){if(selector==='.engine-content,.engine-inspector')return this.panes;if(selector==='[data-engine-action=select]')return this.controls.filter(node=>node.dataset.engineAction==='select');return [];},
  querySelector(selector){if(selector==='.engine-navigation')return {scrollWidth:0,clientWidth:900,querySelector(){return null;}};if(selector==='.engine-inspector [data-engine-action=drawer-close]')return this.controls.find(node=>node.dataset.engineAction==='drawer-close');return null;}
 };
 const click=async(type,key)=>{const target={owned:true,dataset:type==='tab'?{engineTab:key}:{engineAction:type,engineId:key},disabled:false};await events.click({target:{closest:selector=>selector===(type==='tab'?'[data-engine-tab]':'[data-engine-action]')?target:null}});};
 return {content,doc,click};
}
(async()=>{
 const originalWindow=global.window,originalLocation=global.location;
 global.window={};global.location={hostname:'nas.test'};
 const f=fixture(),container={id:'one',name:'First',image:'nginx',state:'running',networks:[],ports:{}};
 const data={available:true,containers:[container],images:[{Repository:'nginx',Tag:'stable',Size:'10 MB'}],networks:[],volumes:[]};
 try{
  await ui.mount(f.content,{api:async path=>path==='/api/docker-engine'?data:path==='/api/docker-metrics'?{containers:{one:{cpu_percent:1,memory_bytes:10}}}:{},action:async()=>({}),dialog(){},askYesNo:async()=>true,toast(){},bytes:String});
  let markup=f.content.html;
  assert(markup.indexOf('class="engine-content"')<markup.indexOf('class="engine-toolbar"'),'The toolbar belongs to the scrolling content');
  assert(markup.indexOf('class="engine-view-content"')<markup.indexOf('class="engine-footer"'),'Status footer follows the content inside that same pane');
  f.content.panes[0].scrollTop=82;
  await f.click('tab','containers');assert.equal(f.content.panes[0].scrollTop,0,'New sections start at the beginning');f.content.panes[0].scrollTop=235;
  await f.click('tab','images');assert.equal(f.content.panes[0].scrollTop,0);f.content.panes[0].scrollTop=95;
  await f.click('tab','containers');assert.equal(f.content.panes[0].scrollTop,235,'Returning restores the section position');
  await f.click('select','one');assert.equal(f.doc.activeElement.dataset.engineAction,'drawer-close','Opening details focuses Back');assert.equal(f.doc.activeElement.focusOptions.preventScroll,true,'Focus keeps restored detail scroll unchanged');
  f.content.panes.find(p=>p.kind==='engine-inspector').scrollTop=410;
  await f.click('drawer-close','');assert.equal(f.content.panes[0].scrollTop,235);assert.equal(f.doc.activeElement.dataset.engineAction,'select','Back returns keyboard focus to the selected container');assert.equal(f.doc.activeElement.focusOptions.preventScroll,true,'Back focus keeps the list position unchanged');
  await f.click('select','one');assert.equal(f.content.panes.find(p=>p.kind==='engine-inspector').scrollTop,410,'Each container detail retains its own scroll position');
  console.log('App layouts: single Docker pane scroll, per-section and detail scroll restore, Back focus, storage flow and short-window safeguards passed.');
 }finally{ui.dispose();global.window=originalWindow;global.location=originalLocation;}
})().catch(error=>{console.error(error);process.exitCode=1;});
