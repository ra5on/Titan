'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const timers=[],cleared=[];
const context=vm.createContext({window:{},setTimeout,Date,setInterval(fn,delay){timers.push({fn,delay});return timers.length;},clearInterval(id){cleared.push(id);}});
vm.runInContext(fs.readFileSync('titan/web/security_center.js','utf8'),context);
const ui=context.window.TitanSecurity,revision='a'.repeat(64),base={settings:{schema:1,ip:{enabled:true,attempts:5,window_minutes:5,block_minutes:15},account:{enabled:false,attempts:8,window_minutes:10,block_minutes:30}},revision,blocks:[{id:'b'.repeat(32),type:'account',address:'192.0.2.1',username:'<alice>',reason:'<script>bad</script>',expires:Math.floor(Date.now()/1000)+89,remaining_seconds:89}]};
const html=ui.protectionPanel(base);
assert(html.includes('Anmeldeschutz'));assert(html.includes('IP-Sperre aktivieren'));assert(html.includes('Kontoschutz aktivieren'));assert(html.includes('Zwei-Faktor-Anmeldungen'));assert(html.includes('Sperren bleiben nach einem Neustart erhalten'));
assert(html.includes('&lt;alice&gt;'));assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;bad&lt;/script&gt;'));assert(html.includes('data-login-unblock="'+'b'.repeat(32)+'"'));
assert(/name="account_attempts"[^>]*disabled/.test(html));assert(!/name="ip_attempts"[^>]*disabled/.test(html));assert(html.includes('max="10080"'));assert(ui.protectionBlocks({...base,blocked_count:300}).includes('1 von 300 aktiven Sperren'));
assert.equal(ui.remaining(0),'Abgelaufen');assert.equal(ui.remaining(59),'59 Sek.');assert.equal(ui.remaining(61),'2 Min.');
assert(ui.protectionPanel(null,'<script>').includes('&lt;script&gt;'));assert(ui.protectionPanel(null,'No API').includes('data-login-retry'));
const common={checks:[],two_factor:false,sessions:[],login_events:[],all_users:false};
assert(!ui.render(common,{admin:false,protection:base}).includes('data-login-protection-form'),'Ordinary users do not see administrative protection controls');
assert(ui.render(common,{admin:true,protection:base}).includes('data-login-protection-form'));
class Node{
 constructor(){this.nodes=new Map();this.events=new Map();this.elements={};this.dataset={};this.disabled=false;this.hidden=false;this.textContent='';this.value='';this.focused=false;}
 querySelector(selector){return this.nodes.get(selector)||null;}
 querySelectorAll(selector){return this.nodes.get(selector)||[];}
 addEventListener(type,fn){this.events.set(type,fn);}
 removeEventListener(type,fn){if(this.events.get(type)===fn)this.events.delete(type);}
 async fire(type,event={}){return this.events.get(type)?.({target:this,preventDefault(){},...event});}
 focus(){this.focused=true;}
}
function fixture(){const center=new Node(),panel=new Node(),form=new Node(),submit=new Node(),error=new Node(),status=new Node(),list=new Node(),countdown=new Node();countdown.dataset.loginBlockUntil=String(base.blocks[0].expires);list.replaceWith=value=>{list.latest=value;};center.ownerDocument={createElement(){return {innerHTML:'',firstElementChild:{marker:'new list'}};}};center.nodes.set('[data-login-protection]',panel);panel.nodes.set('[data-login-protection-form]',form);panel.nodes.set('[data-login-protection-error]',error);panel.nodes.set('[data-login-protection-status]',status);panel.nodes.set('[data-login-block-list]',list);panel.nodes.set('[data-login-block-refresh]',new Node());panel.nodes.set('[data-login-block-until]',[countdown]);form.nodes.set('[type=submit]',submit);
 for(const kind of ['ip','account']){const group=new Node(),numbers=[];form.nodes.set(`[data-login-mode="${kind}"]`,group);for(const key of ['enabled','attempts','window_minutes','block_minutes']){const element=new Node();element.name=kind+'_'+key;element.checked=base.settings[kind].enabled;element.value=String(base.settings[kind][key]);element.disabled=key!=='enabled'&&!element.checked;form.elements[element.name]=element;if(key!=='enabled')numbers.push(element);}group.nodes.set('input[type=number]',numbers);}
 return {center,panel,form,submit,error,status,list,countdown};}
(async()=>{
 const calls=[],notices=[],f=fixture();let confirms=0,saved=0,allow=true,reject=false;
 const options={api:async(path,body)=>{calls.push({path,body});if(reject)throw Error('Einstellungen wurden zwischenzeitlich geändert.');return {...base,revision:'c'.repeat(64),settings:body?.settings||base.settings,blocks:[]};},toast:(...args)=>notices.push(args),saved:()=>saved++,confirm:async()=>{confirms++;return allow;}};
 const mounted=ui.mountProtection(f.center,base,options);assert.equal(timers.at(-1).delay,1000);assert.equal(f.countdown.textContent,'2 Min.');
 const account=f.form.elements.account_enabled;account.checked=true;await f.form.fire('change',{target:account});assert(!f.form.elements.account_attempts.disabled);
 const ip=f.form.elements.ip_enabled;ip.checked=false;await f.form.fire('change',{target:ip});assert(f.form.elements.ip_attempts.disabled);
 f.form.elements.account_attempts.value='9';f.form.elements.account_window_minutes.value='12';f.form.elements.account_block_minutes.value='60';
 await f.form.fire('submit');const save=calls.at(-1);assert.equal(save.path,'/api/security/login-protection');assert.equal(save.body.expected_revision,revision);assert.equal(save.body.settings.schema,1);assert.equal(save.body.settings.ip.enabled,false);assert.equal(save.body.settings.ip.attempts,5);assert.equal(save.body.settings.account.enabled,true);assert.equal(save.body.settings.account.attempts,9);assert.equal(save.body.settings.account.block_minutes,60);assert.equal(saved,1);assert(f.status.textContent.includes('gespeichert'));assert(!f.submit.disabled);assert(f.submit.focused);
 reject=true;await f.form.fire('submit');assert.equal(calls.at(-1).body.expected_revision,'c'.repeat(64),'Subsequent saves use the returned configuration revision');assert(!f.error.hidden);assert(f.error.textContent.includes('zwischenzeitlich'));assert.equal(saved,1);assert.equal(f.form.elements.account_attempts.value,'9','Failure keeps entered values');reject=false;
 const unblock=new Node();unblock.dataset.loginUnblock='b'.repeat(32);const target={closest(selector){return selector==='[data-login-unblock]'?unblock:null;}};
 allow=false;const before=calls.length;await f.panel.fire('click',{target});assert.equal(calls.length,before,'No means no mutation');allow=true;await f.panel.fire('click',{target});assert.equal(calls.at(-1).path,'/api/security/login-protection/unblock');assert.equal(calls.at(-1).body.id,'b'.repeat(32));assert.equal(confirms,2);assert(f.status.textContent.includes('aufgehoben'));
 const refresh=new Node();await f.panel.fire('click',{target:{closest(selector){return selector==='[data-login-block-refresh]'?refresh:null;}}});assert.equal(calls.at(-1).path,'/api/security/login-protection');assert.equal(calls.at(-1).body,undefined);assert.equal(f.form.elements.account_attempts.value,'9','Refreshing the block list does not overwrite form edits');assert(refresh.focused,'Refreshing restores focus after the button was temporarily disabled');
 mounted.dispose();assert(cleared.length);assert.equal(f.panel.events.size,0);assert.equal(f.form.events.size,0);
 // A response arriving after navigation must not update the detached panel or show a toast.
 const late=fixture();let resolve;const pending=new Promise(done=>{resolve=done;});const later=ui.mountProtection(late.center,base,{api:()=>pending,toast:()=>{throw Error('Late toast');}});const waiting=late.form.fire('submit');later.dispose();resolve(base);await waiting;assert.equal(late.status.textContent,'Wird gespeichert …');assert.equal(late.list.latest,undefined);
 console.log('Login protection UI: administrative scope, escaped blocks, threshold bounds, enabled modes, full revisioned settings, failed-save preservation, yes/no unblock, refresh without resetting edits, countdown and disposal passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
