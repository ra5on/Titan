'use strict';
// UI lifecycle only: no server authentication, shell or privileged action runs.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const turns=()=>new Promise(resolve=>setImmediate(resolve));
class Node{
 constructor(){this.nodes=new Map();this.listeners=new Map();this.disabled=false;this.textContent='';}
 querySelector(key){return this.nodes.get(key)||null;}
 addEventListener(type,callback){const set=this.listeners.get(type)||new Set();set.add(callback);this.listeners.set(type,set);}
 removeEventListener(type,callback){this.listeners.get(type)?.delete(callback);}
 click(){for(const callback of [...(this.listeners.get('click')||[])])callback();}
}
const timers=new Map();let timerId=0,now=100000;
const box={module:{exports:{}},Date:{now:()=>now*1000},setInterval:callback=>{const id=++timerId;timers.set(id,callback);return id;},clearInterval:id=>timers.delete(id)};
vm.runInNewContext(fs.readFileSync(require.resolve('../titan/web/root_access.js'),'utf8'),box);
const root=box.module.exports;
function fixture(data={enabled:false},extra={}){
 const scope=new Node(),bar=new Node(),toggle=new Node(),files=new Node(),countdown=new Node();
 scope.nodes.set('[data-root-access]',bar);bar.nodes.set('[data-root-toggle]',toggle);bar.nodes.set('[data-root-files]',files);bar.nodes.set('[data-root-countdown]',countdown);
 const dialogs=[],requests=[],notices=[];let refreshes=0,opens=0;
 const ctx={api:async(path,body)=>{requests.push({path,body});return extra.api?extra.api(path,body):{enabled:false};},dialog:(title,html,submit)=>dialogs.push({title,html,submit}),toast:(text,error)=>notices.push({text,error}),refresh:async()=>{refreshes++;},openFiles:()=>{opens++;}};
 const controller=root.mount(scope,data,ctx);
 return{scope,bar,toggle,files,countdown,dialogs,requests,notices,controller,refreshes:()=>refreshes,opens:()=>opens};
}
(async()=>{
 assert.match(root.render(),/Geschützter NAS-Modus/);
 assert(!root.render().includes('data-root-files'));
 assert.match(root.render({enabled:true},'files'),/Root-Modus aktiv/);
 assert.match(root.render({enabled:true,demo:true},'files'),/Root-Modus · Demo/);
 assert.match(root.render({enabled:true},'files'),/data-root-files/);
 assert(!root.render({enabled:true},'terminal').includes('data-root-files'));

 // No password is requested until the administrator explicitly activates root.
 let f=fixture({enabled:false,two_factor_required:true,demo:true});
 assert.equal(f.requests.length,0);f.toggle.click();assert.equal(f.requests.length,0);
 let form=f.dialogs.at(-1);assert.match(form.html,/type="password"/);assert.match(form.html,/autocomplete="current-password"/);assert.match(form.html,/name="otp"/);assert.match(form.html,/Isolierte Demo/);assert.match(form.html,/nicht automatisch entsperrt/);
 await form.submit(new Map([['password','temporary-secret'],['otp','123456'],['minutes','5']]));
 assert.equal(f.requests.length,1);assert.equal(f.requests[0].path,'/api/root-access');
 assert.equal(JSON.stringify(f.requests[0].body),JSON.stringify({password:'temporary-secret',otp:'123456',minutes:5}));
 assert.equal(f.refreshes(),1);assert(f.notices.every(item=>!item.text.includes('temporary-secret')&&!item.text.includes('123456')));
 root.dispose();assert.equal(f.toggle.listeners.get('click').size,0);

 // Authentication errors remain in the dialog; no success or page transition.
 f=fixture({enabled:false},{api:async()=>{throw Error('Passwort oder Sicherheitscode ist falsch.');}});f.toggle.click();form=f.dialogs.at(-1);
 assert(!form.html.includes('name="otp"'));
 await assert.rejects(form.submit(new Map([['password','wrong'],['minutes','15']])),/Passwort/);
 assert.equal(f.refreshes(),0);assert.equal(f.notices.length,0);root.dispose();

 // A double click cannot issue duplicate revocations and system files are explicit.
 let resolve;
 f=fixture({enabled:true,expires:now+90},{api:async()=>new Promise(done=>resolve=done)});
 assert.equal(f.countdown.textContent,'1:30 Min.');assert.equal(timers.size,1);f.files.click();assert.equal(f.opens(),1);
 f.toggle.click();f.toggle.click();assert.equal(f.requests.length,1);assert.equal(f.toggle.disabled,true);
 assert.equal(JSON.stringify(f.requests[0].body),JSON.stringify({enabled:false}));resolve({enabled:false});await turns();
 assert.equal(f.refreshes(),1);assert.equal(f.toggle.disabled,false);root.dispose();assert.equal(timers.size,0);

 // Expiry is verified by the server; mounting another page disposes old listeners.
 f=fixture({enabled:true,expires:now+2});const old=f;
 now+=3;for(const callback of timers.values())callback();await turns();
 assert.equal(f.requests[0].path,'/api/root-access');assert.equal(f.requests[0].body,undefined);assert.equal(f.refreshes(),1);
 f=fixture();assert.equal(timers.size,0);old.toggle.click();assert.equal(old.requests.length,1);assert.equal(old.files.listeners.get('click').size,0);
 root.dispose();assert.equal(timers.size,0);
 console.log('Root UI: explicit fresh authentication, OTP, isolated demo labels, duration, revocation, countdown and cleanup passed.');
})().catch(error=>{root.dispose();console.error(error);process.exitCode=1;});
