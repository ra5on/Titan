'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const read=name=>fs.readFileSync('titan/web/'+name,'utf8');
function rules(name){return [...read(name).replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([,selector,body])=>({selector:selector.trim(),properties:Object.fromEntries(body.split(';').filter(Boolean).map(value=>{const colon=value.indexOf(':');return [value.slice(0,colon).trim(),value.slice(colon+1).trim()];}))}));}
function value(name,selector,property){const matches=rules(name).filter(rule=>rule.selector===selector&&Object.hasOwn(rule.properties,property));assert(matches.length,`${name} defines ${selector} ${property}`);return matches.at(-1).properties[property];}

// These complete components must work with either palette without a late
// selector blanket rescuing literal light surfaces or dark text descendants.
const components=['settings_center.css','identity_security.css','user_manager.css','docker_workbench.css','storage_backup.css','package_center.css','application_shell.css','manager_views.css','vm_manager.css'];
const colorProperty=/^(?:color|background(?:-color)?|border(?:-[\w]+)?|outline(?:-[\w]+)?|box-shadow|accent-color)$/;
for(const file of components)for(const rule of rules(file))for(const [property,entry]of Object.entries(rule.properties))if(colorProperty.test(property)){
 // A VM console has its own always-dark canvas; app chrome still follows the palette.
 if(file==='vm_manager.css'&&rule.selector.endsWith('.vm-console-frame')&&property==='background'){assert.equal(entry,'var(--vm-console-bg,#111827)');continue;}
 assert.doesNotMatch(entry,/#(?:[a-f\d]{3,8})\b|\b(?:white|black)\b/i,`${file} ${rule.selector} ${property} must follow the palette`);
}
for(const rule of rules('responsive.css').filter(rule=>/\.(?:engine-|app-live-grid|device-picker|device-option)/.test(rule.selector)))for(const [property,entry]of Object.entries(rule.properties))if(colorProperty.test(property))assert.doesNotMatch(entry,/#(?:[a-f\d]{3,8})\b|\b(?:white|black)\b/i,`Responsive Docker/device styling ${rule.selector} ${property} must follow the palette`);
for(const file of ['style.css','nas_desktop.css','responsive.css','sidebar_layout.css'])for(const rule of rules(file).filter(rule=>/\.(?:vm-|cpu-option)|#shell\[data-page=vms\]/.test(rule.selector)))for(const [property,entry]of Object.entries(rule.properties))if(colorProperty.test(property))assert.doesNotMatch(entry,/#(?:[a-f\d]{3,8})\b|\b(?:white|black)\b/i,`Shared VM styling ${file} ${rule.selector} ${property} must follow the palette`);

for(const [file,selector,property,expected]of [
 ['application_design.css','.cp-window','background','var(--bg)'],
 ['application_design.css','.cp-content .sc-save-actions','background','transparent'],
 ['application_design.css','.cp-view-switch button[aria-pressed=true]','background','var(--selected)'],
 ['application_design.css','dialog:not(.desktop-menu-dialog)','background','var(--panel)'],
 ['application_shell.css','.nas-window-content','color','var(--text)'],
 ['application_shell.css','.nas-window-content .panel','background','var(--panel)'],
 ['application_shell.css','.nas-window-content .service-card','background','var(--panel)'],
 ['settings_center.css','.sc-search:focus-within','border-color','var(--focus)'],
 ['settings_center.css','.sc-category-icon','background','transparent'],
 ['settings_center.css','.update-stream-versions div','background','var(--panel-soft)'],
 ['identity_security.css','.security-check','background','var(--warning-bg)'],
 ['identity_security.css','.security-check.is-good','background','var(--success-bg)'],
 ['user_manager.css','.um-detail','background','var(--panel-soft)'],
 ['user_manager.css','.um-table tr.is-selected td','background','var(--selected)'],
 ['user_manager.css','.um-table tr:hover td','background','var(--hover)'],
 ['user_manager.css','.um-info dd','color','var(--text)'],
 ['docker_workbench.css','.engine-log','background','var(--panel-soft)'],
 ['docker_workbench.css','.engine-feedback.is-error','background','var(--danger-bg)'],
 ['docker_workbench.css','.network-table tr.is-selected','background','var(--selected)'],
 ['responsive.css','.app-live-grid strong','color','var(--text)'],
 ['responsive.css','.app-live-grid span','color','var(--muted)'],
 ['manager_views.css','.mv-filter-bar>select','background','var(--panel)'],
 ['manager_views.css','.mv-filter-bar>select','color','var(--text)'],
 ['manager_views.css','.mv-filter-bar>select','border','1px solid var(--line)'],
 ['manager_views.css','.mv-warning','background','var(--warning-bg)'],
 ['manager_views.css','.mv-warning','color','var(--warning)'],
 ['manager_views.css','.mv-status-dot','background','var(--success)'],
 ['manager_views.css','.mv-status-warning','background','var(--warning)'],
 ['manager_views.css','.mv-cpu-performance','background','var(--info-bg)'],
 ['manager_views.css','.mv-cpu-efficiency','background','var(--success-bg)'],
 ['responsive.css','.vm-live-grid small','color','var(--muted)'],
 ['responsive.css','.vm-sparkline','color','var(--accent)'],
 ['vm_manager.css','#shell[data-page=vms] .vm-list-row.is-selected','background','var(--selected)'],
 ['vm_manager.css','#shell[data-page=vms] .vm-row-live .vm-live-grid strong','color','var(--text)'],
 ['vm_manager.css','#shell[data-page=vms] .vm-live-unavailable','color','var(--warning)'],
 ['vm_manager.css','#shell[data-page=vms] .vm-operation-status','background','var(--info-bg)'],
 ['nas_desktop.css','.cpu-option:has(input:checked)','background','var(--selected)'],
 ['nas_desktop.css','.cpu-option:has(input:checked)','border-color','var(--accent)'],
 ['nas_desktop.css','.cpu-option-efficiency','border-left','3px solid var(--success)'],
 ['sidebar_layout.css','#shell[data-page=vms] .mv-manager[data-manager=vms][data-sidebar-layout] .mv-tabs>button[aria-selected=true]','color','var(--selected-text)'],
 ['storage_backup.css','.storage-navigation','background','var(--panel-soft)'],
 ['storage_backup.css','.storage-health-summary.warning','background','var(--warning-bg)'],
 ['apps_center.css','.ac-status','background','var(--panel-soft)'],
 ['apps_center.css','.ac-app-icon','background','var(--selected)'],
 ['compact_ui.css','.security-tabs button[aria-selected=true]','color','var(--selected-text)'],
 ['package_center.css','.package-summary','background','var(--panel-soft)'],
 ['package_center.css','.package-service.is-ready .package-service-dot','background','var(--success)'],
 ['web_access.css','.remote-access .remote-checks','background','var(--panel-soft)'],
 ['nas_desktop.css','.field label','color','var(--text)'],
 ['nas_desktop.css','.button.primary','color','var(--primary-text)'],
 ['nas_desktop.css','.button.primary','background','var(--primary-bg)'],
 ['nas_desktop.css','.meter span','background','var(--accent)'],
 ['nas_desktop.css','.meter.teal span','background','var(--success)'],
 ['nas_desktop.css','.legend span:before','background','var(--accent)'],
])assert.equal(value(file,selector,property),expected,`${file}: ${selector} ${property}`);
assert.match(value('apps_center.css','.ac-app-card','background'),/linear-gradient\(.*var\(--panel\).*var\(--panel-soft\)/,'Store glass surfaces keep the semantic light/dark palette');
assert.match(value('nas_desktop.css','dialog::backdrop','background'),/transparent/,'The modal backdrop remains translucent in both modes');
const actionSurfaces=rules('responsive.css').filter(rule=>rule.selector==='.form-actions'&&Object.hasOwn(rule.properties,'background'));
assert(actionSurfaces.length,'Responsive form action surfaces are explicitly defined');
for(const rule of actionSurfaces)assert.equal(rule.properties.background,'transparent','Responsive form actions never reintroduce a white strip');

const theme=rules('desktop_theme.css'),required=['--bg','--panel','--panel-soft','--text','--muted','--line','--accent','--focus','--focus-ring','--hover','--selected','--selected-text','--primary-bg','--primary-text','--success','--success-bg','--warning','--warning-bg','--danger','--danger-bg','--info','--info-bg'];
for(const rule of theme)assert.doesNotMatch(rule.selector,/\.(?:cp-|sc-|um-|engine-|network-|security-|catalog-|sl-|package-|mv-|vm-(?!console\b)|storage-(?:navigation|health|toolbar|volume|dataset|properties))/,'The desktop theme must not override semantic application component states');
for(const mode of ['light','dark']){
 const modeSelector=`html[data-color-theme=${mode}]`,palettes=theme.filter(rule=>rule.selector.split(',').some(selector=>[':root',modeSelector].includes(selector.trim())));
 const modePalette=palettes.find(rule=>rule.selector.split(',').some(selector=>selector.trim()===modeSelector));assert(modePalette,`${mode} palette exists`);
 const properties=Object.assign({},...palettes.map(rule=>rule.properties));
 for(const name of required){const source=['--hover','--selected','--selected-text','--focus-ring'].includes(name)?properties:modePalette.properties;assert(Object.hasOwn(source,name),`${mode} palette defines ${name} for every component state`);}
}
console.log('Component themes: semantic surfaces, text, selected/hover/focus, status feedback, transparent form actions and complete light/dark palette contracts passed.');
