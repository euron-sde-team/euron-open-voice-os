import { expect, test } from "@playwright/test";

import { asOwner, choose, watchConsole } from "../helpers";

/**
 * AC1: a person talks to an agent in the browser and hears it answer, over WebRTC and over
 * the WebSocket fallback. The fake microphone asks to book a table; the agent's reply comes
 * from the configured LLM and is spoken by the TTS provider.
 */
for (const transport of ["WebRTC", "WebSocket"] as const) {
  test(`talks to an agent over ${transport} and stores the session`, async ({ page }) => {
    const errors = watchConsole(page);
    await asOwner(page, "/talk");
    await expect(page.getByRole("heading", { name: "Talk" })).toBeVisible();
    if (process.env.E2E_AGENT) await choose(page, "talk-agent", new RegExp(process.env.E2E_AGENT));
    await expect(page.getByTestId("disclosure")).toBeVisible();
    await page.getByRole("radio", { name: transport }).click();

    await page.getByRole("button", { name: "Start talking" }).click();
    await expect(page.getByText(new RegExp(`\\u00b7 ${transport}$`))).toBeVisible({ timeout: 20_000 });

    const transcript = page.getByTestId("transcript");
    // The caller's words, recognized by the STT provider, then the agent's spoken answer:
    // "answered in" appears on an agent line once its first audio reached this browser.
    await expect(transcript.locator('[data-who="user"]').first()).toContainText(/book a table/i, { timeout: 45_000 });
    await expect(transcript.locator('[data-who="agent"]', { hasText: /answered in/ }).first()).toBeVisible({ timeout: 60_000 });

    await page.getByRole("button", { name: "End conversation" }).click();
    await expect(page.getByTestId("phase")).toHaveText(/ended/i);

    await page.getByRole("link", { name: "open this session" }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer).toContainText(/book a table/i, { timeout: 20_000 });
    await expect(drawer.getByTestId("waterfall").first()).toBeVisible();
    await expect(drawer).toContainText(transport);

    expect(errors.filter((e) => /Content Security Policy|Refused to connect/i.test(e))).toEqual([]);
  });
}
