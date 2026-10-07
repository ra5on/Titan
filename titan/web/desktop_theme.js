'use strict';
// Theme messages are confined to Titan's own application windows.
(function(root,factory){const ui=factory();if(typeof module==='object'&&module.exports)module.exports=ui;if(root){root.TitanTheme=ui.init(root);}})(typeof window==='undefined'?null:window,function(){
 function normalize(value={}){return {color_mode:['light','dark','system'].includes(value?.color_mode)?value.color_mode:'light',transparency:Number.isInteger(value?.transparency)&&value.transparency>=0&&value.transparency<=100?value.transparency:40};}
 function init(win){
  const doc=win.document,media=win.matchMedia?.('(prefers-color-scheme: dark)'),embedded=win.parent!==win&&new URLSearchParams(win.location.search).get('desktop-app')==='1';let prefs=normalize();
  function frames(){return [...doc.querySelectorAll('iframe.desktop-app-frame')].map(node=>node.contentWindow).filter(Boolean);}
  function send(target){target.postMessage({type:'titan-theme',preferences:{...prefs}},win.location.origin);}
  function apply(){const theme=prefs.color_mode==='system'?(media?.matches?'dark':'light'):prefs.color_mode;doc.documentElement.dataset.colorTheme=theme;doc.documentElement.dataset.colorMode=prefs.color_mode;doc.documentElement.style.setProperty('--desktop-glass-opacity',String(1-prefs.transparency/100));doc.documentElement.style.setProperty('color-scheme',theme);const meta=doc.querySelector('meta[name="color-scheme"]');if(meta)meta.content=theme;}
  function set(value){prefs=normalize(value);apply();if(!embedded)frames().forEach(send);return {...prefs};}
  function message(event){if(event.origin!==win.location.origin)return;if(embedded){if(event.source===win.parent&&event.data?.type==='titan-theme'&&event.data.preferences&&typeof event.data.preferences==='object')set(event.data.preferences);}else if(event.data?.type==='titan-theme-ready'&&frames().includes(event.source))send(event.source);}
  function systemChanged(){if(prefs.color_mode==='system'){apply();if(!embedded)frames().forEach(send);}}
  win.addEventListener('message',message);media?.addEventListener?.('change',systemChanged);apply();
  if(embedded)win.parent.postMessage({type:'titan-theme-ready'},win.location.origin);
  return {set,reset:()=>set({}),get:()=>({...prefs}),destroy(){win.removeEventListener('message',message);media?.removeEventListener?.('change',systemChanged);}};
 }
 return {normalize,init};
});
