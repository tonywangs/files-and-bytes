'use strict';
const $ = id => document.getElementById(id);
let token, packages = [], busy = false;
const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes = n => `${Number(n).toLocaleString()} B`;
const link = (kind,id,name,label) => `<a href="/download?${new URLSearchParams({kind,id,name})}">${escape(label || name)}</a>`;
function setBusy(value) {
  busy = value;
  document.querySelectorAll('button:not(#cancel), input, select').forEach(b => b.disabled = value || b.dataset.unsupported === 'true');
  $('cancel').hidden = !value;
}
async function getState() {
  const response = await fetch('/api/state');
  const s = await response.json();
  if (!response.ok) throw Error(s.error);
  token = s.token; packages = s.packages;
  $('source').textContent = s.source;
  $('engine').textContent = s.tool_version;
  if (!$('candidate').value) $('candidate').value = s.source;
  if (!$('files').children.length) $('files').innerHTML = s.files.map(f => `<label class="file"><input type="checkbox" value="${escape(f.name)}" ${f.supported ? 'checked' : 'disabled data-unsupported="true"'}>${f.name.endsWith('.svg') && s.source.endsWith('/data/twemoji') ? `<img src="/art/${encodeURIComponent(f.name)}" alt="">` : ''}<span>${escape(f.name)}<small>${bytes(f.bytes)}${f.supported ? '' : ' · '+escape(f.reason)}</small></span></label>`).join('');
  const selected = $('packages').value;
  $('packages').innerHTML = packages.length ? packages.map(p => `<option value="${p.id}">${escape(p.id.slice(0,20))} · ${p.files.length} files · ${escape(p.basis)}</option>`).join('') : '<option value="">Create or import a package</option>';
  if (packages.some(p => p.id === selected)) $('packages').value = selected;
  showPackage();
  return s;
}
function showPackage() {
  const p = packages.find(p => p.id === $('packages').value);
  if (!p) return;
  $('package-info').innerHTML = `<div class="stats"><div><strong>${p.files.length}</strong><span>accounted files</span></div><div><strong>${bytes(p.recovery_files.reduce((n,f)=>n+f.bytes,0))}</strong><span>actual recovery-file size, including metadata</span></div><div><strong>${p.settings.recovery_blocks}</strong><span>recovery blocks · ${p.settings.block_size} bytes each</span></div></div><p>Verification basis: <b>${escape(p.basis)}</b></p><div class="downloads">${p.recovery_files.map(f=>link('package',p.id,f.name,`${f.name} (${bytes(f.bytes)})`)).join('')}</div>`;
}
function showReport(r) {
  const success = r.status.startsWith('verified');
  $('report').innerHTML = `<span class="badge ${success?'':'bad'}">${escape(r.status)}</span><p>Basis: <b>${escape(r.basis)}</b>. Candidate inputs unchanged: <b>${r.inputs_unchanged}</b>. Recovery inputs unchanged: <b>${r.recovery_inputs_unchanged}</b>.</p><p>${r.output_directory ? `Verified copies: <code>${escape(r.output_directory)}</code>` : 'No verified restored copies have been published by this operation.'}</p><div class="table-wrap"><table><thead><tr><th>File</th><th>Before</th><th>After</th><th>SHA-256 of output</th></tr></thead><tbody>${r.output_files.map((f,i)=>`<tr><td>${escape(f.name)}</td><td>${escape(r.inspected_files[i].state)}</td><td>${escape(f.state)}</td><td><code>${escape(f.sha256 || 'Missing')}</code></td></tr>`).join('')}</tbody></table></div><div class="downloads">${link('report',r.id,'report.html','Export HTML report')}${link('report',r.id,'report.json','Export JSON report')}</div>${r.output_directory?`<h3>Save & reopen verified copies</h3><div class="downloads">${r.output_files.map(f=>link('restored',r.id,f.name)).join('')}</div>`:''}<details><summary>PAR2 engine output & exact command</summary><pre>${escape(r.engine.command.join(' '))}\nExit ${r.engine.exit_code}\n${escape(r.engine.output)}</pre></details>`;
}
async function poll() {
  while (true) {
    const job = await (await fetch('/api/job')).json();
    if (job.state === 'running') { await new Promise(resolve=>setTimeout(resolve,150)); continue; }
    setBusy(false);
    if (job.state === 'error') throw Error(job.error);
    const r = job.result;
    await getState();
    if (r && ['create','import'].includes(job.action)) { $('packages').value=r.id; showPackage(); }
    if (r && job.action === 'demo') {
      $('candidate').value=r.candidate; $('recovery').value=r.recovery_folder;
      $('mutation').textContent=JSON.stringify(r.mutation,null,2); $('mutation').hidden=false;
    }
    if (r && ['verify','repair'].includes(job.action)) showReport(r);
    $('status').textContent = `${job.action}: ${r?.status || 'ready'}`;
    return;
  }
}
async function act(action,args) {
  if (busy) return;
  try {
    setBusy(true); $('report').replaceChildren(); $('status').textContent=`${action} running…`;
    const response=await fetch(`/api/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-Desk-Token':token},body:JSON.stringify(args)});
    const result=await response.json(); if(!response.ok) throw Error(result.error);
    await poll();
  } catch(e) { setBusy(false); $('status').textContent=`Error: ${e.message}`; }
}
const inputs = () => ({package_id:$('packages').value,candidate:$('candidate').value,recovery_folder:$('recovery').value || null});
$('create').onclick=()=>act('create',{names:[...document.querySelectorAll('#files input:checked')].map(e=>e.value),redundancy:Number($('redundancy').value),block_size:Number($('block').value)});
$('import').onclick=()=>act('import',{directory:$('import-directory').value});
$('packages').onchange=()=>{showPackage();$('report').replaceChildren();$('recovery').value='';$('mutation').hidden=true;};
$('verify').onclick=()=>act('verify',inputs());
$('repair').onclick=()=>act('repair',inputs());
$('demo').onclick=()=>act('demo',{package_id:$('packages').value,scenario:$('scenario').value});
$('cancel').onclick=async()=>{const response=await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-Desk-Token':token},body:'{}'});const result=await response.json();$('status').textContent=result.message;};
getState().then(s=>{if(s.job.state==='running'){setBusy(true);poll().catch(e=>{$('status').textContent=e.message;setBusy(false);});}else $('status').textContent='Ready. Select files to create your first recovery package.';}).catch(e=>$('status').textContent=e.message);
