'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('titan/web/app.js','utf8');
const apiSource=source.slice(source.indexOf('async function api('),source.indexOf('\nfunction toast('));
const authSource=source.slice(source.indexOf('async function renderAuth('),source.indexOf('\nasync function boot('));

class Node {
 constructor(){this.nodes=new Map();this.events=new Map();this.attributes={};this.dataset={};this.value='';this.type='';this.textContent='';this.hidden=false;this.disabled=false;this.isConnected=true;this.focused=false;}
 querySelector(selector){return this.nodes.get(selector)||null;}
 querySelectorAll(selector){return this.nodes.get(selector)||[];}
 addEventListener(type,handler){this.events.set(type,handler);}
 setAttribute(name,value){this.attributes[name]=value;}
 removeAttribute(name){delete this.attributes[name];}
 focus(){this.focused=true;}
 async fire(type){return this.events.get(type)?.({target:this,preventDefault(){}});}
}
function fixture({setup=false,reply=async()=>({ok:true})}={}){
 const auth=new Node(),shell=new Node(),dialog=new Node(),requests=[],notices=[];let markup='',boots=0;
 Object.defineProperty(auth,'innerHTML',{get:()=>markup,set(value){
  for(const node of auth.nodes.values())if(node&&typeof node==='object')node.isConnected=false;
  markup=value;auth.nodes=new Map();
  const form=new Node(),error=new Node(),submit=new Node(),label=new Node(),toggles=[];
  error.hidden=true;label.textContent=value.match(/class="auth-submit"[^>]*><span>([^<]+)/)[1];submit.nodes.set('span',label);
  form.nodes.set('button[type=submit]',submit);form.inputs=new Map();
  for(const match of value.matchAll(/<input\b([^>]+)>/g)){
   const attributes=Object.fromEntries([...match[1].matchAll(/([a-z-]+)="([^"]*)"/g)].map(([,name,entry])=>[name,entry]));
   const input=new Node();input.type=attributes.type;input.attributes=attributes;
   auth.nodes.set('#'+attributes.id,input);form.inputs.set(attributes.name,input);
  }
  for(const match of value.matchAll(/<button\b([^>]*data-auth-password="[^"]+"[^>]*)>/g)){
   const attributes=Object.fromEntries([...match[1].matchAll(/([a-z-]+)="([^"]*)"/g)].map(([,name,entry])=>[name,entry]));
   const toggle=new Node();toggle.attributes=attributes;toggle.dataset.authPassword=attributes['data-auth-password'];toggle.textContent='Anzeigen';toggles.push(toggle);
  }
  auth.nodes.set('form',form);auth.nodes.set('#auth-error',error);auth.nodes.set('[data-auth-password]',toggles);
 }});
 const document={querySelector(selector){if(selector==='#auth')return auth;if(selector==='#shell')return shell;if(selector==='#dialog')return dialog;if(selector==='#auth-error')return auth.querySelector(selector);throw Error('Unexpected selector '+selector);}};
 const session={user:null,setup_required:setup,...(setup?{setup_csrf:'one-time-setup-csrf'}:{})};
 const context=vm.createContext({window:{},document,session,desktopWidgets:null,desktopShortcuts:null,desktopWorkspace:null,desktopEmbedded:false,embeddedReady:false,loginUpdateController:null,loginUpdateOffer:null,fileDialogRequest:0,filesView:null,
  $:(selector,root=document)=>root.querySelector(selector),icon:()=>'<svg aria-hidden="true"></svg>',toast:message=>notices.push(message),boot:async()=>{boots++;},
  FormData:class{constructor(form){this.form=form;}get(name){return this.form.inputs.get(name)?.value??null;}},
  fetch:async(path,options)=>{const request={path,...options,body:options.body?JSON.parse(options.body):undefined};requests.push(request);const value=await reply(request);return{ok:value.status===undefined||value.status<400,status:value.status||200,json:async()=>value};}});
 vm.runInContext(apiSource+'\n'+authSource,context);
 return {auth,shell,requests,notices,context,boots:()=>boots,render:()=>vm.runInContext('renderAuth('+setup+')',context),
  form:()=>auth.querySelector('form'),notice:()=>auth.querySelector('#auth-error'),submit:()=>auth.querySelector('form').querySelector('button[type=submit]'),
  fill(values){for(const[name,value]of Object.entries(values))auth.querySelector('form').inputs.get(name).value=value;}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const login=fixture();await login.render();assert(login.shell.hidden);assert(!login.auth.hidden);
 assert(login.auth.querySelector('#f-name').focused,'Username receives initial keyboard focus');
 assert(login.auth.innerHTML.includes('aria-labelledby="auth-title"'));assert(login.auth.innerHTML.includes('name="otp"'));assert(!login.auth.innerHTML.includes('password_confirmation'));
 assert.equal(login.auth.querySelector('#f-password').attributes.autocomplete,'current-password');
 login.fill({name:'alice',password:'correct-test-password',otp:'123456'});
 const toggle=login.auth.querySelectorAll('[data-auth-password]')[0];await toggle.fire('click');
 assert.equal(login.auth.querySelector('#f-password').type,'text');assert.equal(toggle.attributes['aria-pressed'],'true');assert.equal(toggle.attributes['aria-label'],'Passwort verbergen');
 assert.equal(login.auth.querySelector('#f-password').value,'correct-test-password','Visibility never changes the credential');
 await toggle.fire('click');assert.equal(login.auth.querySelector('#f-password').type,'password');assert.equal(toggle.attributes['aria-pressed'],'false');
 await login.form().fire('submit');assert.equal(login.requests[0].path,'/api/login');assert.deepEqual(login.requests[0].body,{name:'alice',password:'correct-test-password',otp:'123456'});assert.equal(login.boots(),1);assert(!login.submit().disabled);
 login.fill({otp:''});await login.form().fire('submit');assert(!Object.hasOwn(login.requests[1].body,'otp'),'Empty OTP is not sent');

 let release;const pending=new Promise(resolve=>{release=resolve;});
 const limited=fixture({reply:async()=>{await pending;return{status:429,error:'<script>Kein Zugriff</script>',retry_after:61};}});await limited.render();limited.fill({name:'alice',password:'wrong-test-password'});
 const first=limited.form().fire('submit');await tick();assert(limited.submit().disabled);assert.equal(limited.form().attributes['aria-busy'],'true');assert.equal(limited.submit().querySelector('span').textContent,'Anmeldung läuft …');
 await limited.form().fire('submit');assert.equal(limited.requests.length,1,'A pending sign-in cannot be submitted twice');
 release();await first;assert(!limited.notice().hidden);assert(limited.notice().focused);assert.equal(limited.notice().textContent,'<script>Kein Zugriff</script> Wartezeit: 2 Min.');
 assert.equal(limited.auth.querySelector('#f-password').value,'wrong-test-password');assert(!limited.submit().disabled);assert(!Object.hasOwn(limited.form().attributes,'aria-busy'));assert.equal(limited.submit().querySelector('span').textContent,'Anmelden');

 const setup=fixture({setup:true});await setup.render();assert(!setup.auth.innerHTML.includes('name="otp"'));assert(setup.auth.innerHTML.includes('auth-password-hint'));assert.equal(setup.auth.querySelector('#f-password').attributes.autocomplete,'new-password');assert.equal(setup.auth.querySelectorAll('[data-auth-password]').length,2);
 setup.fill({name:'owner',password:'first-test-password',password_confirmation:'different-test-password'});await setup.form().fire('submit');assert.equal(setup.requests.length,0);assert(setup.notice().textContent.includes('nicht überein'));
 setup.fill({password_confirmation:'first-test-password'});await setup.form().fire('submit');assert.equal(setup.requests[0].path,'/api/setup');assert.equal(setup.requests[0].headers['X-CSRF-Token'],'one-time-setup-csrf');assert.deepEqual(setup.requests[0].body,{name:'owner',password:'first-test-password'});
 assert.equal(setup.context.session.setup_required,false);assert(!Object.hasOwn(setup.context.session,'setup_csrf'));assert(setup.auth.innerHTML.includes('Anmelden'));assert.equal(setup.boots(),0);assert.deepEqual(setup.notices,['Administrator angelegt. Bitte anmelden.']);

 const conflict=fixture({setup:true,reply:async request=>request.path==='/api/setup'?{status:409,error:'Administrator ist bereits eingerichtet.'}:{user:null,setup_required:false}});await conflict.render();conflict.fill({name:'owner',password:'first-test-password',password_confirmation:'first-test-password'});await conflict.form().fire('submit');
 assert.deepEqual(conflict.requests.map(item=>item.path),['/api/setup','/api/session']);assert(!conflict.auth.innerHTML.includes('password_confirmation'));assert(!conflict.notice().hidden);assert.equal(conflict.notice().textContent,'Administrator ist bereits eingerichtet.');
 assert.equal(conflict.auth.querySelector('#f-password').value,'','Setup conflict renders a fresh login without retaining secrets');
 console.log('Sign-in UI: password visibility, focus, OTP and setup payloads, setup CSRF, duplicate-submit prevention, busy state, literal errors, retry delay and setup-conflict recovery passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
