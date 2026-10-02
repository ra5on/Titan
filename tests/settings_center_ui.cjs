'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/settings_center.js');
const settings={hostname:'My NAS',repository:'ra5on/Titan',channel:'alpha',auto_check:true,check_interval:'weekly',installation:'automatic',window_day:0,window_hour:0,allow_reboot:false};
const session={version:'0.4.5',stage:'alpha'};
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const attr=(tag,name)=>new RegExp(`\\b${name}="([^"]*)"`).exec(tag)?.[1];
const decode=value=>String(value??'').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
// Model the existing FormData handler's successful controls, checkbox read and numeric conversion.
function submitted(html){
 const data={},counts={},elements={};
 for(const[tag]of html.matchAll(/<input\b[^>]*>/g)){
  const name=attr(tag,'name');if(!name)continue;counts[name]=(counts[name]||0)+1;const type=attr(tag,'type')||'text';
  if(type==='checkbox'){elements[name]={checked:/\bchecked\b/.test(tag)};if(elements[name].checked)data[name]=attr(tag,'value')||'on';}
  else data[name]=decode(attr(tag,'value'));
 }
 for(const[,tag,options]of html.matchAll(/(<select\b[^>]*>)([\s\S]*?)<\/select>/g)){
  const name=attr(tag,'name');if(!name)continue;counts[name]=(counts[name]||0)+1;
  const choices=[...options.matchAll(/<option\b[^>]*>/g)].map(match=>match[0]),choice=choices.find(option=>/\bselected\b/.test(option))||choices[0];data[name]=decode(attr(choice,'value'));
 }
 assert(elements.auto_check,'The existing handler always accesses form.elements.auto_check.checked');
 data.auto_check=elements.auto_check.checked;data.window_day=Number(data.window_day);data.window_hour=Number(data.window_hour);
 for(const[name,count]of Object.entries(counts))assert.equal(count,1,`Exactly one ${name} control must be submitted`);
 return data;
}

const hub=ui.render({settings,session,icon:key=>`<svg data-icon="${key}"></svg>`});
assert(hub.includes('data-settings-center'));assert(hub.includes('data-settings-search-input'));assert(hub.includes('10 Bereiche'));
assert.equal([...hub.matchAll(/data-settings-category=/g)].length,10);assert(!hub.includes('id="settings-form"'));
for(const route of ['settings?section=general','settings?section=updates','settings?section=components','storage','users','shares','services','backups','monitoring','logs'])assert(hub.includes(`href="#${route}"`),route);
assert(!hub.includes('javascript:'));assert(!hub.includes('coming soon'));
assert(ui.render({section:'unknown'}).includes('data-settings-search-input'));

for(const section of ['general','updates']){
 for(const auto_check of [false,true]){
  for(const[window_day,window_hour]of [[0,0],[6,23]]){
   const current={...settings,auto_check,window_day,window_hour},html=ui.render({section,settings:current,session,channelNotice:channel=>`Kanal: <${channel}>`});
   const expected={...current};delete expected.allow_reboot;assert.deepEqual(submitted(html),expected);
   assert(html.includes('id="settings-form"'));assert(html.includes(`data-settings-section="${section}"`));assert(html.includes('href="#settings"'));
   assert(html.includes(`href="#settings?section=${section}" class="active" aria-current="page"`));
   assert(!html.includes('name="allow_reboot"'));
   if(section==='general'){assert.match(html,/<input[^>]+name="hostname" type="text"/);assert.match(html,/<input type="checkbox" name="auto_check" hidden/);assert(html.includes('HTTPS · Port 5000'));assert(html.includes('href="#users"'));}
   else{assert.match(html,/<input type="hidden" name="hostname"/);assert.match(html,/<select[^>]+name="channel"/);assert(html.includes('id="channel-notice"'));assert(html.includes('Kanal: &lt;alpha&gt;'));assert(html.includes('href="#updates"'));}
  }
 }
}
const hostile=ui.render({section:'updates',settings:{...settings,hostname:'"><script>bad</script>',repository:'x/<bad>'},session:{version:'<v>',stage:'beta'},channelNotice:()=>'<script>bad()</script>'});
assert(!hostile.includes('<script>'));assert(hostile.includes('&lt;script&gt;'));assert(hostile.includes('x/&lt;bad&gt;'));assert(hostile.includes('v&lt;v&gt;'));assert(hostile.includes('Beta'));
const componentData={components:{docker:{available:false}},repair:{running:true}},calls=[];
const components=ui.render({section:'components',components:componentData,componentPanel:data=>{calls.push(data);return '<section class="component-panel"><button data-action="component-install" data-component="all">Reparieren</button></section>';}});
assert.equal(calls[0],componentData);assert(components.includes('data-action="component-install" data-component="all"'));assert(!components.includes('id="settings-form"'));
for(const route of ['apps','vms','services'])assert(components.includes(`href="#${route}"`));

class Element{
 constructor(){this.nodes=new Map();this.dataset={};this.events=new Map();this.value='';this.hidden=false;this.textContent='';this.focused=false;}
 querySelector(selector){return this.nodes.get(selector)||null;}
 querySelectorAll(selector){return this.nodes.get(selector)||[];}
 addEventListener(type,listener){if(!this.events.has(type))this.events.set(type,new Set());this.events.get(type).add(listener);}
 removeEventListener(type,listener){const set=this.events.get(type);set?.delete(listener);if(!set?.size)this.events.delete(type);}
 dispatch(type,details={}){const event={target:this,type,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},...details};for(const fn of [...(this.events.get(type)||[])])fn(event);return event;}
 focus(){this.focused=true;}
}
function fixture(){
 const main=new Element(),center=new Element(),input=new Element(),count=new Element(),empty=new Element(),reset=new Element();main.nodes.set('[data-settings-center]',center);
 const groups=['System','Daten','Betrieb'].map(()=>new Element());
 const tiles=[...hub.matchAll(/data-settings-category="([^"]*)" data-settings-search="([^"]*)"/g)].map(([,key,search],index)=>{const tile=new Element();tile.dataset={settingsCategory:key,settingsSearch:decode(search)};const group=index<3?0:index<6?1:2;const current=groups[group].nodes.get('[data-settings-category]')||[];current.push(tile);groups[group].nodes.set('[data-settings-category]',current);return tile;});
 for(const[key,node]of [['[data-settings-search-input]',input],['[data-settings-result-count]',count],['[data-settings-empty]',empty],['[data-settings-search-reset]',reset],['[data-settings-category]',tiles],['[data-settings-group]',groups]])center.nodes.set(key,node);
 return {main,center,input,count,empty,reset,groups,tiles,mount:()=>ui.mount(main)};
}
const f=fixture();f.mount();assert.equal(f.count.textContent,'10 Bereiche');assert(f.empty.hidden);
f.input.value='ALPHA';f.input.dispatch('input');assert.deepEqual(f.tiles.filter(tile=>!tile.hidden).map(tile=>tile.dataset.settingsCategory),['updates']);assert.equal(f.count.textContent,'1 Bereich');assert(f.groups[1].hidden&&f.groups[2].hidden);
f.input.value='lese Schreibrechte';f.input.dispatch('input');assert.deepEqual(f.tiles.filter(tile=>!tile.hidden).map(tile=>tile.dataset.settingsCategory),['shares']);
f.input.value='passwort';f.input.dispatch('input');assert.deepEqual(f.tiles.filter(tile=>!tile.hidden).map(tile=>tile.dataset.settingsCategory),['users']);
f.input.value='kapazitat';f.input.dispatch('input');assert.deepEqual(f.tiles.filter(tile=>!tile.hidden).map(tile=>tile.dataset.settingsCategory),['storage']);
f.input.value='<not found>';f.input.dispatch('input');assert.equal(f.count.textContent,'0 Bereiche');assert(!f.empty.hidden);assert(f.groups.every(group=>group.hidden));
f.reset.dispatch('click');assert.equal(f.input.value,'');assert(f.input.focused);assert.equal(f.count.textContent,'10 Bereiche');assert(f.groups.every(group=>!group.hidden));
f.input.value='docker';f.input.dispatch('input');assert.equal(f.count.textContent,'1 Bereich');assert(f.input.dispatch('keydown',{key:'Escape'}).defaultPrevented);assert.equal(f.count.textContent,'10 Bereiche');assert(!f.input.dispatch('keydown',{key:'Escape'}).defaultPrevented);
const other=fixture();other.mount();assert.equal(f.input.events.size,0);assert.equal(f.reset.events.size,0);ui.dispose();assert.equal(other.input.events.size,0);assert.equal(other.reset.events.size,0);
const subMain=new Element(),subCenter=new Element();subMain.nodes.set('[data-settings-center]',subCenter);assert(ui.mount(subMain));ui.dispose();assert.equal(ui.mount(new Element()),null);
assert.equal(ui.normalize('GRÖẞE / Kapazität'),'grosse / kapazitat');
console.log('Settings center: linked category hub, section routes, unchanged complete settings payloads, checked/unchecked preservation, zero-value windows, escaping, existing component actions, accent-aware search and lifecycle disposal passed.');
