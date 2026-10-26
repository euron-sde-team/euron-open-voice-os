/**
 * Browser QA (make qa): signs in through the real form, visits every dashboard page in
 * light and dark at desktop and phone width, saves screenshots, and fails on console
 * errors, failed or 4xx/5xx requests, broken images, error states and horizontal overflow.
 *
 *   make qa
 *   QA_BASE=http://localhost:4510 QA_OUT=./output node qa.mjs
 *   QA_PAGES=/,/sessions QA_THEMES=dark QA_SIZES=desktop node qa.mjs
 *
 * Uses Puppeteer's bundled Chromium; set CHROME_PATH to use a local browser instead.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.QA_BASE ?? "http://localhost:4510";
const OUT = process.env.QA_OUT ?? path.resolve("output");
const EMAIL = process.env.QA_EMAIL ?? "admin@voiceos.local";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.VOS_DEMO_PASSWORD ?? "";
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;

const ALL_PAGES = [
  "/login",
  "/",
  "/talk",
  "/agents",
  "/agents/:agent",
  "/providers",
  "/sessions",
  "/sessions?session=:session",
  "/benchmarks",
  "/keys",
  "/integrations",
  "/users",
  "/audit",
  "/settings",
];
const PAGES = process.env.QA_PAGES ? process.env.QA_PAGES.split(",") : ALL_PAGES;
const THEMES = (process.env.QA_THEMES ?? "light,dark").split(",");
const SIZES = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const SIZE_KEYS = (process.env.QA_SIZES ?? "desktop,phone").split(",");
const FULL = process.env.QA_FULL !== "0";

function slug(p) {
  return p === "/" ? "overview" : p.replace(/^\//, "").replace(/[/:?=]/g, "-");
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const problems = [];
  let ids = null;

  for (const theme of THEMES) {
    for (const sizeKey of SIZE_KEYS) {
      const ctx = await browser.createBrowserContext();
      const page = await ctx.newPage();
      await page.setViewport(SIZES[sizeKey]);
      await page.evaluateOnNewDocument((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, theme);
      const consoleErrors = [];
      page.on("console", (m) => {
        if (m.type() === "error") consoleErrors.push(m.text());
      });
      page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
      page.on("requestfailed", (r) => {
        const err = r.failure()?.errorText ?? "";
        if (!err.includes("ERR_ABORTED")) consoleErrors.push(`requestfailed ${r.url()} ${err}`);
      });
      page.on("response", (r) => {
        if (r.status() >= 400) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`);
      });

      // Sign in through the real form once per context.
      await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
      if (PAGES.includes("/login")) {
        await new Promise((r) => setTimeout(r, 400));
        await page.screenshot({ path: path.join(OUT, `${sizeKey}-${theme}-login.png`) });
      }
      await page.type("#email", EMAIL);
      await page.type("#password", PASSWORD);
      await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);

      if (!ids) {
        ids = await page.evaluate(async () => {
          const sessions = await (await fetch("/api/v1/sessions?limit=1")).json();
          const agents = await (await fetch("/api/v1/agents")).json();
          return { session: sessions.items?.[0]?.id ?? "missing", agent: agents?.[0]?.id ?? "missing" };
        });
      }

      for (const p of PAGES) {
        if (p === "/login") continue;
        const url = p.replace(":session", ids.session).replace(":agent", ids.agent);
        consoleErrors.length = 0;
        await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 45_000 });
        await new Promise((r) => setTimeout(r, 900));
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        const broken = await page.evaluate(() =>
          [...document.images].filter((img) => img.complete && img.naturalWidth === 0).map((img) => img.src),
        );
        // A healthy page with demo data renders no error states.
        const errorStates = await page.evaluate(() =>
          [...document.querySelectorAll("[data-qa='error-state']")].map((el) => el.textContent?.slice(0, 80) ?? ""),
        );
        const file = path.join(OUT, `${sizeKey}-${theme}-${slug(p)}.png`);
        await page.screenshot({ path: file, fullPage: FULL });
        const issues = [...consoleErrors];
        if (overflow > 1) issues.push(`horizontal overflow ${overflow}px`);
        for (const src of broken) issues.push(`broken image ${src}`);
        for (const text of errorStates) issues.push(`error state: ${text}`);
        if (issues.length) problems.push({ page: p, theme, size: sizeKey, issues });
        console.log(`${issues.length ? "WARN" : "ok  "} ${sizeKey} ${theme} ${p}${issues.length ? `: ${issues.join(" | ")}` : ""}`);
      }
      await ctx.close();
    }
  }
  await browser.close();
  console.log(`\n${problems.length} page(s) with problems. Screenshots in ${OUT}`);
  if (problems.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
