import { expect, test } from "@playwright/test";

import { asOwner, RUN, talkOnce, watchConsole } from "../helpers";

/**
 * AC16: from the dashboard alone, create an agent from a template and talk to it. The
 * template picks the self-hosted providers, so no key or configuration is needed.
 */
test("create an agent from a template and talk to it in minutes", async ({ page }) => {
  const errors = watchConsole(page);
  await asOwner(page, "/agents");
  await page.getByRole("button", { name: "New agent" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: /Receptionist/ }).click();
  await dialog.locator("#agent-name").fill(`Clinic desk ${RUN}`);
  await dialog.getByRole("button", { name: "Create agent" }).click();

  await expect(page).toHaveURL(/\/agents\/[0-9a-f-]{36}$/);
  await expect(page.getByText(`Clinic desk ${RUN} is ready`)).toBeVisible();
  // Self-hosted by default: listening, thinking and speaking stay on this deployment.
  await expect(page.locator("#a-stt")).toContainText("Local Whisper");
  await expect(page.locator("#a-tts")).toContainText("Local Kokoro");
  const agentId = page.url().split("/").pop() ?? "";

  await talkOnce(page, agentId);
  await expect(page.getByTestId("disclosure")).toContainText("stay on this deployment");
  expect(errors.filter((e) => /Content Security Policy|Refused/i.test(e))).toEqual([]);
});
