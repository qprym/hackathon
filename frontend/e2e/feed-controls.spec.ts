import {test,expect} from '@playwright/test';

test('sorting can switch between personal relevance and publication date across pages',async({page})=>{
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await page.getByRole('button',{name:'Все материалы',exact:true}).click();
  for(const order of ['newest','oldest']){
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/feed'&&new URL(r.url()).searchParams.get('sort')===order);
    await page.getByLabel('Сортировка событий',{exact:true}).selectOption(order);
    const data=await(await response).json();
    await expect(page.locator('.event-card .event-title')).toHaveText(data.items.map((item:{title:string})=>item.title));
    const dates=data.items.map((item:{published_at:string})=>item.published_at);
    expect(dates).toEqual([...dates].sort((a,b)=>order==='newest'?b.localeCompare(a):a.localeCompare(b)));
    if(data.next_offset!==null){
      const next=page.waitForResponse(r=>r.url().includes('feed_version='+data.feed_version));
      await page.getByRole('button',{name:/Показать ещё/}).click();const part=await(await next).json();
      await expect(page.locator('.event-card .event-title')).toHaveText([...data.items,...part.items].map((item:{title:string})=>item.title));
    }
  }
  await page.getByLabel('Сортировка событий',{exact:true}).selectOption('relevance');
});

test('RSS settings are visible from the feed and persist without enabling LLM or fetching news',async({page})=>{
  await page.goto('/');await page.getByRole('button',{name:'Войти в кабинет'}).click();
  await page.getByRole('button',{name:'Настроить автообновление',exact:true}).click();
  const form=page.getByRole('region',{name:'Автообновление новостей',exact:true});
  await expect(form.getByLabel('Автоматически загружать новости')).not.toBeChecked();
  const before=await(await page.request.get('/api/admin/llm-settings')).json();
  await form.getByLabel('Автоматически загружать новости').check();
  await form.getByLabel('Автоматически загружать новости').uncheck();
  await form.getByLabel('Интервал обновления, минуты').fill('5');
  await form.getByLabel('Банк России',{exact:true}).uncheck();
  await form.getByRole('button',{name:'Сохранить расписание'}).click();
  await expect(form.getByRole('status')).toContainText('Автообновление отключено');
  const saved=await(await page.request.get('/api/admin/feed-settings')).json();
  expect(saved.sources).toEqual(['vedomosti']);expect(saved.interval_seconds).toBe(300);expect(saved.automatic).toBe(false);
  const after=await(await page.request.get('/api/admin/llm-settings')).json();
  delete before.revision;delete after.revision;expect(after).toEqual(before);
  await page.reload();await page.getByRole('button',{name:'Источники и импорт',exact:true}).click();
  await expect(form.getByLabel('Интервал обновления, минуты')).toHaveValue('5');
  await expect(form.getByLabel('Банк России',{exact:true})).not.toBeChecked();
  await form.getByLabel('Банк России',{exact:true}).check();
  await form.getByLabel('Интервал обновления, минуты').fill('30');
  await form.getByRole('button',{name:'Сохранить расписание'}).click();
  await expect(form.getByRole('status')).toContainText('Автообновление отключено');
});
