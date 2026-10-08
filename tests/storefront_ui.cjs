'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),ui=require('../titan/web/apps_center.js'),{fixture}=require('./desktop_test_dom.cjs');
const ids=['titan-immich','titan-adguard','titan-tailscale'];
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const installation={revision:'cf',status:'idle',runtime:{state:'missing'}};
function store(options={}){
 const f=fixture(),scope=f.doc.createElement('section');f.doc.body.append(scope);scope.className='nas-window-content';
 const context={admin:true,catalog:{apps:ids.map((id,index)=>({id,name:['Immich','AdGuard Home','Tailscale'][index],description:['Fotos und Videos','Schutz für dein Netzwerk','Privates Netzwerk'][index]}))},installation,installed:[{id:'titan-adguard',name:'AdGuard Home'}],...options};
 scope.innerHTML=ui.render(context);let lastMarkup='';
 function hydrate(){const panel=scope.querySelector('[data-apps-center]');for(const form of panel.querySelectorAll('form')){form.elements={};for(const input of form.querySelectorAll('input,select')){input.value=input.getAttribute('value')??input.querySelector('option')?.getAttribute('value')??'';form.elements[input.getAttribute('name')]=input;}}panel.insertBefore=function(node,before){node.remove();node.parentElement=this;const at=this.children.indexOf(before);this.children.splice(at<0?this.children.length:at,0,node);};Object.defineProperty(panel,'outerHTML',{set(html){lastMarkup=html;scope.innerHTML=html;hydrate();}});}
 hydrate();const calls=[],api=(path,body)=>new Promise(resolve=>calls.push({path,body,resolve}));
 const controller=ui.mount(scope,{api,admin:context.admin,demo:context.demo});
 const query=selector=>scope.querySelector(selector),click=selector=>f.doc.dispatch(query(selector),'click');
 return {...f,scope,query,click,calls,controller,get lastMarkup(){return lastMarkup;}};
}
async function main(){
 let f=store({demo:true});assert.equal(f.query('[data-store-search]').disabled,false,'Search stays usable in preview');assert.equal(f.query('[data-store-category="network"]').disabled,false);
 assert.equal(f.query('[data-store-result]').textContent,'4 Apps');
 f.click('[data-store-category="network"]');assert.equal(f.query('[data-store-result]').textContent,'2 Apps');assert.equal(f.query('[data-store-card="titan-immich"]').hidden,true);assert.equal(f.query('[data-store-card="titan-tailscale"]').hidden,false);assert.equal(f.query('[data-store-featured]').hidden,true);assert.equal(f.query('[data-store-category="network"]').getAttribute('aria-pressed'),'true');
 f.click('[data-store-category="all"]');const input=f.query('[data-store-search]');input.value='Erinnerungen';f.doc.dispatch(input,'input');assert.equal(f.query('[data-store-result]').textContent,'1 App');assert.equal(f.query('[data-store-card="titan-immich"]').hidden,false);
 input.value='finde-ich-nicht';f.doc.dispatch(input,'input');assert.equal(f.query('[data-store-empty]').hidden,false);input.value='';f.doc.dispatch(input,'input');
 f.click('[data-store-category="installed"]');assert.equal(f.query('[data-store-result]').textContent,'1 App');assert.equal(f.query('[data-store-card="titan-adguard"]').hidden,false);
 f.click('[data-store-category="all"]');f.click('[data-store-open="titan-immich"]');assert.equal(f.query('[data-apps-center]').getAttribute('data-store-detail'),'titan-immich');assert.equal(f.query('[data-native-app="titan-immich"]').getAttribute('data-active'),'');assert.equal(f.query('[data-native-app="titan-immich"]').querySelector('[data-native-detail]').hidden,false);assert.equal(f.query('[data-native-app="titan-immich"]').querySelector('[data-native-back]').disabled,false,'Back navigation is never disabled by demo mode');
 f.click('[data-native-back]');assert.equal(f.query('[data-apps-center]').getAttribute('data-store-detail'),null);assert.equal(f.query('[data-native-app="titan-immich"]').querySelector('[data-native-detail]').hidden,true);
 f.click('[data-store-open="titan-cloudflared"]');assert.equal(f.query('[data-apps-center]').getAttribute('data-store-detail'),'titan-cloudflared');assert.equal(f.query('[data-apps-detail]').hidden,false);f.click('[data-apps-close]');assert.equal(f.query('[data-apps-center]').getAttribute('data-store-detail'),null);assert.equal(f.query('[data-apps-detail]').hidden,true);ui.dispose();
 // Refresh retains query, selected category, native detail, and does not replay
 // an enter animation on every Cloudflare status update.
 f=store();for(let n=0;n<3;n++){f.calls[n].resolve({status:'idle',installed:ids[n]==='titan-adguard',runtime:{}});await settle();}
 f.click('[data-store-category="network"]');f.query('[data-store-search]').value='Tunnel';f.doc.dispatch(f.query('[data-store-search]'),'input');f.click('[data-apps-open]');assert(f.query('[data-apps-detail]').classList.contains('is-entering'));
 const refreshing=f.controller.refresh();f.calls[3].resolve(installation);await refreshing;assert.equal(f.query('[data-store-search]').value,'Tunnel');assert.equal(f.query('[data-store-category="network"]').getAttribute('aria-pressed'),'true');assert.equal(f.query('[data-store-result]').textContent,'1 App');assert.equal(f.query('[data-apps-center]').getAttribute('data-store-detail'),'titan-cloudflared');assert(!f.query('[data-apps-detail]').classList.contains('is-entering'),'Polling does not fade the detail view out and in');assert.match(f.lastMarkup,/ac-feature-photos/,'Local feature availability survives whitelisted Cloudflare hydration');ui.dispose();
 const restricted=store({admin:false});restricted.click('[data-store-open="titan-immich"]');assert.equal(restricted.query('[data-native-back]').disabled,false);restricted.click('[data-native-back]');assert.equal(restricted.query('[data-apps-center]').getAttribute('data-store-detail'),null);assert.equal(restricted.calls.length,0);ui.dispose();
 assert.equal(ui.matchesApp('titan-adguard','AdGuard','',true,'dns','privacy'),true);
 assert.equal(ui.matchesApp('titan-adguard','AdGuard','',false,'','installed'),false);
 assert.match(fs.readFileSync('titan/web/apps_center.css','utf8'),/\.ac-categories\{display:flex;flex-direction:row;/);
 console.log('Storefront: local features, real search/category/installed filters, empty result, focused detail/back navigation with demo/rights, retained search/category/feature state and no repeated poll animation passed.');
}
main().catch(error=>{ui.dispose();console.error(error);process.exitCode=1;});
