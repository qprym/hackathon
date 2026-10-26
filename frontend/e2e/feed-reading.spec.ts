import {test,expect} from '@playwright/test';

test('article title opens the complete source without requesting an analysis',async({page})=>{
  let calls=0;page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/analyses')calls++;});
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  const card=page.locator('.event-card').first();await expect(card).toBeVisible();
  const response=page.waitForResponse(r=>/\/api\/sources\/[^/]+$/.test(new URL(r.url()).pathname));
  await card.locator('.event-title').click();const source=await(await response).json();
  await expect(page.getByRole('dialog').locator('.source-content')).toHaveText(source.content);
  expect(calls).toBe(0);
  await page.getByRole('button',{name:'Закрыть источник'}).click();
  await expect(card.locator('.event-summary')).not.toHaveCSS('-webkit-line-clamp','2');
});

test('analysis progress and a rejected request are visible in the clicked card',async({page})=>{
  let release!:()=>void;
  let markRequested!:()=>void;
  const requested=new Promise<void>(resolve=>{markRequested=resolve;});
  await page.route('**/api/analyses',async route=>{
    await new Promise<void>(resolve=>{release=resolve;markRequested();});
    await route.fulfill({status:429,contentType:'application/json',body:JSON.stringify({detail:'Проверочная ошибка: лимит модели исчерпан.'})});
  });
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  const card=page.locator('.event-card').first();await expect(card).toBeVisible();
  await card.getByRole('button',{name:'Разобрать влияние',exact:true}).click();
  await requested;
  await expect(card.getByRole('button',{name:'Открываем разбор…'})).toBeDisabled();
  release();
  await expect(card.getByRole('alert')).toContainText('Проверочная ошибка: лимит модели исчерпан.');
  await expect(card.getByRole('button',{name:'Разобрать влияние',exact:true})).toBeEnabled();
});
