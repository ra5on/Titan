// Console setup and recovery are automatic; guest shortcuts stay optional.
const vm = new URLSearchParams(location.search).get('vm');
const screen = document.querySelector('#screen');
const status = document.querySelector('#console-status');
const retry = document.querySelector('#reconnect');
let rfb=null,timer=null,messageTimer=null,layoutTimer=null,closed=false,attempt=0,generation=0,connected=false;
const overlay=document.querySelector('#console-connection'),connectionMessage=document.querySelector('#connection-message'),notice=document.querySelector('#console-message');
const name=new URLSearchParams(location.search).get('name');if(name)document.querySelector('#console-name').textContent=name.slice(0,96);
function feedback(message){notice.textContent=message;notice.hidden=false;clearTimeout(messageTimer);messageTimer=setTimeout(()=>{notice.hidden=true;},6500);}
function showConnection(state,label,message){document.body.dataset.connection=state;status.textContent=label;overlay.hidden=state==='connected';if(message)connectionMessage.textContent=message;}
// Imported/custom guests have no reliable OS label. Store an explicit choice per VM.
const displayKey='titan.vm.console.display.v1:'+vm;
let displayMode='fixed';try{if(window.localStorage?.getItem(displayKey)==='graphical')displayMode='graphical';}catch{}
function settleLayout(){
 clearTimeout(layoutTimer);const client=rfb;if(!client||closed||!connected)return;
 // Suppress guest resize requests while the window settles, then remeasure once.
 client.resizeSession=false;
 layoutTimer=setTimeout(()=>{layoutTimer=null;if(closed||client!==rfb||!connected)return;client.scaleViewport=client.scaleViewport!==false;client.resizeSession=displayMode==='graphical';},350);
}
function setDisplayMode(value){displayMode=value==='graphical'?'graphical':'fixed';try{window.localStorage?.setItem(displayKey,displayMode);}catch{}settleLayout();feedback(displayMode==='graphical'?'Gastauflösung folgt dem Fenster, sofern der Gast dies unterstützt.':'Feste Gastauflösung für Textkonsolen, Alpine und Android.');}
const controls=window.TitanVMConsole?.mount({doc:document,win:window,client:()=>rfb,connected:()=>connected,status:feedback,displayMode:()=>displayMode,setDisplayMode});
function connection(value){connected=value;controls?.update();}
const embeddedConsole=new URLSearchParams(location.search).get('embedded')==='1';
if(embeddedConsole)document.body.dataset.embedded='true';
// Embedded consoles receive live preferences from their parent. Separate tabs
// read the signed-in user's saved appearance without writing account settings.
let accountThemeAbort=null;
if(!embeddedConsole&&window.TitanTheme){
 accountThemeAbort=window.AbortController?new window.AbortController():null;
 fetch('/api/launcher-layout',{credentials:'same-origin',cache:'no-store',...(accountThemeAbort?{signal:accountThemeAbort.signal}:{})})
  .then(async response=>{if(!response.ok)return;const layout=await response.json();if(!closed&&layout?.desktop&&typeof layout.desktop==='object')window.TitanTheme.set(layout.desktop);})
  .catch(()=>{});
}
function wake(){if(rfb){rfb.sendKey(0xffe1,'ShiftLeft',true);rfb.sendKey(0xffe1,'ShiftLeft',false);rfb.focus();}}
function later(message){if(closed)return;showConnection('error','Getrennt',message);clearTimeout(timer);timer=setTimeout(()=>connect(),Math.min(15000,1500*2**Math.min(attempt++,3)));}
async function connect(){
 const mine=++generation;connection(false);clearTimeout(timer);clearTimeout(layoutTimer);if(rfb){const old=rfb;rfb=null;old.disconnect();}retry.disabled=true;showConnection('connecting','Verbinden …','Verbindung zur virtuellen Maschine wird hergestellt.');
 try{
  if(!vm){showConnection('empty','Keine VM ausgewählt','Wähle eine virtuelle Maschine aus, um ihre Konsole zu öffnen.');retry.textContent='VM auswählen';return;}
  const response=await fetch('/api/vm-console?vm='+encodeURIComponent(vm),{cache:'no-store'});const result=await response.json();if(closed||mine!==generation)return;
  if(!response.ok){if(response.status===401||response.status===403){showConnection('error','Anmeldung erforderlich','Bitte in Titan als Administrator anmelden.');return;}throw Error(result.error||'VM-Konsole noch nicht bereit.');}
  const {default:RFB}=await import('/novnc/core/rfb.js');if(closed||mine!==generation)return;
  const client=new RFB(screen,`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/vnc?vm=${encodeURIComponent(vm)}`);rfb=client;
  client.background='#000';client.scaleViewport=true;client.resizeSession=false;client.focusOnClick=true;
  client.addEventListener('connect',()=>{if(client!==rfb)return;attempt=0;connection(true);showConnection('connected','Verbunden');wake();settleLayout();});
  client.addEventListener('disconnect',()=>{if(client!==rfb||closed)return;rfb=null;clearTimeout(layoutTimer);connection(false);later('Verbindung getrennt · erneuter Verbindungsaufbau …');});
  client.addEventListener('clipboard',event=>{if(client===rfb)controls?.clipboard(event.detail?.text);});
  client.addEventListener('credentialsrequired',()=>{if(client!==rfb)return;generation++;rfb=null;clearTimeout(layoutTimer);connection(false);client.disconnect();clearTimeout(timer);showConnection('error','Zugangsdaten erforderlich','VNC verlangt Zugangsdaten. VM-Konfiguration prüfen.');});
 }catch(error){if(closed||mine!==generation)return;later((error.message||'Konsole nicht erreichbar.')+' · Verbindung wird erneut versucht.');}
 finally{if(mine===generation)retry.disabled=false;}
}
const layoutObserver=window.ResizeObserver?new window.ResizeObserver(settleLayout):null;layoutObserver?.observe(screen);
window.addEventListener('resize',settleLayout);document.addEventListener('fullscreenchange',settleLayout);
retry.addEventListener('click',()=>{if(!vm){if(embeddedConsole)window.parent.postMessage({type:'titan-console-back'},location.origin);else location.href='/#vms';return;}attempt=0;connect();});
window.addEventListener('pagehide',()=>{closed=true;generation++;accountThemeAbort?.abort();clearTimeout(timer);clearTimeout(messageTimer);clearTimeout(layoutTimer);layoutObserver?.disconnect();window.removeEventListener('resize',settleLayout);document.removeEventListener('fullscreenchange',settleLayout);controls?.destroy();rfb?.disconnect();});
connect();
