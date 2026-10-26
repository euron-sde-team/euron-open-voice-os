import { expect, test } from "@playwright/test";

import { asOwner } from "../helpers";

/** AC8 and AC14: a latency benchmark holds real conversations and reports each stage. */
test("a benchmark runs real conversations and reports stage latency", async ({ page }) => {
  test.setTimeout(6 * 60_000);
  await asOwner(page, "/benchmarks");
  await page.getByRole("button", { name: "Run benchmark" }).click();
  const dialog = page.getByRole("dialog");
  // Keep exactly one agent selected, the English front desk.
  const pressed = dialog.getByRole("button", { pressed: true });
  while ((await pressed.count()) > 0) await pressed.first().click();
  await dialog.getByRole("button", { name: /^Front desk/ }).click();
  await page.locator("#bench-sessions").click();
  await page.getByRole("option", { name: "3", exact: true }).click();
  await dialog.getByRole("button", { name: "Run benchmark" }).click();
  await expect(page.getByText(/Benchmark queued/)).toBeVisible();
  await expect(page.getByTestId("bench-agent").first()).toBeVisible({ timeout: 5 * 60_000 });
  await expect(page.getByTestId("bench-agent").first()).toContainText("Median");
  await expect(page.getByText(/Measured on/)).toBeVisible();
});
