import { expect, type Page } from "@playwright/test";

export const OWNER = {
  email: process.env.E2E_EMAIL || "admin@voiceos.local",
  password: process.env.E2E_PASSWORD || process.env.VOS_DEMO_PASSWORD || "",
};

/** Mutations through the API add the CSRF header the dashboard sends. */
export const CSRF = { "x-voiceos-csrf": "1" };

/** A per-run suffix so suites can run repeatedly against the same demo database. */
export const RUN = process.env.E2E_RUN || Date.now().toString(36).slice(-5);

/** Open the dashboard with the shared owner session from global setup. */
export async function asOwner(page: Page, path = "/"): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}

/** Sign in through the real form (for auth tests and other users). */
export async function signIn(page: Page, email = OWNER.email, password = OWNER.password): Promise<void> {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

/** Pick an option in one of the dashboard's custom selects. */
export async function choose(page: Page, triggerId: string, option: string | RegExp): Promise<void> {
  await page.locator(`#${triggerId}`).click();
  await page.getByRole("option", { name: option }).first().click();
}

/** Fail the test on any console error or CSP violation the page reports. */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}
