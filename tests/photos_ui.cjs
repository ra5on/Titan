'use strict';
const assert=require('node:assert/strict');
const ui=require('../titan/web/photos.js');
(async()=>{
 const params=new URL(ui.query({share:'famille & amis',path:'Urlaub/2026',search:'<img>',offset:48}),'http://nas').searchParams;
 assert.equal(params.get('share'),'famille & amis');assert.equal(params.get('recursive'),'1');assert.equal(params.get('type'),'image');assert.equal(params.get('limit'),'48');assert.equal(params.get('offset'),'48');
 const url=new URL(ui.fileUrl('a&b','?evil#name.jpg',true),'http://nas');assert.equal(url.pathname,'/api/file');assert.equal(url.searchParams.get('path'),'?evil#name.jpg');assert.equal(url.searchParams.get('preview'),'1');
 assert(ui.canPreview({name:'A.JPG',size:100}));for(const name of ['x.svg','x.html','x.heic','x.png.html'])assert(!ui.canPreview({name,size:10}));assert(!ui.canPreview({name:'x.png',size:25*1024*1024}));assert(!ui.canPreview({name:'x.png',size:10,directory:true}));
 const html=ui.cards([{name:'<img onerror="evil">.jpg',path:'" onclick="evil',size:100}],'<script>');assert(!html.includes('<script>'));assert(!html.includes(' onclick="evil'));assert(html.includes('&lt;img'));assert(html.includes('loading="lazy"'));
 const calls=[],received=[];const loader=ui.createLoader((path,body,options)=>new Promise((resolve,reject)=>calls.push({path,options,resolve,reject})),v=>received.push(v));
 const first=loader.load({share:'one'}),second=loader.load({share:'two'});assert(calls[0].options.signal.aborted);calls[1].resolve({entries:['new']});await second;calls[0].resolve({entries:['old']});await first;assert.deepEqual(received.filter(v=>v.data).map(v=>v.data.entries),[['new']],'A late response cannot reveal a previously selected share');
 const third=loader.load({share:'denied'});calls[2].reject(new Error('Zugriff verweigert'));await third;assert.equal(received.at(-1).error,'Zugriff verweigert');
 const last=loader.load({share:'last'}),before=received.length;loader.dispose();assert(calls[3].options.signal.aborted);calls[3].resolve({entries:['secret']});await last;assert.equal(received.length,before,'Closed gallery ignores pending results');
 console.log('Photos: bounded authorized URLs, safe previews, escaped filenames, lazy loading, stale-response isolation, errors and disposal passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
