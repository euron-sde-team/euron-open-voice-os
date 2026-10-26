import { expect, test } from "@playwright/test";

import { asOwner, talkOnce, watchConsole } from "../helpers";

/** AC8 and AC9 on screen: the month of measured history, per-turn waterfalls, cost and erasure. */
test("the overview shows measured latency and cost", async ({ page }) => {
  const errors = watchConsole(page);
  await asOwner(page, "/");
  const main = page.locator("#main");
  for (const label of ["Response, median", "Sessions", "Cost (est.)", "Saved by caches"]) {
    await expect(main.getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Where the time goes" })).toBeVisible();
  await expect(main.getByText("LLM first token").first()).toBeVisible();
  await expect(page.getByRole("img", { name: /Sessions and average response time/ })).toBeVisible();
  await page.getByRole("radio", { name: "7d" }).click();
  await expect(page.getByRole("heading", { name: "By agent" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("a session opens with its turns, waterfall and cost, and its words can be erased", async ({ page }) => {
  // A conversation of our own, so the session under test is known to have an answer.
  await asOwner(page, "/agents");
  const agent = page.getByTestId("agent-card").filter({ hasText: "Front desk" }).first();
  const href = await agent.getByRole("link", { name: "Front desk" }).getAttribute("href");
  await talkOnce(page, href?.split("/").pop() ?? "");
  await page.getByRole("link", { name: "open this session" }).click();
  const drawer = page.getByRole("dialog").filter({ hasText: "Cost by stage" });
  await expect(drawer.getByTestId("waterfall").first()).toBeVisible();
  await expect(drawer).toContainText("Cost by stage");
  await expect(drawer).toContainText("Caller:");

  await drawer.getByRole("button", { name: "Erase transcript" }).click();
  await page.getByRole("dialog").filter({ hasText: "Erase this transcript?" }).getByRole("button", { name: "Erase transcript" }).click();
  await expect(page.getByText("Transcript erased.")).toBeVisible();
  await expect(drawer).toContainText("Words not kept");
  await expect(drawer.getByTestId("waterfall").first()).toBeVisible();
});
