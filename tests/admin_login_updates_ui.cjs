'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/admin_login_updates.js');
(async()=>{
 let calls=[],notifications=[];const api=async(...args)=>{calls.push(args);return {job:'job-check'};},wait=async(fn,id,options)=>{assert.equal(fn,api);assert.equal(id,'job-check');assert.equal(options.maxWait,120000);return {result:{available:true,latest:'v0.9.0'}};};
 for(const user of [null,{role:'user'},{role:'Admin'}])await ui.check({user,api,wait,onAvailable:value=>notifications.push(value)});
 await ui.check({user:{role:'admin'},embedded:true,api,wait});assert.equal(calls.length,0,'Users and app-frame boots never check for updates');
 for(let login=0;login<2;login++)await ui.check({user:{role:'admin'},api,wait,onAvailable:value=>notifications.push(value)});
 assert.equal(calls.length,2,'Every admin login requests a fresh check');assert.equal(notifications.length,2);assert.deepEqual(calls[0].slice(0,2),['/api/updates/check',{update_kind:'all'}]);
 notifications=[];await ui.check({user:{role:'admin'},api,wait:async()=>({result:{available:false}}),onAvailable:value=>notifications.push(value)});await ui.check({user:{role:'admin'},api,wait:async()=>({result:{available:true,error:'offline'}}),onAvailable:value=>notifications.push(value)});assert.equal(notifications.length,0);
 const controller=new AbortController();await ui.check({user:{role:'admin'},api,signal:controller.signal,wait:async()=>{controller.abort();return {result:{available:true}};},onAvailable:value=>notifications.push(value)});assert.equal(notifications.length,0,'Logging out suppresses a delayed offer');
 assert(calls.every(row=>row[0]==='/api/updates/check'),'A login check never installs or reboots');console.log('Admin login update checks: every login, user/frame isolation, unavailable/error offers, logout and no installation passed.');
})();
