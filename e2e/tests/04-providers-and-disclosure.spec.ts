import { expect, test } from "@playwright/test";

import { agentFromTemplate, asOwner, choose, RUN, talkOnce } from "../helpers";

/**
 * AC4 and AC6: add a provider, switch an agent to it from the editor (configuration only),
 * and see the external processing disclosed before the call and recorded after it.
 */
test("switching an agent to an external provider is disclosed and recorded", async ({ page }) => {
  const providerName = `Hosted LLM ${RUN}`;
  await asOwner(page, "/providers");
  await page.getByRole("button", { name: "Add provider" }).click();
  const dialog = page.getByRole("dialog");
  await choose(page, "p-stage", "Language model");
  await dialog.locator("#p-name").fill(providerName);
  await dialog.locator("#p-url").fill("http://mock-providers:4550/v1");
  await dialog.locator("#p-model").fill("mock-llm");
  await dialog.locator("#p-price").fill("0.15");
  await dialog.locator("#p-price2").fill("0.6");
  await dialog.getByRole("switch", { name: "Treat as external" }).click();
  await dialog.getByRole("button", { name: "Add provider" }).click();
  await expect(page.getByText("Provider added.")).toBeVisible();

  const row = page.getByTestId("provider-row").filter({ hasText: providerName });
  await row.getByRole("button", { name: `Test ${providerName}` }).click();
  await expect(page.getByText(new RegExp(`${providerName}: `))).toBeVisible();

  const agentId = await agentFromTemplate(page, "support", `Support ${RUN}`);
  await page.goto(`/agents/${agentId}`);
  await choose(page, "a-llm", providerName);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/is now version 2/)).toBeVisible();

  await page.goto(`/talk?agent=${agentId}`);
  await expect(page.getByTestId("disclosure")).toContainText(providerName);
  await talkOnce(page, agentId);

  await page.getByRole("link", { name: "open this session" }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText(`Sent to ${providerName}`, { timeout: 20_000 });
  await expect(drawer).toContainText("Cost by stage");
  await expect(drawer).toContainText("Self-hosted");
});
