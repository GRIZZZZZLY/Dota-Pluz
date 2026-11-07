import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("live page plays the demo match", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Игры пока нет" })).toBeVisible();
  await page.getByRole("button", { name: "Запустить демо-матч" }).click();
  await expect(page.getByText("Демо-матч, выдуманные цифры")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Juggernaut" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Ближайшие таймеры")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Следующие предметы" })).toBeVisible();
  await expect(page.getByText("Получаем данные игры").or(page.getByText("Идёт демо-матч"))).toBeVisible();
  await page.getByRole("button", { name: "Остановить" }).click();
  await expect(page.getByRole("heading", { name: "Игры пока нет" })).toBeVisible({ timeout: 10_000 });
});

test("draft fills in from the game by itself", async ({ page, request }) => {
  await request.post("/api/demo", { data: { hero: "juggernaut", speed: 4, minutes: 3 } });
  await page.goto("/draft");
  const status = page.getByRole("region", { name: "Из игры" });
  await expect(status).toContainText("ваш герой и команда из игры", { timeout: 20_000 });
  await expect(status).toContainText("объявлений в игровом чате");
  await expect(status).toContainText("не передаёт игроку чужие пики");
  await expect(page.getByLabel("Пики Света").getByText("Juggernaut")).toBeVisible();
  await expect(page.getByLabel("Баны", { exact: true }).locator("button.ban")).toHaveCount(4);
  await request.post("/api/live/reset");
});

test("draft by keyboard gives suggestions and a win estimate", async ({ page }) => {
  await page.goto("/draft");
  const search = page.getByLabel("Поиск героя");
  for (const hero of ["pa", "lion", "invo"]) {
    await search.fill(hero);
    await search.press("Enter");
  }
  await search.press("Tab");
  for (const hero of ["cm", "axe"]) {
    await search.fill(hero);
    await search.press("Enter");
  }
  await expect(page.getByLabel("Пики Света").getByText("Crystal Maiden")).toBeVisible();
  await expect(page.getByLabel("Пики Тьмы").getByText("Phantom Assassin")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Пики для вас" })).toBeVisible();
  await expect(page.getByLabel("Оценка шанса на победу")).toBeVisible();
  await expect(page.locator("table.suggest tbody tr")).toHaveCount(15);
  await page.getByRole("tab", { name: "Поз. 5" }).click();
  await expect(page.locator("table.suggest tbody tr").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Предметы против их драфта" })).toBeVisible();
  await page.getByRole("button", { name: "Очистить" }).click();
  await expect(page.getByLabel("Пики Тьмы").getByText("Phantom Assassin")).toHaveCount(0);
});

test("hero page shows a pro build", async ({ page }) => {
  await page.goto("/heroes");
  await page.getByLabel("Поиск героя").fill("jugg");
  await page.getByRole("link", { name: "Juggernaut" }).click();
  await expect(page.getByRole("heading", { name: "Juggernaut", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Основные предметы в порядке сборки у про-игроков" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Порядок способностей" })).toBeVisible();
  await page.getByRole("tab", { name: "Матчапы" }).click();
  await expect(page.getByRole("heading", { name: "Слаб против" })).toBeVisible();
});

test("meta, items and setup load", async ({ page }) => {
  await page.goto("/meta");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  expect(await page.locator("tbody tr").count()).toBeGreaterThan(50);
  await page.goto("/items/black_king_bar");
  await expect(page.getByRole("heading", { name: "Black King Bar" })).toBeVisible();
  await page.goto("/setup");
  await expect(page.getByRole("heading", { name: "Подключение Dota 2" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Данные", exact: true })).toBeVisible();
});

test("settings switch the theme", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("group", { name: "Тема" }).getByRole("button", { name: "Светлая" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("group", { name: "Тема" }).getByRole("button", { name: "Тёмная" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("keyboard shortcuts switch pages", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("2");
  await expect(page).toHaveURL(/\/draft$/);
  await page.keyboard.press("5");
  await expect(page).toHaveURL(/\/meta$/);
});

test("compact view shows the Copilot's advice and labels the demo", async ({ page, request }) => {
  await request.post("/api/demo", { data: { hero: "juggernaut", speed: 8, minutes: 6 } });
  await page.goto("/compact");
  const copilot = page.getByRole("region", { name: "Copilot" });
  await expect(copilot).toContainText("Демо-матч, не ваша игра", { timeout: 20_000 });
  await expect(copilot.getByText("Основной предмет").first()).toBeVisible({ timeout: 30_000 });
  await request.post("/api/replay/stop"); // freeze the match so the advice stops changing
  await page.waitForTimeout(2_000);
  const before = await copilot.getByRole("article").count();
  await copilot.getByRole("button", { name: /^Скрыть совет/ }).first().click();
  await expect(copilot.getByRole("article")).toHaveCount(before - 1, { timeout: 10_000 });
  await request.post("/api/live/reset");
});

test("an overlay widget shows its hint, labels the demo and has no scrollbars", async ({ page, request }) => {
  await request.post("/api/demo", { data: { hero: "juggernaut", speed: 2, minutes: 3 } });
  await page.setViewportSize({ width: 320, height: 176 });
  await page.goto("/hud/items");
  await expect(page.getByText(/^Старт ·/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("демо")).toBeVisible();
  const clipped = await page.evaluate("getComputedStyle(document.documentElement).overflow");
  expect(clipped).toBe("hidden");
  await page.screenshot({ path: "test-results/hud-items.png" });
  await page.goto("/hud/draft");
  await expect(page.getByText("Подсказка: кого взять")).toBeVisible(); // no draft now: the placeholder he drags in setup
  await request.post("/api/live/reset");
});

test("the draft board sends his corrections to the Copilot during a match", async ({ page, request }) => {
  await request.post("/api/demo", { data: { hero: "juggernaut", speed: 1, minutes: 3 } });
  await page.goto("/draft");
  await expect(page.getByLabel("Пики Света").getByText("Juggernaut")).toBeVisible({ timeout: 20_000 });
  const draftSource = async () => (await (await request.get("/api/copilot/status")).json()).context.sources.draft;
  await page.waitForTimeout(1_000);
  expect(await draftSource()).not.toBe("manual"); // the game's own draft is not "his corrections"
  await expect(page.getByText("Чтение экрана драфта не запущено")).toBeVisible();
  const search = page.getByLabel("Поиск героя");
  await search.fill("lion");
  await search.press("Enter");
  await expect.poll(draftSource, { timeout: 10_000 }).toBe("manual");
  await request.post("/api/live/reset");
});

test("the review page explains what it compares and works with an empty journal", async ({ page }) => {
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Разбор матчей" })).toBeVisible();
  await expect(page.getByText("Пока нет игр в журнале")).toBeVisible();
  await page.keyboard.press("1");
  await expect(page).toHaveURL(/\/$/);
  await page.keyboard.press("0");
  await expect(page).toHaveURL(/\/review$/);
});
