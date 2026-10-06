// Console setup and recovery are automatic; guest shortcuts stay optional.
const vm = new URLSearchParams(location.search).get('vm');
const screen = document.querySelector('#screen');
const status = document.querySelector('#console-status');
const retry = document.querySelector('#reconnect');
let rfb=null,timer=null,closed=false,attempt=0,generation=0;
if(new URLSearchParams(location.search).get('embedded')==='1')document.querySelector('.topbar a')?.remove();
function wake(){if(rfb){rfb.sendKey(0xffe1,'ShiftLeft',true);rfb.sendKey(0xffe1,'ShiftLeft',false);rfb.focus();}}
function later(message){if(closed)return;status.textContent=message;clearTimeout(timer);timer=setTimeout(()=>connect(),Math.min(15000,1500*2**Math.min(attempt++,3)));}
async function connect(){
 const mine=++generation;clearTimeout(timer);if(rfb){const old=rfb;rfb=null;old.disconnect();}retry.disabled=true;status.textContent='Konsole wird verbunden …';
 try{
  if(!vm)throw Error('Keine VM ausgewählt.');
  const response=await fetch('/api/vm-console?vm='+encodeURIComponent(vm),{cache:'no-store'});const result=await response.json();
  if(!response.ok){if(response.status===401||response.status===403){status.textContent='Bitte in Titan als Administrator anmelden.';return;}throw Error(result.error||'VM-Konsole noch nicht bereit.');}
  const {default:RFB}=await import('/novnc/core/rfb.js');if(closed||mine!==generation)return;
  const client=new RFB(screen,`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/vnc?vm=${encodeURIComponent(vm)}`);rfb=client;
  client.scaleViewport=true;client.resizeSession=true;client.focusOnClick=true;
  client.addEventListener('connect',()=>{if(client!==rfb)return;attempt=0;status.textContent='Verbunden';wake();});
  client.addEventListener('disconnect',()=>{if(client!==rfb||closed)return;rfb=null;later('Verbindung getrennt · erneuter Verbindungsaufbau …');});
  client.addEventListener('credentialsrequired',()=>{if(client!==rfb)return;generation++;rfb=null;client.disconnect();clearTimeout(timer);status.textContent='VNC verlangt Zugangsdaten. VM-Konfiguration prüfen.';});
 }catch(error){if(closed||mine!==generation)return;later((error.message||'Konsole nicht erreichbar.')+' · Verbindung wird erneut versucht.');}
 finally{if(mine===generation)retry.disabled=false;}
}
retry.addEventListener('click',()=>{attempt=0;connect();});
document.querySelector('#wake-screen').addEventListener('click',wake);
document.querySelector('#ctrl-alt-del').addEventListener('click',()=>rfb?.sendCtrlAltDel());
window.addEventListener('pagehide',()=>{closed=true;generation++;clearTimeout(timer);rfb?.disconnect();});
connect();
