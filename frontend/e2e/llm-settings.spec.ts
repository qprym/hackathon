import {test,expect} from '@playwright/test';

test('administrator can save a token, reload it masked, remove it and restore server defaults',async({page})=>{
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await expect(page.getByRole('button',{name:'Настройки LLM',exact:true})).toBeVisible();
  const before=await (await page.request.get('/api/admin/metrics')).json();
  await page.getByRole('button',{name:'Настройки LLM',exact:true}).click();
  await expect(page.getByLabel('Токен API',{exact:true})).toHaveAttribute('type','password');
  await page.getByLabel('Адрес API',{exact:true}).fill('https://example.invalid/v1');
  await page.getByLabel('Токен API',{exact:true}).fill('browser-test-credential-not-real');
  await expect(page.getByLabel('Разрешить вызовы LLM')).not.toBeChecked();
  await page.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Настройки сохранены');
  await expect(page.getByLabel('Токен API',{exact:true})).toHaveValue('');
  const saved=await (await page.request.get('/api/admin/llm-settings')).json();
  expect(saved.api_key_configured).toBe(true);
  expect(JSON.stringify(saved)).not.toContain('browser-test-credential-not-real');
  await page.reload();await page.getByRole('button',{name:'Настройки LLM',exact:true}).click();
  await expect(page.getByLabel('Токен API',{exact:true})).toHaveValue('');
  await expect(page.getByText('Сохранённый ключ не отображается.',{exact:true})).toBeVisible();
  await page.getByLabel('Удалить сохранённый ключ при сохранении').check();
  await page.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Настройки сохранены');
  expect((await (await page.request.get('/api/admin/llm-settings')).json()).api_key_configured).toBe(false);
  await page.getByRole('button',{name:'Вернуть настройки из .env',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Восстановлены настройки');
  const after=await (await page.request.get('/api/admin/metrics')).json();
  expect(after.llm_allowance).toEqual(before.llm_allowance);
  await page.getByRole('button',{name:'Выйти из кабинета'}).click();
  await page.getByLabel('Логин',{exact:true}).fill('viewer');
  await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await expect(page.getByLabel('Компания',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Настройки LLM',exact:true})).toHaveCount(0);
});

test('topic buttons stay stable when choosing liquidity and returning to all events',async({page})=>{
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await page.getByRole('button',{name:'Все материалы',exact:true}).click();
  const topics=page.getByLabel('Темы новостей',{exact:true});
  await expect(topics.getByRole('button',{name:'Ликвидность',exact:true})).toBeVisible();
  const before=await topics.getByRole('button').allTextContents();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/feed?')&&new URL(r.url()).searchParams.get('topic')==='liquidity'),topics.getByRole('button',{name:'Ликвидность',exact:true}).click()]);
  await expect(page.locator('.event-card').first()).toBeVisible();
  expect(await topics.getByRole('button').allTextContents()).toEqual(before);
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/feed?')&&!new URL(r.url()).searchParams.get('topic')),topics.getByRole('button',{name:'Все события',exact:true}).click()]);
  await expect(page.locator('.event-card').first()).toBeVisible();
  expect(await topics.getByRole('button').allTextContents()).toEqual(before);
});
