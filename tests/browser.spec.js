const {test,expect}=require('@playwright/test');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {pathToFileURL}=require('node:url');

test('real folder: scan, navigate, filter, inspect, sort, export and offline reopen',async({page,browser})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:4173');
 await page.getByRole('button',{name:'Scan selected folder'}).click();
 await expect(page.locator('#status')).toContainText('Complete enumeration');
 await expect(page.locator('#count')).toHaveText('296');
 await expect(page.locator('#apparent')).toHaveText('4,398,621');
 await page.locator('#treemap').getByRole('button',{name:'directory contrib',exact:true}).click();
 await expect(page.locator('#crumbs')).toContainText('contrib');
 await page.locator('#crumbs button').first().click();
 await page.getByLabel('Filename filter').fill('zlib.h');
 await expect(page.locator('#rows tr')).toHaveCount(1);
 await page.locator('#rows').getByRole('button',{name:'zlib.h',exact:true}).click();
 await expect(page.locator('#inspection')).toContainText('"raw_apparent": 96829');
 await page.getByLabel('Filename filter').fill('');
 await page.getByRole('button',{name:'Name ↕'}).click();
 const names=await page.locator('#rows td:first-child').allTextContents();
 expect(names.length).toBeGreaterThan(20);
 expect(names).toEqual([...names].sort((a,b)=>b.localeCompare(a)));
 await page.getByLabel('Treemap area').selectOption('allocated');
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'atlas-export-'));
 for(const [label,name] of [['Save JSON','report.json'],['Save offline HTML','report.html']]){
   const waiting=page.waitForEvent('download');await page.getByRole('button',{name:label}).click();await (await waiting).saveAs(path.join(temp,name));
 }
 const json=JSON.parse(await fs.readFile(path.join(temp,'report.json'),'utf8'));
 expect(json.counts.files).toBe(257);expect(json.complete).toBe(true);expect(json.rules.hard_links).toContain('first encounter');
 await page.screenshot({path:'results/browser-demo.png',fullPage:true});
 const context=await browser.newContext({offline:true});const offline=await context.newPage();const requests=[];
 offline.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url())});offline.on('pageerror',e=>errors.push(e.message));
 await offline.goto(pathToFileURL(path.join(temp,'report.html')).href);
 await expect(offline.locator('#status')).toContainText('Historical snapshot');
 await expect(offline.locator('#count')).toHaveText('296');
 await offline.getByLabel('Filename filter').fill('contrib');
 await offline.locator('#treemap').getByRole('button',{name:'directory contrib',exact:true}).click();
 await offline.getByLabel('Filename filter').fill('');
 await expect(offline.locator('#rows tr')).not.toHaveCount(0);
 await offline.locator('#crumbs button').first().click();
 await offline.getByLabel('Filename filter').fill('zlib.h');
 await offline.locator('#rows').getByRole('button',{name:'zlib.h',exact:true}).click();
 await expect(offline.locator('#inspection')).toContainText('96829');
 expect(requests).toEqual([]);expect(errors).toEqual([]);
 await context.close();
 await fs.writeFile('results/browser-verification.json',JSON.stringify({workflow:'Real zlib scan, treemap navigation, breadcrumb, filename filter, file inspection, table sorting, allocated view, JSON/HTML download, offline reopening and navigation',entries:json.counts.discovered,files:json.counts.files,offline_network_requests:requests,page_errors:errors,browser:'Chromium',passed:true},null,2)+'\n');
});

test('zero-size, excluded, unicode and inert names remain accessible',async({page})=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'atlas-controls-'));
 await fs.writeFile(path.join(dir,'empty'), '');await fs.writeFile(path.join(dir,'雪 <img onerror=alert(1)>'),'abc');await fs.mkdir(path.join(dir,'excluded'));
 const server=spawn('python3',['-m','atlas',dir,'--port','4174','--exclude','excluded']);
 try{
  await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',code=>reject(Error('server '+code)))});
  await page.goto('http://127.0.0.1:4174');await page.getByRole('button',{name:'Scan selected folder'}).click();
  await expect(page.locator('#status')).toContainText('INCOMPLETE SCAN');
  await expect(page.locator('#rows tr')).toHaveCount(3);
  await page.locator('#rows').getByRole('button',{name:'empty',exact:true}).click();await expect(page.locator('#inspection')).toContainText('"raw_apparent": 0');
  await page.locator('#rows').getByRole('button',{name:'excluded',exact:true}).click();await expect(page.locator('#inspection')).toContainText('Excluded basename');
  await page.getByRole('button',{name:'雪 <img onerror=alert(1)>',exact:true}).click();
  await expect(page.locator('#inspection')).toContainText('雪 <img onerror=alert(1)>');expect(await page.locator('img').count()).toBe(0);
 }finally{server.kill();await fs.rm(dir,{recursive:true,force:true})}
});

test('server rejects unrelated origins and exposes no arbitrary file endpoint',async({request})=>{
 expect((await request.post('http://127.0.0.1:4173/api/scan',{headers:{Origin:'https://example.com'}})).status()).toBe(403);
 expect((await request.get('http://127.0.0.1:4173/api/config',{headers:{Host:'example.com'}})).status()).toBe(403);
 expect((await request.get('http://127.0.0.1:4173/etc/passwd')).status()).toBe(404);
});

test('labeled large-byte control preserves exact decimal evidence through offline export',async({page})=>{
 const {execFileSync}=require('node:child_process');
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'atlas-large-control-'));
 const fixture=execFileSync('python3',['-c',"import json; from atlas.report import html; r=json.load(open('demo/sample.json')); r['root']='Labeled large-integer transport control'; r['totals']['apparent']=2**53+1; r['entries'][0]['apparent']=2**53+1; print(html(r))"],{encoding:'utf8'});
 await fs.writeFile(path.join(temp,'large.html'),fixture);
 await page.goto(pathToFileURL(path.join(temp,'large.html')).href);
 await expect(page.locator('#inspection')).toContainText('9007199254740993');
 const waiting=page.waitForEvent('download');await page.getByRole('button',{name:'Save JSON'}).click();await (await waiting).saveAs(path.join(temp,'large.json'));
 const exported=JSON.parse(await fs.readFile(path.join(temp,'large.json'),'utf8'));
 expect(exported.totals.apparent).toBe('9007199254740993');
 expect(exported.entries[0].apparent).toBe('9007199254740993');
});
