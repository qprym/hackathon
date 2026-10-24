import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('independent labels stay local and survive export', async ({ page }) => {
  const contexts = Object.fromEntries(['a','b','c'].map(id => [id,{name:id,industry:'Перевозки',region:'Москва',features:{industry:{value:'Перевозки',source:'case'}},missing:[],limitations:[]}]));
  const relevance = Object.fromEntries(['a','b','c'].flatMap(c=>['CEO','CFO','TREASURER'].map(r=>[`${c}:${r}`,null])));
  const bundle = {schema_version:2,companies:['a','b','c'],contexts,rubric:{0:'Не релевантно',1:'Полезно',2:'Приоритетно'},events:[
    {id:'x',title:'<img src=x onerror=alert(1)>',published_at:'2026-10-24',split:'development',relevance,comments:{},sources:[{title:'Источник',publisher:'Тест',content:'Текст для оценки',coverage:'full'}]},
    {id:'y',title:'Вторая новость',published_at:'2026-10-24',split:'holdout',relevance:{...relevance},comments:{},sources:[]}
  ]};
  const requests: string[] = [];
  page.on('request',r=>requests.push(r.url()));
  await page.goto('/review.html');
  await page.getByLabel('Файл для разметки').setInputFiles({name:'review.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(bundle))});
  await expect(page.locator('#title')).toHaveText('<img src=x onerror=alert(1)>');
  await expect(page.locator('img')).toHaveCount(0);
  await page.getByLabel('Ваше имя или псевдоним').fill('Тестовый рецензент');
  await page.getByLabel('Ваша оценка').selectOption('1');
  await page.getByLabel('Комментарий', {exact:true}).fill('Полезно для планирования');
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'Сохранить прогресс'}).click();
  const file=await downloaded;
  const saved=JSON.parse(await readFile((await file.path())!, 'utf8'));
  expect(saved.events[0].relevance['a:CEO']).toBe(1);
  expect(saved.events[0].relevance['b:CFO']).toBeNull();
  expect(saved.events[0].comments['a:CEO']).toBe('Полезно для планирования');
  expect(saved.reviewer).toBe('Тестовый рецензент');
  expect(requests.every(url=>!url.includes('/api/') && !url.includes('deepseek'))).toBeTruthy();
  await page.getByLabel('Часть набора').selectOption('holdout');
  await expect(page.locator('#holdout')).toBeVisible();
});
