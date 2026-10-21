import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const COMPLETED = "11111111-1111-4111-8111-111111111111";
const HALTED = "22222222-2222-4222-8222-222222222222";
const REFUSED = "33333333-3333-4333-8333-333333333333";
const REFUSED_TURN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

async function expectNoSeriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter(
    (violation) =>
      violation.impact === "serious" || violation.impact === "critical",
  );
  expect(blocking).toEqual([]);
}

test("axe passes on every tutor route", async ({ page }) => {
  for (const path of [
    "/",
    `/sessions/${COMPLETED}`,
    `/sessions/${HALTED}`,
    `/sessions/${REFUSED}`,
    `/audit/${REFUSED_TURN}`,
  ]) {
    await page.goto(path);
    await expectNoSeriousViolations(page);
  }
});

test("gate state stays readable when colour is removed", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto(`/sessions/${HALTED}`);
  await expect(page.getByText("Checked and fired (stop)")).toBeVisible();
  await expect(page.getByText("Not reached").first()).toBeVisible();
  await expect(page.getByText("Open", { exact: true })).toBeVisible();
});

test("the sessions link shows a focus outline", async ({ page }) => {
  await page.goto(`/sessions/${COMPLETED}`);
  const link = page.getByRole("link", { name: "Sessions", exact: true });
  await link.focus();
  const width = await link.evaluate(
    (element) => getComputedStyle(element).outlineWidth,
  );
  expect(width).not.toBe("0px");
});
