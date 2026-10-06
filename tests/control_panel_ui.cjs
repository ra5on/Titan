const assert=require('node:assert/strict');
const ui=require('../titan/web/control_panel.js');
for(const [section,page] of [['','settings'],['general','settings'],['components','settings'],['users','users'],['updates','updates'],['shares','shares'],['services','services'],['backups','backups'],['logs','logs']]){
 assert.deepEqual(ui.resolve('#settings'+(section?'?section='+section:'')),{section,page});
 const html=ui.render(section,'<form id="real-form">Existing controls</form>',{icon:id=>`<svg data-icon="${id}"></svg>`});
 assert(html.includes('data-control-panel'));
 if(section){assert(html.includes('<form id="real-form">'));assert(html.includes('aria-current="page"'));assert(html.includes(`value="${section}" selected`));}
 else {assert(html.includes('data-cp-search'));assert.equal((html.match(/data-cp-item /g)||[]).length,11);assert(!html.includes('real-form'));}
}
assert.equal(ui.resolve('#docker'),null);
for(const section of ['groups','security']) {
 assert.deepEqual(ui.resolve('#settings?section='+section),{section,page:section});
 assert(ui.render(section,'<form>Controls</form>').includes(`value="${section}" selected`));
}
for(const section of ['../../etc/passwd','constructor','<script>','unknown'])assert.deepEqual(ui.resolve('#settings?section='+encodeURIComponent(section)),{section:'',page:'settings'});
assert.equal(ui.internal('#users'),'#settings?section=users');assert.equal(ui.internal('#docker'),'#docker');assert.equal(ui.internal('#settings?section=general'),'#settings?section=general');
const app=require('fs').readFileSync('titan/web/app.js','utf8');
assert(app.includes("controlRoute=session.user.role==='admin'?"));
assert(app.includes('window.TitanControlPanel.render(controlRoute.section,html,{icon,esc})'));
assert(app.includes("event.source===window.parent&&event.data?.type==='titan-navigate'"));
assert.deepEqual(ui.normalizePreferences({view:'list',favorites:['users','unknown','shares','users','__proto__']}),{view:'list',favorites:['users','shares']});
assert.deepEqual(ui.normalizePreferences(null),{view:'grid',favorites:[]});
const storage={data:new Map(),getItem(key){return this.data.get(key)||null;},setItem(key,value){this.data.set(key,value);}};
assert.equal(ui.writePreferences(storage,'alice',{view:'list',favorites:['updates']}),true);
assert.deepEqual(ui.readPreferences(storage,'alice'),{view:'list',favorites:['updates']});
assert.deepEqual(ui.readPreferences(storage,'bob'),{view:'grid',favorites:[]});
assert.equal(ui.writePreferences(null,'alice',{}),false);
assert.deepEqual(ui.readPreferences({getItem(){throw Error('blocked');}},'alice'),{view:'grid',favorites:[]});
const hub=ui.render('', '');
assert(hub.includes('data-cp-view="list"'));assert(hub.includes('data-cp-favorites'));assert.equal((hub.match(/data-cp-pin=/g)||[]).length,11);
console.log('Control Panel: safe section routing, persistent navigation, existing forms and mobile selector passed');
