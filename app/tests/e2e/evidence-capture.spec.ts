import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const COMPLETED = "11111111-1111-4111-8111-111111111111";
const HALTED = "22222222-2222-4222-8222-222222222222";
const REFUSED = "33333333-3333-4333-8333-333333333333";
const COMPLETED_TURN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const directory = path.resolve(
  import.meta.dirname,
  "../../../evidence/article-14",
);

const captures = [
  { name: "sessions.png", route: "/" },
  { name: "turn-completed.png", route: `/sessions/${COMPLETED}` },
  { name: "turn-halted.png", route: `/sessions/${HALTED}` },
  { name: "turn-refused.png", route: `/sessions/${REFUSED}` },
  { name: "audit-completed.png", route: `/audit/${COMPLETED_TURN}` },
];

test.beforeEach(() => {
  test.skip(
    process.env.CAPTURE_EVIDENCE !== "1",
    "Regenerate with pnpm evidence:screenshots.",
  );
});

test("captures Article 14 screenshots of redacted fixture turns", async ({
  page,
}) => {
  await mkdir(directory, { recursive: true });
  for (const capture of captures) {
    await page.goto(capture.route);
    await expect(page.locator("body")).toBeVisible();
    await assertRedacted(page);
    await page.screenshot({
      path: path.join(directory, capture.name),
      fullPage: true,
    });
  }
  await writeFile(
    path.join(directory, "manifest.json"),
    `${JSON.stringify(
      {
        version: "policy-1",
        redaction:
          "Fixture prompts are already redacted. These captures contain no unredacted learner text.",
        screenshots: captures.map((capture) => capture.name),
      },
      null,
      2,
    )}\n`,
  );
});

async function assertRedacted(page: Page) {
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  expect(text).not.toMatch(/\b\d{1,5}\s+[A-Za-z]+\s+(Street|Avenue|Road)\b/);
}
