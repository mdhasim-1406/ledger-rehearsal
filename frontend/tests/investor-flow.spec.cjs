const { chromium } = require('/home/mohamedhasim/zaha-sync-triage/web/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.APP_URL || 'http://127.0.0.1:28752';
const api = process.env.API_URL || 'http://127.0.0.1:28751';
const shots = path.resolve('artifacts');
fs.mkdirSync(shots, { recursive: true });
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
  const failed=[]; page.on('pageerror',e=>failed.push(e.message));
  const health=await (await page.request.get(api+'/api/health')).json();
  assert.equal(health.mode,'synthetic-demo'); assert.match(health.writes,/non-financial/);
  await page.goto(base); await page.getByText('Local synthetic demo',{exact:false}).waitFor();
  await page.screenshot({path:path.join(shots,'overview-desktop.png'),fullPage:true});
  assert.equal(await page.locator('.stat').count(),3);
  await page.getByRole('button',{name:/All cases/}).click();
  const row=page.locator('.case-row').filter({hasText:'Fee Discrepancy'}); await row.click();
  await page.getByText('Source evidence',{exact:false}).waitFor();
  await page.getByRole('button',{name:/Start investigation/}).click();
  await page.getByText('The investigation is running.',{exact:false}).waitFor({timeout:10000});
  await page.locator('.preview-note').waitFor({timeout:20000});
  await page.screenshot({path:path.join(shots,'case-proposal-desktop.png'),fullPage:true});
  assert.equal(await page.locator('pre').count(),0,'raw JSON must not be exposed in page');
  assert.equal(await page.locator('.journal-facts').getByText('Financial posting',{exact:false}).count(),1);
  async function apiCaseId(){return (await (await page.request.get(api+'/api/cases')).json()).cases.find(c=>c.title==='Fee Discrepancy').id}
  // Approval/apply only after reviewing the actual proposal and evidence.
  const reviewHash=await page.locator('.hash code').innerText();
  await page.getByRole('button',{name:/Approve exact proposal/}).click();
  await page.getByRole('heading',{name:'Approve this exact proposal?'}).waitFor();
  await page.getByRole('button',{name:'Approve proposal'}).click();
  await page.getByRole('status').filter({hasText:'Approval recorded'}).waitFor();
  let data=await (await page.request.get(api+'/api/cases/'+(await apiCaseId()))).json();
  assert.equal(data.case.status,'approved'); assert.equal(data.case.posting,'not supported; sandbox state changes only');
  await page.getByRole('button',{name:/Apply approved change/}).click();
  await page.getByRole('heading',{name:'Apply the approved change?'}).waitFor();
  await page.getByRole('button',{name:'Apply change'}).click();
  await page.getByRole('status').filter({hasText:'No financial journal entry was posted'}).waitFor();
  data=await (await page.request.get(api+'/api/cases/'+(await apiCaseId()))).json();
  assert.equal(data.case.status,'resolved_nonfinancial'); assert.equal(data.events.at(-1).type,'applied_nonfinancial');
  const records=await (await page.request.get(api+'/api/records')).json(); assert(records.records.filter(r=>data.proposal.operation.record_ids.includes(r.id)).every(r=>r.status==='reviewed'));
  await page.getByRole('button',{name:'Records',exact:true}).click(); await page.getByRole('heading',{name:'Records',exact:true}).waitFor();
  await page.locator('.record').first().waitFor({timeout:5000}).catch(()=>{});
  assert((await page.locator('.record').count())>=4);
  await page.screenshot({path:path.join(shots,'records-desktop.png'),fullPage:true});
  const mobile=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1}); mobile.on('pageerror',e=>failed.push(e.message));
  await mobile.goto(base); await mobile.getByText('Local synthetic demo',{exact:false}).waitFor();
  assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overview has no horizontal overflow');
  await mobile.getByRole('button',{name:'Open navigation'}).click(); await mobile.locator('.side.open .nav').filter({hasText:'Cases'}).click();
  await mobile.locator('.case-row').filter({hasText:'Payment Mismatch'}).click();
  await mobile.getByText('Source evidence',{exact:false}).waitFor();
  assert.equal(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'case has no horizontal overflow');
  await mobile.screenshot({path:path.join(shots,'case-mobile.png'),fullPage:true});
  assert.deepEqual(failed,[]);
  console.log(JSON.stringify({ok:true,backend:health.mode,case:'Fee Discrepancy',approval:'verified from API',application:'resolved_nonfinancial; records marked reviewed; no financial posting',evidenceCount:data.evidence.length,recordCount:records.records.length,mobileOverflow:false,screenshots:fs.readdirSync(shots)},null,2));
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
