import { expect, test } from "@playwright/test";

import { agentFromTemplate, asOwner, RUN } from "../helpers";

/** AC13: an SDK key scoped to one agent and one website starts sessions from a backend. */
test("an SDK key is shown once and only starts its agent from its origin", async ({ page }) => {
  const agentId = await agentFromTemplate(page, "tutor", `Tutor ${RUN}`);
  const other = await agentFromTemplate(page, "meeting", `Meeting ${RUN}`);
  await asOwner(page, "/keys");
  await page.getByRole("button", { name: "New key" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#key-name").fill(`widget-${RUN}`);
  await dialog.getByRole("button", { name: `Tutor ${RUN}` }).click();
  await dialog.locator("#key-origins").fill("https://app.example.com");
  await dialog.getByRole("button", { name: "Create key" }).click();
  const key = (await page.getByTestId("new-key").textContent())?.trim() ?? "";
  expect(key).toMatch(/^vos_/);
  await page.getByRole("button", { name: "I have copied the key" }).click();
  await expect(page.locator("tr", { hasText: `widget-${RUN}` })).toContainText(`Tutor ${RUN}`);

  const start = (agent: string, origin?: string) =>
    page.request.post("/v1/sessions", {
      data: { agent_id: agent },
      headers: { authorization: `Bearer ${key}`, ...(origin ? { origin } : {}) },
    });
  const ok = await start(agentId, "https://app.example.com");
  expect(ok.status()).toBe(201);
  const ticket = (await ok.json()) as { websocket_url: string; disclosure: { message: string } };
  expect(ticket.websocket_url).toContain("/ws?token=");
  expect(ticket.disclosure.message).toBeTruthy();
  expect((await start(agentId, "https://evil.example")).status()).toBe(403);
  expect((await start(other, "https://app.example.com")).status()).toBe(403);

  await page.goto("/integrations");
  await expect(page.getByText("Ask for a session ticket")).toBeVisible();
  await expect(page.getByText("webrtcRequestParams").first()).toBeVisible();
});

test("settings show the runtime and the providers in use", async ({ page }) => {
  await asOwner(page, "/settings");
  await expect(page.getByText("Voice runtime")).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();
  await expect(page.getByText(/\d+ STT, \d+ LLM, \d+ TTS/)).toBeVisible();
});
