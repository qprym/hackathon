import { test, expect } from '@playwright/test';

test('fresh demo opens a populated feed and all nine static examples without a model', async ({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'Войти в кабинет'}).click();
  // Do not switch the corpus manually: this is what a reviewer sees after login.
  await expect(page.locator('.event-card').first()).toBeVisible();
  for(const name of ['Северный металл','Торговый контур','Вектор логистики']) {
    for(const role of ['CEO','CFO','Казначей']) {
      await page.getByRole('button',{name:'Готовые примеры',exact:true}).click();
      const card=page.locator('.library-card').filter({has:page.getByRole('heading',{name,exact:true})});
      await card.getByRole('button',{name:`Открыть разбор · ${role}`,exact:true}).click();
      await expect(page.getByText('ГОТОВЫЙ УЧЕБНЫЙ ПРИМЕР',{exact:true})).toBeVisible();
      await expect(page.getByRole('heading',{name:'Влияние на ваш бизнес',exact:true})).toBeVisible();
      await page.locator('.source-ref').first().click();
      await expect(page.getByRole('dialog')).toContainText('Учебная');
      await page.getByRole('button',{name:'Закрыть источник'}).click();
    }
  }
  const metrics=await (await page.request.get('/api/admin/metrics')).json();
  expect(metrics.llm_allowance.requests_used).toBe(0);
});
