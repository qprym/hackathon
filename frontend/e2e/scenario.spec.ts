import { test, expect } from "@playwright/test";
test("login, personalized feed, evidence and company switch", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Новостная аналитика", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Учебные события", exact: true }).click();
  await expect(page.locator(".event-card").first()).toBeVisible();
  await page.getByRole("button", { name: "Разобрать влияние" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Влияние на ваш бизнес", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page.locator(".source-ref").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть источник" }).click();
  await page.getByRole("button", { name: "К событиям" }).click();
  await page
    .getByLabel("Компания", { exact: true })
    .selectOption("demo-retail");
  await page.getByLabel("Моя роль", { exact: true }).selectOption("TREASURER");
  await expect(page.locator(".company-heading")).toHaveText("Торговый контур");
  await expect(page.locator(".event-card").first()).toBeVisible();
});

test("viewer sees only the authorized company and cannot import", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Логин", { exact: true }).fill("viewer");
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(page.getByLabel("Компания", { exact: true }).locator("option")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Источники и импорт" })).toHaveCount(0);
  await page.getByRole("button", { name: "Контекст компании", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Платежные связи" })).toBeVisible();
  await expect(page.locator(".connection").filter({ hasText: /demo-logistics|demo-retail/ })).toHaveCount(0);
  expect((await page.request.get("/api/companies/demo-retail/context")).status()).toBe(403);
  expect((await page.request.get("/api/admin/metrics")).status()).toBe(403);
  const contextResponse = await page.request.get("/api/companies/demo-metal/context");
  const context = await contextResponse.json();
  expect(context.counterparties.every((c: { profile_available: boolean }) => !c.profile_available)).toBe(true);
});

test("unseen news is imported, analyzed and receives feedback", async ({ page }) => {
  const title = `Проверка сроков платежей ${Date.now()}`;
  await page.goto("/");
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await page.getByRole("button", { name: "Источники и импорт" }).click();
  await page.getByLabel("Заголовок", { exact: true }).fill(title);
  await page.getByLabel("Издатель", { exact: true }).fill("Учебная редакция · проверка");
  await page.getByLabel("Полный текст", { exact: true }).fill(
    `Синтетическое событие: контрагенты пересматривают сроки авансовых платежей. Для оценки оборотного капитала нужны договоры, графики обязательств и календарь расчетов компании. Проверочный экземпляр: ${title}.`,
  );
  await expect(page.getByLabel("Синтетический материал для демонстрации")).toBeChecked();
  await page.getByRole("button", { name: "Загрузить и обработать" }).click();
  await expect(page.getByRole("heading", { name: "Результат обработки" })).toBeVisible();
  await page.getByRole("button", { name: "Новостная аналитика", exact: true }).click();
  await page.getByRole("button", { name: "Учебные события", exact: true }).click();
  await page.getByLabel("Поиск по ленте", { exact: true }).fill(title);
  await page.locator('.event-card').filter({has:page.getByRole('button',{name:title,exact:true})})
    .getByRole('button',{name:'Разобрать влияние',exact:true}).click();
  await expect(page.getByRole("heading", { name: "Влияние на ваш бизнес", exact: true })).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Полезно", exact: true }).click();
  await expect(page.getByText("Сохранено", { exact: true })).toBeVisible();
  await page.getByLabel("Уточняющий вопрос").fill("Каких данных не хватает для оценки оборотного капитала?");
  await page.getByRole("button", { name: "Задать вопрос", exact: true }).click();
  await expect(page.locator(".answer")).toContainText("Демо без LLM не интерпретирует произвольный вопрос", { timeout: 30000 });
});
