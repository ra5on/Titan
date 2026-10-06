'use strict';
(async function(){
 const status=document.getElementById('office-status'),session=new URLSearchParams(location.search).get('session');let editor;
 document.getElementById('office-close').addEventListener('click',()=>{editor?.destroyEditor?.();window.close();status.textContent='Dokument geschlossen. Du kannst diese Ansicht schließen.';});
 try{
  if(!session)throw Error('Dokument erneut aus dem Dateimanager öffnen.');
  const response=await fetch('/api/office/config?'+new URLSearchParams({session,mobile:matchMedia("(max-width:760px)").matches?"1":"0"}),{credentials:'same-origin'}),result=await response.json();
  if(!response.ok)throw Error(result.error||'Office-Verbindung ist nicht verfügbar.');
  const script=document.createElement('script');script.src=result.script;
  await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=()=>reject(Error('Euro-Office ist nicht erreichbar. Prüfe das Paket Nextcloud + Euro-Office.'));document.head.append(script);});
  result.config.events={onDocumentReady(){status.textContent='';},onError(event){status.textContent=event?.data?.errorDescription||'Office konnte das Dokument nicht öffnen.';},onRequestClose(){document.getElementById('office-close').click();}};
  editor=new DocsAPI.DocEditor('office-editor',result.config);
 }catch(error){status.textContent=error.message;}
})();
