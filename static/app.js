const $=s=>document.querySelector(s), codecs=['utf-8','utf-16-le','utf-16-be','windows-1252','iso-8859-1','cp1251', 'koi8-r'];
function valid(files){return Array.isArray(files)&&files.length<=32&&files.every(r=>r&&typeof r.name==='string'&&r.name.length<=1000&&/^[a-f0-9]{64}$/.test(r.hash)&&['',...codecs].includes(r.codec)&&typeof r.excluded==='boolean'&&Number.isInteger(r.size)&&r.size>=0&&r.size<=2097152)}
let rows=[]; try {const saved=JSON.parse(localStorage.getItem('desk')||'[]');if(valid(saved))rows=saved} catch {};
const status=s=>$('#status').textContent=s;
const metadata=()=>rows.map(({data,inspection,...r})=>r);
function persist(){localStorage.setItem('desk',JSON.stringify(metadata()))}
async function api(path,value){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});if(!r.ok)throw Error(await r.text());return r}
function download(name,blob){let a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function add(files){
 const used=new Set(); const rejected=[];
 for(const f of files){
  if(f.size>2097152){rejected.push(`Rejected ${f.name}: exceeds 2 MiB`);continue}
  const bytes=new Uint8Array(await f.arrayBuffer());const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
  let r=rows.find(r=>!r.data&&r.hash===hash&&r.name===f.name&&!used.has(r));
  const existing=!!r;
  if(!r){if(rows.length>=32){rejected.push(`Rejected ${f.name}: maximum 32 files`);continue}r={name:f.name,hash,codec:'',excluded:false,size:f.size};rows.push(r)}
  if(rows.reduce((s,x)=>s+(x.data?x.size:0),0)+f.size>8388608){rejected.push(`Rejected ${f.name}: batch exceeds 8 MiB`);if(!existing)rows=rows.filter(x=>x!==r);continue}
  used.add(r);let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));r.data=btoa(raw);r.inspection=await (await api('/inspect',r)).json();
 }
 persist();render();if(rejected.length)status(rejected.join('; '));return rejected;
}
function el(tag,text,parent){let e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e}
function render(){
 $('#desk').replaceChildren();
 rows.forEach((r,i)=>{
  const a=el('article',undefined,$('#desk'));el('h2',`${i+1}. ${r.name}`,a);el('small',`SHA-256 ${r.hash}`,a);
  el('p',r.data?'Original connected • '+r.size+' bytes':'Reconnect matching original bytes to inspect and export.',a);
  let l=el('label','Explicit interpretation: ',a),sel=el('select',undefined,l);el('option','Choose encoding',sel).value='';for(const c of codecs)el('option',c,sel).value=c;sel.value=r.codec;sel.onchange=()=>{r.codec=sel.value;persist()};
  let ex=el('label','Exclude from conversion ',a),cb=el('input',undefined,ex);cb.type='checkbox';cb.checked=r.excluded;cb.onchange=()=>{r.excluded=cb.checked;persist()};
  if(!r.inspection)return;
  const grid=el('div',undefined,a);grid.className='previews';
  for(const initial of [r.codec||'utf-8','iso-8859-1']){
   const box=el('section',undefined,grid),s=el('select',undefined,box);s.setAttribute('aria-label','Preview encoding');for(const c of codecs)el('option',c,s).value=c;s.value=initial;const p=el('pre',undefined,box);
   function show(){let v=r.inspection.previews[s.value];p.textContent=v.error?`DECODING ERROR at bytes ${v.start}–${v.end}: ${v.error}`:v.text+`\n\n[${v.characters} code points; ${v.literal_replacements} literal U+FFFD characters]`;p.className=v.error?'error':''}s.onchange=show;show();
  }
  const label=el('label','Inspect byte offset (decimal) ',a),offset=el('input',undefined,label);offset.type='number';offset.min=0;offset.max=r.size;offset.value=0;const hex=el('pre',r.inspection.hex,a);
  offset.onchange=async()=>{try{const v=await(await api('/inspect',{...r,inspection:undefined,offset:Number(offset.value)})).json();hex.textContent=v.hex}catch(e){status(e.message)}};
 });
}
$('#files').onchange=e=>add(e.target.files).catch(e=>status(e.message));
$('#demo').onclick=async()=>{try{const sources=await(await fetch('/demo/sources.json')).json();const rejected=await add(await Promise.all(sources.filter(r=>r.codec).map(async r=>new File([await(await fetch('/demo/'+r.name)).arrayBuffer()],r.name))));if(!rejected.length)status('Real Vim translations loaded. Upstream filenames and scriptencoding declarations identify Latin-1 and KOI8-R; select each explicitly.')}catch(e){status(e.message)}};
$('#save').onclick=()=>download('encoding-decisions.json',new Blob([JSON.stringify({version:1,files:metadata()},null,2)],{type:'application/json'}));
$('#project').onchange=async e=>{try{if(e.target.files[0].size>100000)throw Error('Project too large');const p=JSON.parse(await e.target.files[0].text());if(p.version!==1||!valid(p.files))throw Error('Invalid project');rows=p.files.map(({name,hash,codec,excluded,size})=>({name,hash,codec,excluded,size}));persist();render();status('Decisions restored. Reconnect files with matching names and SHA-256 hashes.')}catch(e){status(e.message)}};
$('#clear').onclick=()=>{rows=[];persist();render();status('Desk cleared')};
$('#export').onclick=async()=>{try{if(!rows.length)throw Error('Import files first');if(rows.some(r=>!r.excluded&&(!r.codec||!r.data)))throw Error('Every included file needs an explicit decision and matching original');const response=await api('/export',rows.map(({inspection,...r})=>r));download('utf8-export.zip',await response.blob());status('Export downloaded. Read manifest.json: failed or unsupported entries mean an incomplete batch.')}catch(e){status(e.message)}};
render();
