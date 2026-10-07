"use strict";
// Small deterministic DOM/event fixture for pointer and focus behavior. No browser
// APIs or timers escape into the host beyond the module's cleared polling timer.
const camel=s=>s.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
const unescape=s=>s.replace(/&quot;/g,'"').replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>');
class Element {
 constructor(doc,tag='div'){this.ownerDocument=doc;this.tagName=tag.toUpperCase();this.children=[];this.parentElement=null;this.dataset={};this.attrs={};this.style={};this.events=new Map();this.hidden=false;this.open=false;this.disabled=false;this.clientWidth=900;this.clientHeight=650;this.scrollLeft=this.scrollTop=0;this._text='';this.classList={contains:k=>this.className.split(/\s+/).includes(k),add:k=>{if(!this.classList.contains(k))this.className+=' '+k;},remove:k=>{this.className=this.className.split(/\s+/).filter(v=>v!==k).join(' ');},toggle:(k,on)=>{if(on??!this.classList.contains(k))this.classList.add(k);else this.classList.remove(k);}};}
 get className(){return this.attrs.class||'';} set className(v){this.attrs.class=v;}
 setAttribute(k,v){this.attrs[k]=String(v);if(k.startsWith('data-'))this.dataset[camel(k.slice(5))]=String(v);if(k==='hidden')this.hidden=true;if(k==='disabled')this.disabled=true;}
 getAttribute(k){return this.attrs[k]??null;} hasAttribute(k){return Object.hasOwn(this.attrs,k);} removeAttribute(k){delete this.attrs[k];}
 get isConnected(){return this===this.ownerDocument||!!this.parentElement?.isConnected;}
 append(...nodes){for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
 remove(){if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}}
 contains(node){return node===this||this.children.some(child=>child.contains(node));}
 matches(selector){return selector.split(',').some(part=>{let s=part.trim();if(s.endsWith(':not(:disabled)')){if(this.disabled)return false;s=s.replace(':not(:disabled)','');}if(s===':disabled')return this.disabled;const tag=s.match(/^[a-z]+/i)?.[0];if(tag&&this.tagName!==tag.toUpperCase())return false;for(const [,name,value] of s.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)){if(!this.hasAttribute(name)||value!==undefined&&this.getAttribute(name)!==value)return false;}for(const [,name]of s.matchAll(/\.([\w-]+)/g))if(!this.classList.contains(name))return false;for(const [,id]of s.matchAll(/#([\w-]+)/g))if(this.attrs.id!==id)return false;return true;});}
 closest(selector){for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
 querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 set innerHTML(html){if(this.contains(this.ownerDocument?.activeElement))this.ownerDocument.activeElement=this.ownerDocument.body;for(const child of this.children)child.parentElement=null;this.children=[];this._html=html;const stack=[this],voids=new Set(['input','img','br','hr']);for(const token of html.matchAll(/<\/?[^>]+>|[^<]+/g)){const text=token[0];if(text.startsWith('</')){if(stack.length>1)stack.pop();continue;}if(text.startsWith('<')){const tag=text.match(/^<([a-z][\w-]*)/i)?.[1];if(!tag)continue;const node=new Element(this.ownerDocument,tag);for(const match of text.slice(tag.length+1,-1).matchAll(/([\w-]+)(?:="([^"]*)")?/g))node.setAttribute(match[1],unescape(match[2]??''));stack.at(-1).append(node);if(!voids.has(tag)&&!text.endsWith('/>'))stack.push(node);}else stack.at(-1)._text+=unescape(text);}}
 get innerHTML(){return this._html||'';} get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}set textContent(value){this._text=value;this.children=[];}
 focus(){this.ownerDocument.activeElement=this;}
 addEventListener(type,fn,capture=false){const all=this.events.get(type)||[];all.push({fn,capture:!!capture});this.events.set(type,all);}
 removeEventListener(type,fn,capture=false){this.events.set(type,(this.events.get(type)||[]).filter(v=>v.fn!==fn||v.capture!==!!capture));}
 getBoundingClientRect(){if(this._rect)return this._rect;const width=this.classList.contains('desktop-widget')?272:104,height=this.classList.contains('desktop-widget')?260:104,left=parseFloat(this.style.left)||0,top=parseFloat(this.style.top)||0;return {left,top,width,height,right:left+width,bottom:top+height};}
 get offsetHeight(){return this.classList.contains('desktop-quick-actions')?350:260;}
 showModal(){this.open=true;this.querySelector('input,button')?.focus();}close(){this.open=false;this.ownerDocument.dispatch(this,'close');}
 setPointerCapture(id){this.pointer=id;}hasPointerCapture(id){return this.pointer===id;}releasePointerCapture(){delete this.pointer;}
}
function fixture(){
 const doc=new Element(null,'document');doc.ownerDocument=doc;doc.body=new Element(doc,'body');doc.append(doc.body);doc.activeElement=doc.body;doc.createElement=tag=>new Element(doc,tag);doc.hidden=false;
 const win=new Element(doc,'window');doc.defaultView=win;win.innerWidth=1000;win.innerHeight=800;win.opened=[];win.open=(...args)=>win.opened.push(args);win.ResizeObserver=class{observe(){}disconnect(){}};
 let now=10000,next=0;const timers=new Map();win.setTimeout=(fn,delay)=>{const id=++next;timers.set(id,{fn,at:now+delay});return id;};win.clearTimeout=id=>timers.delete(id);win.setInterval=()=>++next;win.clearInterval=()=>{};
 const advance=ms=>{now+=ms;for(const [id,value]of [...timers])if(value.at<=now){timers.delete(id);value.fn();}};
 doc.dispatch=(target,type,data={})=>{const event={target,type,button:0,isPrimary:true,pointerId:1,pointerType:'mouse',clientX:30,clientY:90,detail:1,defaultPrevented:false,stopped:false,preventDefault(){this.defaultPrevented=true;},stopImmediatePropagation(){this.stopped=true;},...data};const path=[];for(let node=target;node;node=node.parentElement)path.push(node);if(!path.includes(doc))path.push(doc);path.push(win);for(const capture of [true,false])for(const node of capture?[...path].reverse():path){event.currentTarget=node;for(const {fn,capture:cap}of node.events.get(type)||[])if(cap===capture){fn(event);if(event.stopped)return event;}}return event;};
 doc.elementFromPoint=()=>null;const surface=new Element(doc);surface.setAttribute('id','desktop-surface');surface._rect={left:0,top:60,width:900,height:650,right:900,bottom:710};doc.body.append(surface);return {doc,win,surface,advance,now:()=>now,Element};
}
module.exports={fixture,Element};
