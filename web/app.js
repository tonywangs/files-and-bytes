'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
let snapshot, plan, files = [], busy = false;
const ruleIds = ['find','replace','prefix','suffix','preserve_extension','number','start','width'];
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function invalidate() { plan = null; $('apply').disabled = true; }
async function api(path, body = {}) {
  const response = await fetch('/api/' + path, {method:'POST', headers:{'Content-Type':'application/json','X-Desk-Token':token}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}
function renderRows(rows) {
  $('rows').replaceChildren();
  rows.forEach((row, i) => {
    const tr = document.createElement('tr'), td = document.createElement('td'), target = document.createElement('td'), input = document.createElement('input');
    td.textContent = row.source; input.value = row.dest ?? row.source;
    input.setAttribute('aria-label', 'Proposed name for ' + row.source); input.dataset.index = i;
    input.addEventListener('input', () => {invalidate(); message('Edited preview. Validate before applying.');});
    target.append(input); tr.append(td,target); $('rows').append(tr);
  });
  $('validate').disabled = !rows.length;
}
async function refresh(note) {
  invalidate();
  const data = await api('state'); snapshot = data.snapshot; files = data.files;
  $('folder').textContent = data.folder; $('count').textContent = `${files.length} regular files · ${data.skipped.length} excluded items`;
  renderRows(files); $('history').replaceChildren();
  if (!data.journals.length) $('history').textContent = 'No operations yet. Your first applied plan will appear here.';
  data.journals.forEach(j => {
    const item = document.createElement('div'); item.className = 'operation';
    const label = document.createElement('span'); label.textContent = `${j.status.toUpperCase()} · ${j.rows.length} files · ${j.id.slice(0,8)}`; item.append(label);
    const details = document.createElement('details'), summary = document.createElement('summary'), list = document.createElement('ul');
    summary.textContent = 'View recorded mapping'; details.append(summary, list);
    j.rows.forEach(r => {const li = document.createElement('li'); li.textContent = `${r.source} → ${r.dest}`; list.append(li);}); item.append(details);
    if(j.status !== 'undone') {
      const button = document.createElement('button'); button.textContent = j.status === 'applied' ? 'Undo operation' : 'Recover original names'; button.className = 'secondary';
      button.addEventListener('click', () => run(async () => { await api('undo', {id:j.id}); await refresh('Original names restored. Contents verified.'); })); item.append(button);
    }
    $('history').append(item);
  });
  const ul = $('skipped').querySelector('ul'); ul.replaceChildren();
  data.skipped.forEach(s => {const li = document.createElement('li'); li.textContent = `${s.name}: ${s.reason}`; ul.append(li);});
  message(note || 'Ready. Generate a preview or edit the proposed names.');
}
async function run(action) {
  if(busy) return; busy = true;
  // Freeze the entire form during validation/application so the displayed plan cannot drift.
  const controls = [...document.querySelectorAll('button,input')];
  const prior = new Map(controls.map(el=>[el,el.disabled])); controls.forEach(el=>el.disabled=true);
  try { await action(); } catch(error) {invalidate(); message(error.message + ' Refresh the folder to inspect the journal if a move was interrupted.', true);}
  finally {
    busy = false;
    controls.forEach(el=>{if(el.isConnected)el.disabled=prior.get(el);});
    $('apply').disabled = !plan;
    $('validate').disabled = !files.length;
  }
}
ruleIds.forEach(id => $(id).addEventListener('input', () => {invalidate(); message('Rules changed. Generate a new preview to use them.');}));
async function preview(edits) {
  const rules = Object.fromEntries(ruleIds.map(id => [id, $(id).type==='checkbox' ? $(id).checked : $(id).value]));
  invalidate();
  const data = await api('preview', {snapshot, rules, ...(edits ? {edits} : {})});
  renderRows(data.rows); plan = data.plan;
  const changes = data.rows.filter(r=>r.source!==r.dest).length;
  if(!changes) plan = null;
  message(data.errors.length ? data.errors.join('\n') : `${changes} filename changes validated. Inspect the names, then apply explicitly.`, !!data.errors.length);
}
$('generate').onclick = () => run(() => preview());
$('validate').onclick = () => run(() => preview([...$('rows').querySelectorAll('input')].map(el=>el.value)));
$('apply').onclick = () => run(async () => {const id=plan; invalidate(); await api('apply', {plan:id}); await refresh('Renamed successfully. The durable journal is ready for undo.');});
$('refresh').onclick = () => run(() => refresh());
run(() => refresh());
