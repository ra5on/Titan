'use strict';
(function(root){
 const views=new Map();
 function mount(scope,page){
  if(!['storage','apps'].includes(page))return;
  const content=scope?.querySelector('.nas-window-content');if(!content||content.querySelector('[data-section-layout]'))return;
  const doc=content.ownerDocument,holder=page==='storage'?content.querySelector('.storage-workspace'):content;
  if(!holder)return;
  const panels=page==='storage'?[...holder.children]:[...holder.querySelectorAll(':scope > .app-installed-section,:scope > .app-discover-section')];
  if(!panels.length)return;
  const shell=doc.createElement('section');shell.className='sl-manager';shell.dataset.sectionLayout=page;
  const nav=doc.createElement('nav');nav.className='sl-nav';nav.setAttribute('aria-label',page==='storage'?'Speicherbereiche':'App-Ansichten');
  const main=doc.createElement('div');main.className='sl-content';
  const buttons=[];
  panels.forEach((panel,index)=>{
   const summary=panel.tagName==='DETAILS'?panel.querySelector('summary'):null;
   const label=page==='apps'?(index===0?'Installiert':'Alle Apps'):(summary?.textContent||panel.querySelector('h2')?.textContent||'Systemlaufwerk');
   const button=doc.createElement('button');button.type='button';button.textContent=label;button.dataset.sectionView=String(index);button.setAttribute('aria-controls',panel.id||'sl-panel-'+index);nav.append(button);buttons.push(button);
   if(!panel.id)panel.id='sl-panel-'+index;panel.setAttribute('role','region');panel.setAttribute('aria-label',label);
   if(summary){panel.open=true;summary.hidden=true;const title=doc.createElement('h2');title.textContent=label;panel.insertBefore(title,summary);}
   main.append(panel);
  });
  function select(index){panels.forEach((panel,i)=>{panel.hidden=i!==index;buttons[i].setAttribute('aria-current',i===index?'page':'false');});views.set(page,index);}
  buttons.forEach((button,index)=>button.addEventListener('click',()=>select(index)));
  shell.append(nav,main);
  if(page==='storage'){holder.replaceWith(shell);}else content.append(shell);
  const remembered=views.get(page);select(Number.isInteger(remembered)&&remembered<panels.length?remembered:page==='apps'?1:0);
 }
 const ui={mount};if(root)root.TitanSectionLayout=ui;
})(typeof window==='undefined'?null:window);
