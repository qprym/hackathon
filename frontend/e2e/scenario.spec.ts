import { test, expect } from "@playwright/test";
test("login, personalized feed, evidence and company switch", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Войти в кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Новостная аналитика", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".event-card").first()).toBeVisible();
  await page.getByRole("button", { name: "Разобрать влияние" }).first().click();
  await expect(
    page.getByText("ВЛИЯНИЕ НА ВАШ БИЗНЕС", { exact: true }),
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
