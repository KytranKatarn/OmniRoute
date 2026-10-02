// Smoke test (no jsdom needed): node tests/js/map_labels_smoke.js — draws Canada with fake DOM, prints on-map labels + outline attrs.
const fs=require('fs'),vm=require('vm'),path=require('path');
const S=require('path').resolve(__dirname,'../../consumer/static')+'/';
class El{constructor(t){this.tag=t;this.attrs={};this.children=[];this.style={};this.listeners={};this._t='';this.clientWidth=1000;this.clientHeight=352;
 this.classList={add:()=>{},remove:()=>{},toggle:()=>{}}}
 setAttribute(k,v){this.attrs[k]=String(v)} getAttribute(k){return this.attrs[k]}
 removeAttribute(k){delete this.attrs[k]} appendChild(c){this.children.push(c);return c}
 addEventListener(){} set textContent(v){this._t=v; if(v==='')this.children=[]} get textContent(){return this._t}
 querySelector(){return null} get firstChild(){return this.children[0]||null} removeChild(){}
}
const host=new El('div');
global.window=global; global.addEventListener=()=>{};
global.document={createElementNS:(n,t)=>new El(t),createElement:t=>new El(t),getElementById:id=>id==='m'?host:null};
global.fetch=u=>Promise.resolve({ok:true,json:()=>Promise.resolve(JSON.parse(fs.readFileSync(S+u.replace(/^\/static\//,''),'utf8')))});
for(const f of ['vendor/d3-array.min.js','vendor/internmap.min.js','vendor/d3-geo.min.js','js/wtf-map.js'])vm.runInThisContext(fs.readFileSync(S+f,'utf8'),{filename:f});
const counts={ON:9000,QC:4000,BC:2500,AB:2000,NS:300,PE:5};
const m=WTFMap.create({el:'m',layers:[{id:'v',outline:true,fillOpacity:.4,
  label:pc=>counts[pc]?counts[pc].toLocaleString():null,
  metric:pc=>counts[pc]?{col:'#38bdf8'}:null,tooltip:pc=>pc,ramp:[[1,'#38bdf8','x']]}],active:'v'});
setTimeout(()=>{
 const svg=host.children[0]; const labs=svg.children.find(c=>c.attrs.class==='wtf-map-labels');
 const provs=svg.children.find(c=>c.attrs.class==='wtf-map-provinces');
 const texts=labs.children.map(t=>t._t);
 console.log('provinces drawn:',provs.children.length,'| label texts:',JSON.stringify(texts));
 const on=provs.children.find(p=>p.attrs['data-code']==='ON'), nu=provs.children.find(p=>p.attrs['data-code']==='NU');
 console.log('ON stroke',on.attrs.stroke,on.attrs['stroke-width'],'fill-op',on.attrs['fill-opacity'],'| NU(no data) stroke',nu.attrs.stroke,'dash',nu.attrs['stroke-dasharray']);
},800);
