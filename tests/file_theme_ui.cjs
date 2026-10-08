'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const read=name=>fs.readFileSync('titan/web/'+name,'utf8');
function rules(name){return [...read(name).replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([,selector,body])=>({selector:selector.trim(),properties:Object.fromEntries(body.split(';').filter(Boolean).map(value=>{const colon=value.indexOf(':');return [value.slice(0,colon).trim(),value.slice(colon+1).trim()];}))}));}
const colorProperty=/^(?:color|background(?:-color)?|border(?:-[\w]+)?|outline(?:-[\w]+)?|box-shadow|accent-color|caret-color|fill|stroke)$/;
const fileSelector=/\.(?:fb-|file-|preview-frame|location-selected)/;
const components=['file_browser.css','file_types.css'];
const shared=['style.css','nas_desktop.css','desktop_shell.css','nas_polish.css','application_design.css','application_shell.css','compact_ui.css','app_window_layout.css'];
for(const file of [...components,...shared])for(const rule of rules(file)){
 if(!components.includes(file)&&!fileSelector.test(rule.selector))continue;
 for(const [property,value]of Object.entries(rule.properties))if(colorProperty.test(property)){
  assert.doesNotMatch(value,/#(?:[a-f\d]{3,8})\b|\b(?:white|black)\b|rgba?\(\s*\d/i,`${file}: ${rule.selector} ${property} must use the active palette`);
 }
}
function value(file,selector,property){const matches=rules(file).filter(rule=>rule.selector===selector&&Object.hasOwn(rule.properties,property));assert(matches.length,`${file}: missing ${selector} ${property}`);return matches.at(-1).properties[property];}
for(const [file,selector,property,expected]of [
 ['file_browser.css','#shell .fb-browser.panel','background','var(--bg)'],
 ['file_browser.css','.fb-table thead th','background','var(--panel-soft)'],
 ['file_browser.css','.fb-table thead th','color','var(--muted)'],
 ['file_browser.css','.fb-place','color','var(--text)'],
 ['file_browser.css','.fb-place.active','background','var(--selected)'],
 ['file_browser.css','.fb-place.active','color','var(--selected-text)'],
 ['file_browser.css','.fb-search-advanced','color','var(--muted)'],
 ['file_browser.css','.fb-name-button','color','var(--text)'],
 ['file_browser.css','.fb-inline-preview pre','color','var(--text)'],
 ['file_browser.css','.fb-entry:hover','background','var(--hover)'],
 ['file_browser.css','.fb-entry.selected','background','var(--selected)'],
 ['file_browser.css','.fb-entry:focus-visible','outline','2px solid var(--accent)'],
 ['file_browser.css','.fb-system-note','background','var(--warning-bg)'],
 ['file_browser.css','#shell .fb-toolbar','background','var(--panel-soft)'],
 ['file_browser.css','.fb-selection','background','var(--panel-soft)'],
 ['nas_polish.css','.fb-search-advanced summary','color','var(--muted)'],
 ['nas_polish.css','#shell .fb-toolbar','background','var(--panel-soft)'],
 ['nas_polish.css','#shell .fb-places','background','var(--panel-soft)'],
 ['desktop_shell.css','.fb-table thead th','background','var(--panel-soft)'],
 ['desktop_shell.css','.fb-system-note','background','var(--warning-bg)'],
 ['nas_desktop.css','.file-editor-workspace .file-editor','background','var(--panel)'],
 ['nas_desktop.css','.file-editor-workspace .file-editor','color','var(--text)'],
 ['nas_desktop.css','.file-editor-workspace .file-editor','caret-color','var(--accent)'],
 ['file_types.css','.file-type-word','color','var(--info)'],
 ['file_types.css','.file-type-sheet','color','var(--success)'],
 ['file_types.css','.file-type-pdf','color','var(--danger)'],
])assert.equal(value(file,selector,property),expected,`${file}: ${selector} ${property}`);
for(const rule of rules('desktop_theme.css'))assert.doesNotMatch(rule.selector,/\.(?:fb-|file-)/,'File components own their semantic states without late theme selector overrides');

const theme=rules('desktop_theme.css');
const luminance=hex=>{let value=hex.replace('#','');if(value.length===3)value=[...value].map(v=>v+v).join('');const rgb=value.match(/.{2}/g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;};
for(const mode of ['light','dark']){
 const selectors=[':root',`html[data-color-theme=${mode}]`],palette=Object.assign({},...theme.filter(rule=>rule.selector.split(',').some(selector=>selectors.includes(selector.trim()))).map(rule=>rule.properties));
 const resolve=name=>{const entry=palette[name];assert(entry,`${mode} defines ${name}`);return entry.startsWith('var(')?resolve(entry.slice(4,-1)):entry;};
 for(const [foreground,background]of [['--muted','--panel-soft'],['--muted','--panel'],['--text','--panel'],['--selected-text','--selected'],['--warning','--warning-bg']]){
  const a=luminance(resolve(foreground)),b=luminance(resolve(background)),contrast=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);assert(contrast>=4.5,`${mode} ${foreground} on ${background}: ${contrast.toFixed(2)} must remain readable`);
 }
}
console.log('File themes: semantic list headers, sidebar/search, menus/previews/editor, selection/focus/warnings, mobile surfaces and readable light/dark palettes passed.');
