import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const BANNER = "Simulated campaign — no real learner or tutor";
const HALTED = "22222222-2222-4222-8222-222222222222";

test.beforeEach(() => {
  test.skip(
    process.env.TUTOR_MODE !== "simulation",
    "Run with TUTOR_MODE=simulation so the API mode is simulation.",
  );
});

test("axe passes on the banner and it is not colour alone", async ({
  page,
}) => {
  for (const path of ["/", "/simulation", `/sessions/${HALTED}`]) {
    await page.goto(path);
    const banner = page.getByRole("status");
    await expect(banner).toHaveText(BANNER);
    await expect(banner).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const blocking = results.violations.filter(
      (violation) =>
        violation.impact === "serious" || violation.impact === "critical",
    );
    expect(blocking).toEqual([]);
  }
});
