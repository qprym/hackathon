// Read-only browser audit of the existing keyless preview; no model submissions.
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import { expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
const base='http://127.0.0.1:8081';
await mkdir('tmp/preview-audit',{recursive:true});
const browser=await chromium.launch({headless:true});
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//,r=>r.abort());
  const page=await context.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await expect(page.getByLabel('Компания',{exact:true})).toBeVisible();
  const before=await (await context.request.get(base+'/api/admin/metrics')).json();
  const rows=[];
  for(const company of ['U_26491','U_989','U_6923']) for(const role of ['CEO','CFO','TREASURER']) {
    await page.getByLabel('Компания',{exact:true}).selectOption(company);
    await page.getByLabel('Моя роль',{exact:true}).selectOption(role);
    await page.getByRole('button',{name:'Все материалы',exact:true}).click();
    const ready=page.waitForResponse(r=>r.url().includes('/api/feed?')&&r.url().includes('company_id='+company)&&r.url().includes('role='+role)&&r.url().includes('scope=personal'));
    await page.getByRole('button',{name:'Для моей компании',exact:true}).click();
    const response=await ready;expect(response.status()).toBe(200);const feed=await response.json();
    await expect(page.locator('.event-card')).toHaveCount(Math.min(5,feed.total));
    const titles=await page.locator('.event-card h3').allTextContents();
    if(feed.next_offset!=null){
      const next=page.waitForResponse(r=>r.url().includes('/api/feed?')&&r.url().includes('feed_version='+feed.feed_version));
      await page.getByRole('button',{name:/Показать ещё/}).click();
      const part=await (await next).json();
      expect(part.feed_version).toBe(feed.feed_version);
      await expect(page.locator('.event-card')).toHaveCount(5+part.items.length);
      expect((await page.locator('.event-card h3').allTextContents()).slice(0,5)).toEqual(titles);
    }
    rows.push({company,role,total:feed.total,visible:await page.locator('.event-card').count(),version:feed.feed_version,state:feed.selection||feed.reading_list});
  }
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'tmp/preview-audit/feed.png',fullPage:true});
  await page.getByRole('button',{name:'Контекст компании',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Поиск по всем платёжным связям'})).toBeVisible();
  await page.goto(base+'/?run=7d517cf8-ac88-4184-924d-590d0c31414b');
  await expect(page.getByRole('heading',{name:'Мнение экспертов Альфа-Банка',exact:true})).toBeVisible({timeout:20000});
  await expect(page.getByRole('heading',{name:'Выводы AI для вашей компании',exact:true})).toBeVisible();
  await page.screenshot({path:'tmp/preview-audit/analysis.png',fullPage:true});
  await page.getByRole('button',{name:'Открыть материал'}).first().click();
  await expect(page.getByRole('dialog')).toContainText('Графики и таблицы требуют сверки');
  const after=await (await context.request.get(base+'/api/admin/metrics')).json();
  expect(after.llm_allowance.requests_used).toBe(before.llm_allowance.requests_used);
  expect(after.llm_allowance.spent_rub).toBe(before.llm_allowance.spent_rub);
  expect(errors).toEqual([]);
  const report={rows,browser_errors:errors,paid_calls:0,allowance:after.llm_allowance};
  await writeFile('tmp/preview-audit/report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify({profiles:3,roles:3,pagination_checked:true,bank_ai_separation:true,paid_calls:0,requests_used:after.llm_allowance.requests_used,spent_rub:after.llm_allowance.spent_rub}));
} finally {await browser.close();}
