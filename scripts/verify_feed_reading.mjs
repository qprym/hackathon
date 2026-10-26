// Read-only UI checks against the saved preview; never requests a new analysis.
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {expect} from '../frontend/node_modules/@playwright/test/index.mjs';
import {mkdir,writeFile} from 'node:fs/promises';
const base='http://127.0.0.1:8081';
await mkdir('tmp/preview-audit',{recursive:true});
const browser=await chromium.launch({headless:true});
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//,r=>r.abort());
  const page=await context.newPage();let analysisRequests=0;
  page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/analyses')analysisRequests++;});
  await page.goto(base);await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await expect(page.getByLabel('Компания',{exact:true})).toBeVisible();
  const before=await (await context.request.get(base+'/api/admin/metrics')).json();
  expect(before.mode).toBe('demo');
  await page.getByLabel('Компания',{exact:true}).selectOption('U_26491');
  await page.getByLabel('Моя роль',{exact:true}).selectOption('CFO');
  await expect(page.getByLabel('Режим работы ленты')).toContainText('модель отключена');
  const source=await (await context.request.get(base+'/api/sources/fe306c56-4f1c-4bfd-a0b3-c0195aa9aef5')).json();
  await page.getByLabel('Поиск по ленте',{exact:true}).fill(source.title);
  const rate=page.locator('.event-card').filter({has:page.getByRole('button',{name:source.title,exact:true})});
  await expect(rate).toBeVisible();
  const excerpt=await rate.locator('.event-summary').innerText();
  expect(source.content.replaceAll('\u00a0',' ')).toContain(excerpt.replaceAll('\u00a0',' '));
  expect(excerpt).toMatch(/[.!?…]$/);
  await expect(rate).toContainText('2п26 — 2-е полугодие 2026 года');
  await rate.getByRole('button',{name:'Читать полный доступный текст'}).click();
  await expect(page.getByRole('dialog').locator('.source-content')).toHaveText(source.content);
  await page.screenshot({path:'tmp/preview-audit/full-article.png',fullPage:true});
  await page.getByRole('button',{name:'Закрыть источник'}).click();
  const infrastructure=await (await context.request.get(base+'/api/sources/7266a530-831d-44a0-87ec-0620542e8a2d')).json();
  await page.getByLabel('Поиск по ленте',{exact:true}).fill(infrastructure.title);
  const card=page.locator('.event-card').filter({has:page.getByRole('button',{name:infrastructure.title,exact:true})});
  await expect(card).toContainText('Условная применимость');
  await card.getByRole('button',{name:'Почему нет разбора'}).click();
  await expect(card.getByRole('alert')).toContainText('Вызовы модели отключены');
  await card.getByText('Основания отбора',{exact:true}).click();
  await expect(card).toContainText('Признак профиля:');
  await card.screenshot({path:'tmp/preview-audit/unavailable-analysis.png'});
  await page.getByLabel('Поиск по ленте',{exact:true}).fill('');
  for(const order of ['newest','oldest']){
    const ready=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/feed'&&new URL(r.url()).searchParams.get('sort')===order);
    await page.getByLabel('Сортировка событий',{exact:true}).selectOption(order);
    const feed=await(await ready).json();
    await expect(page.locator('.event-card .event-title')).toHaveText(feed.items.map(item=>item.title));
    const dates=feed.items.map(item=>item.published_at);
    expect(dates).toEqual([...dates].sort((a,b)=>order==='newest'?b.localeCompare(a):a.localeCompare(b)));
  }
  await page.getByRole('button',{name:'Настроить автообновление',exact:true}).click();
  await expect(page.getByLabel('Автоматически загружать новости')).not.toBeChecked();
  await expect(page.getByLabel('Интервал обновления, минуты')).toHaveValue('30');
  await page.screenshot({path:'tmp/preview-audit/rss-settings.png',fullPage:true});
  const after=await (await context.request.get(base+'/api/admin/metrics')).json();
  expect(after.llm_allowance).toEqual(before.llm_allowance);
  expect(analysisRequests).toBe(0);
  const report={source_characters:source.content.length,whole_sentences:true,full_source_visible:true,
    abbreviation_explained:true,offline_mode_visible:true,inline_analysis_message:true,analysis_requests:analysisRequests,
    sorting_controls:true,rss_controls_visible:true,allowance:after.llm_allowance};
  await writeFile('tmp/preview-audit/reading-report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {await browser.close();}
