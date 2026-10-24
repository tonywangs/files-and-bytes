// Independent filesystem oracle: no imports from the rename implementation.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { request } from 'node:http';
import { mkdtemp, readdir, readFile, writeFile, copyFile, mkdir, rm, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const folder = await mkdtemp(join(tmpdir(), 'rename-browser-'));
const provenance = JSON.parse(await readFile(join(root,'demo/provenance.json')));
for (const item of provenance.files) {
  const bytes = await readFile(join(root,'demo/source',item.file));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), item.sha256);
  if(item.file.endsWith('.svg')) await copyFile(join(root,'demo/source',item.file),join(folder,item.file));
}
const original = Object.fromEntries(provenance.files.filter(f=>f.file.endsWith('.svg')).map(f=>[f.file,f.sha256]));
async function hashes() {
  const result={};
  for(const name of (await readdir(folder)).sort()) {
    if(name==='.rename-desk') continue;
    result[name] = createHash('sha256').update(await readFile(join(folder,name))).digest('hex');
  }
  return result;
}
let child, browser;
async function start(crash) {
  child = spawn('python3',['app.py','--folder',folder], {cwd:root,env:{...process.env, ...(crash ? {RENAME_DESK_TEST_CRASH_AFTER:String(crash)} : {})},stdio:['ignore','pipe','pipe']});
  let output='';
  return await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Server launch timeout: '+output)),10000);
    child.stdout.on('data',data=>{output+=data; const match=output.match(/Open (http:\/\/[^\s]+)/); if(match){clearTimeout(timer);resolve(match[1]);}});
    child.stderr.on('data',data=>{output+=data;});
    child.once('exit',code=>{clearTimeout(timer);reject(new Error('Server exited '+code+': '+output));});
  });
}
async function stop() {
  if(child && child.exitCode===null){child.kill('SIGTERM'); await new Promise(r=>child.once('exit',r));}
}
const observations=[];
try {
  const url = await start();
  browser = await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1360,height:1100}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.getByText('5 regular files · 0 excluded items').waitFor();
  // Local-server access checks, independent of UI controls.
  const base=url.split('/#')[0];
  assert.equal((await fetch(base+'/api/state',{method:'POST',body:'{}'})).status,409);
  assert.equal((await fetch(base+'/api/state',{method:'POST',headers:{'X-Desk-Token':url.split('#')[1],Origin:'https://untrusted.example'},body:'{}'})).status,409);
  assert.equal(await new Promise((resolve,reject)=>{const req=request(base+'/',{headers:{Host:'untrusted.example'}},res=>{res.resume();resolve(res.statusCode);});req.on('error',reject);req.end();}),403);
  observations.push('Unauthenticated, foreign-origin, and invalid-Host requests refused');
  await page.locator('#find').fill('camera'); await page.locator('#replace').fill('photo');
  await page.locator('#prefix').fill('travel-'); await page.locator('#suffix').fill('-icon');
  await page.locator('#number').check();
  await page.getByRole('button',{name:'Generate preview'}).click();
  await page.getByText('5 filename changes validated.',{exact:false}).waitFor();
  const inputs=page.locator('#rows input');
  assert.deepEqual(await inputs.evaluateAll(els=>els.map(e=>e.value)),['travel-001-photo-icon.svg','travel-002-coffee-icon.svg','travel-003-map-icon.svg','travel-004-music-icon.svg','travel-005-sun-icon.svg']);
  assert.deepEqual(await hashes(),original);
  await inputs.nth(0).fill('cover.svg'); await inputs.nth(1).fill('cover.svg');
  assert.equal(await page.locator('#apply').isDisabled(),true);
  await page.getByRole('button',{name:'Validate edited preview'}).click();
  await page.getByText('Duplicate destination',{exact:false}).waitFor();
  assert.equal(await page.locator('#apply').isDisabled(),true);
  await inputs.nth(1).fill('travel-002-coffee-icon.svg');
  await page.getByRole('button',{name:'Validate edited preview'}).click();
  await page.getByText('5 filename changes validated.',{exact:false}).waitFor();
  await mkdir(join(root,'results'),{recursive:true});
  await page.screenshot({path:join(root,'results/demo-preview.png'),fullPage:true});
  const destinations=await inputs.evaluateAll(els=>els.map(e=>e.value));
  const expected=Object.fromEntries(Object.keys(original).map((name,i)=>[destinations[i],original[name]]));
  await page.getByRole('button',{name:'Apply displayed plan'}).click();
  await page.getByText('Renamed successfully.',{exact:false}).waitFor();
  assert.deepEqual(await hashes(),expected);
  await page.reload(); await page.getByRole('button',{name:'Undo operation'}).waitFor();
  await page.screenshot({path:join(root,'results/demo-applied.png'),fullPage:true});
  // A conflicting outside file must survive a refused undo.
  await writeFile(join(folder,'camera.svg'),'unrelated file');
  const conflictState=await hashes();
  await page.getByRole('button',{name:'Undo operation'}).click();
  await page.getByText('Recovery destination occupied',{exact:false}).waitFor();
  assert.deepEqual(await hashes(),conflictState);
  await unlink(join(folder,'camera.svg'));
  await page.getByRole('button',{name:'Undo operation'}).click();
  await page.getByText('Original names restored.',{exact:false}).waitFor();
  assert.deepEqual(await hashes(),original);
  observations.push('Real files: literal replacement, prefix, suffix, numbering, extension preservation, manual edit, collision resolution, explicit apply, reload, conflict refusal, and undo');
  // Browser sends an apply; the process terminates after its third durable move.
  await stop(); const crashURL=await start(3); await page.goto(crashURL);
  await page.getByText('5 regular files · 0 excluded items').waitFor();
  await page.locator('#prefix').fill('interrupted-');
  await page.getByRole('button',{name:'Generate preview'}).click();
  await page.getByText('5 filename changes validated.',{exact:false}).waitFor();
  const exited=new Promise(r=>child.once('exit',r));
  await page.getByRole('button',{name:'Apply displayed plan'}).click();
  assert.equal(await exited,86);
  const recoveryURL=await start(); await page.goto(recoveryURL);
  await page.getByRole('button',{name:'Recover original names'}).waitFor();
  await page.getByText('APPLYING · 5 files',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Recover original names'}).click();
  await page.getByText('Original names restored.',{exact:false}).waitFor();
  assert.deepEqual(await hashes(),original);
  observations.push('After controlled process exit during staging, restarted browser honestly showed APPLYING and recovered original names and hashes');
  assert.deepEqual(errors,[]);
  await writeFile(join(root,'results/browser.json'),JSON.stringify({inputRevision:provenance.revision,files:5,observations,originalHashes:original,appliedHashes:expected,recoveredHashes:await hashes(),browserVersion:browser.version(),limitations:['Controlled process exits, not power failure testing','Linux local filesystem and headless Chromium only']},null,2)+'\n');
  console.log('PASS: real-input browser workflow, independent path/hash oracle, conflict refusal, interruption recovery');
} finally {
  if(browser) await browser.close(); await stop(); await rm(folder,{recursive:true,force:true});
}
