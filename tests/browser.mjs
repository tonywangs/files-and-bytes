import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
const root = path.resolve(import.meta.dirname,'..');
const temp = await fs.mkdtemp(path.join(os.tmpdir(),'parity-browser-'));
const server = spawn('python3',['-m','desk.server','--workspace',path.join(temp,'workspace'),'--port','0'],{cwd:root,stdio:['ignore','pipe','pipe']});
let browser;
try {
  const url = await new Promise((resolve,reject)=>{
    let output='';
    const timer=setTimeout(()=>reject(Error('Server startup timeout')),15000);
    server.stdout.on('data',b=>{output+=b;const m=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});
    server.on('exit',code=>{clearTimeout(timer);reject(Error(`Server exited ${code}: ${output}`));});
    server.stderr.on('data',b=>{output+=b;});
  });
  const launch = {headless:true};
  if (process.env.CHROMIUM_PATH) launch.executablePath=process.env.CHROMIUM_PATH;
  browser=await chromium.launch(launch);
  const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(url);
  await page.getByRole('status').filter({hasText:'Ready.'}).waitFor();
  assert.equal(await page.locator('#files input:checked').count(),8);
  await page.locator('#redundancy').fill('30');
  await page.locator('#block').fill('256');
  const waitAction=async(action)=>{
    await page.waitForFunction(action=>document.querySelector('#status').textContent.startsWith(action+':') || document.querySelector('#status').textContent.startsWith('Error:'),action,{timeout:30000});
    const status=await page.locator('#status').innerText();
    assert.ok(!status.startsWith('Error:'),status);
  };
  await page.locator('#create').click();await waitAction('create');
  const packageID=await page.locator('#packages').inputValue();
  assert.ok(packageID.startsWith('package-'));
  assert.ok((await page.locator('#package-info').innerText()).includes('10'));
  // Download one real recovery volume via the UI.
  const parDownload=page.waitForEvent('download');
  await page.locator('#package-info a').first().click();
  const par=await parDownload;
  assert.ok((await fs.readFile(await par.path())).subarray(0,8).equals(Buffer.from('PAR2\0PKT')));
  await page.locator('#verify').click();await waitAction('verify');
  assert.equal(await page.locator('#report .badge').innerText(),'verified-intact');
  await page.reload();await page.getByRole('status').filter({hasText:'Ready.'}).waitFor();
  assert.equal(await page.locator('#packages').inputValue(),packageID);
  await page.locator('#scenario').selectOption('missing-file');
  await page.locator('#demo').click();await waitAction('demo');
  assert.ok((await page.locator('#mutation').innerText()).includes('delete smallest'));
  const candidate=await page.locator('#candidate').inputValue();
  await page.locator('#verify').click();await waitAction('verify');
  assert.equal(await page.locator('#report .badge').innerText(),'repair-possible');
  assert.equal(await page.locator('#report tbody tr').count(),8);
  await page.locator('#repair').click();await waitAction('repair');
  assert.equal(await page.locator('#report .badge').innerText(),'verified-restored');
  // Every restored file is downloaded through the browser, compared outside the
  // application, then actually reopened in a separate browser document.
  const outputs=[];
  for (const anchor of await page.locator('#report a[href*="kind=restored"]').all()) {
    const downloadEvent=page.waitForEvent('download');await anchor.click();const dl=await downloadEvent;
    const file=path.join(temp,dl.suggestedFilename());await dl.saveAs(file);
    const original=await fs.readFile(path.join(root,'data/twemoji',dl.suggestedFilename()));
    const restored=await fs.readFile(file);assert.deepEqual(restored,original);
    const hash=crypto.createHash('sha256').update(restored).digest('hex');
    const reopened=await browser.newPage();await reopened.goto('file://'+file);
    assert.equal(await reopened.locator('svg').count(),1);await reopened.close();
    outputs.push({name:dl.suggestedFilename(),sha256:hash,byte_equal:true,reopened_svg:true});
  }
  assert.equal(outputs.length,8);
  // Candidate remains missing its deleted member even after repair.
  assert.equal((await fs.readdir(candidate)).length,7);
  const jsonEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Export JSON report'}).click();
  const downloadedReport=JSON.parse(await fs.readFile(await (await jsonEvent).path(),'utf8'));
  assert.equal(downloadedReport.basis,'independent-original-sha256');
  assert.equal(downloadedReport.output_files.length,8);
  const htmlEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Export HTML report'}).click();
  const htmlPath=path.join(temp,'report.html');await (await htmlEvent).saveAs(htmlPath);
  const reportPage=await browser.newPage();await reportPage.goto('file://'+htmlPath);
  assert.equal(await reportPage.locator('h2').first().innerText(),'verified-restored');await reportPage.close();
  await page.screenshot({path:path.join(root,'results/browser-demo.png'),fullPage:true});
  for(const scenario of ['insufficient-recovery','damaged-recovery']) {
    await page.locator('#scenario').selectOption(scenario);
    await page.locator('#demo').click();await waitAction('demo');
    await page.locator('#repair').click();await waitAction('repair');
    assert.equal(await page.locator('#report .badge').innerText(),'insufficient-recovery');
    assert.equal(await page.locator('#report a[href*="kind=restored"]').count(),0);
  }
  // Import through the UI and make its weaker basis visible.
  await page.locator('summary').filter({hasText:'Import an existing'}).click();
  await page.locator('#import-directory').fill(path.join(temp,'workspace',packageID,'recovery'));
  await page.locator('#import').click();await waitAction('import');
  assert.ok((await page.locator('#package-info').innerText()).includes('imported-par2-md5-only'));
  await page.locator('#candidate').fill(path.join(root,'data/twemoji'));
  await page.locator('#recovery').fill('');
  await page.locator('#verify').click();await waitAction('verify');
  assert.equal(await page.locator('#report .badge').innerText(),'verified-intact');
  assert.ok((await page.locator('#report').innerText()).includes('imported-par2-md5-only'));
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(root,'results/browser.json'),JSON.stringify({browser:await browser.version(),workflow:'real Twemoji collection; create, verify, reload, damage, inspect, explicit repair, download every file, independent byte/hash comparison, reopen SVGs, HTML/JSON report, insufficient and damaged recovery, import, mobile layout',files:outputs,passed:true},null,2)+'\n');
  console.log('Browser workflow passed; all 8 downloaded restorations independently match and reopen.');
} finally {
  if(browser)await browser.close();
  server.kill('SIGTERM');
  await new Promise(resolve=>{if(server.exitCode!==null)resolve();else server.once('exit',resolve);});
  await fs.rm(temp,{recursive:true,force:true});
}
