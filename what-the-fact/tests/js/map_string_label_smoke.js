// Regression (2026-10-02): a layer whose `label` is a DISPLAY STRING must not be called.
// weather.html:1031-1037 passes label:"Fire activity"; wtf-map.drawLabels() wants an
// opt-in label(code) callback. Truthiness guard let the string through ->
// "TypeError: def.label is not a function" out of restyle/onResize on /weather.
// Run: node tests/js/map_string_label_smoke.js
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

// --- regression: layer.label as a DISPLAY STRING (the weather.html shape) ---
const counts={ON:9000,QC:4000,BC:2500,AB:2000,NS:300,PE:5};
process.on('uncaughtException',e=>{ console.log('RESULT: THREW ->',e.message); process.exit(1); });
const w=WTFMap.create({el:'m',layers:[{id:'wx',
  label:'Fire activity',            // <-- string, exactly as weather.html:1031
  metric:pc=>counts[pc]?{col:'#f97316'}:null,
  tooltip:pc=>pc,ramp:[[1,'#f97316','x']]}],active:'wx'});
setTimeout(()=>{ w.refresh(); },500);
setTimeout(()=>{ console.log('RESULT: no throw - string label skipped, map still drew'); },900);
