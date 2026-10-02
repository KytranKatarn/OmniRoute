// node tests/js/aqhi_bands_smoke.js — evaluates the AQHI stops/band helper straight out of weather.html
// and checks every published band boundary against the SAME ramp the map uses.
const fs=require('fs'),path=require('path');
const html=fs.readFileSync(path.resolve(__dirname,'../../consumer/templates/weather.html'),'utf8');
const m=html.match(/var AQHI_STOPS[\s\S]*?function aqhiBandName\(v\) \{[\s\S]*?\n  \}\n/);
if(!m){console.error('AQHI block not found');process.exit(1)}
const ramp=(stops,v)=>{for(const s of stops) if(v<=s[0]) return s[1]; return stops[stops.length-1][1]};
const f=new Function(m[0].replace(/\\u([0-9a-f]{4})/gi,(a,h)=>String.fromCharCode(parseInt(h,16)))+';return {AQHI_STOPS,aqhiBandName}');
const {AQHI_STOPS,aqhiBandName}=f();
const want={1:'Low',2:'Low',3:'Low',3.4:'Low',3.6:'Moderate',4:'Moderate',5:'Moderate',6:'Moderate',6.6:'High',7:'High',8:'High',10:'High',10.4:'High',10.6:'Very high',11:'Very high','3.40':'Low'};
let bad=0;
for(const [v,b] of Object.entries(want)){const got=aqhiBandName(v);if(got!==b){bad++;console.log('FAIL',v,'->',got,'want',b)}}
const col=v=>ramp(AQHI_STOPS,v);
if(col(3)===col(5)||col(5)===col(8)||col(8)===col(11)||col(3)!==AQHI_STOPS[0][1]) {bad++;console.log('FAIL colours do not follow bands')}
console.log(bad?'FAILED':'ok: all '+Object.keys(want).length+' boundary checks pass');process.exit(bad?1:0);
