/**
 * Curated README screenshots and tour frames from a freshly seeded stack.
 *
 *   make up && make demo
 *   cd scripts/qa && QA_BASE=http://localhost:4310 node screenshots.mjs
 *   ../../scripts/qa/make-tour.sh        (stitches the frames into docs/assets/tour.gif)
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:4310";
const EMAIL = process.env.QA_EMAIL ?? "admin@contextforge.local";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.CF_DEMO_PASSWORD ?? "ForgeDemo2026";
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const DESKTOP = { width: 1440, height: 900, deviceScaleFactor: 1 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tourIndex = 0;

async function settle(page, ms = 1200) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 20_000 }).catch(() => {});
  await sleep(ms);
}

async function shot(page, name, { tour = true, fullPage = false } = {}) {
  await page.evaluate(() => window.scrollTo(0, 0));
  // Park the pointer in an empty corner so no hover tooltip leaks into a capture.
  await page.mouse.move(1, 1);
  await sleep(250);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
  if (tour) await page.screenshot({ path: path.join(TOUR, `${String(++tourIndex).padStart(2, "0")}.png`) });
  console.log(`saved ${name}`);
}

async function choose(page, triggerId, label) {
  await page.click(`#${triggerId}`);
  await sleep(200);
  const options = await page.$$('[role="option"]');
  for (const o of options) {
    const text = (await o.evaluate((el) => el.textContent)) ?? "";
    if (text.trim().startsWith(label)) {
      await o.click();
      await sleep(200);
      return;
    }
  }
  throw new Error(`option ${label} not found in #${triggerId}`);
}

async function clickButton(page, text, { exact = false } = {}) {
  const buttons = await page.$$("button");
  for (const b of buttons) {
    const t = ((await b.evaluate((el) => el.textContent)) ?? "").trim();
    if (exact ? t === text : t.includes(text)) {
      await b.click();
      return;
    }
  }
  throw new Error(`button ${text} not found`);
}

async function optimizeSample(page, label) {
  await page.goto(`${BASE}/playground`, { waitUntil: "networkidle2" });
  await settle(page);
  await choose(page, "sample", label);
  await settle(page, 800);
  await clickButton(page, "Optimize", { exact: true });
  await page.waitForSelector("[aria-live=polite]", { timeout: 20_000 });
  await settle(page, 900);
}

async function main() {
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport(DESKTOP);
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "light");
    } catch {}
  });

  await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
  await sleep(600);
  await shot(page, "00-sign-in", { tour: false });
  await page.type("#email", EMAIL);
  await page.type("#password", PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);

  await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
  await settle(page, 1800);
  await shot(page, "01-overview");

  // A coding agent stuck on a failing test: before and after, side by side.
  await optimizeSample(page, "Coding agent, 8 attempts");
  await shot(page, "02-playground-coding");

  // The pipeline trace of the same run.
  await clickButton(page, "Trace", { exact: true });
  await settle(page, 500);
  await shot(page, "03-playground-trace");

  // A noisy retrieval: duplicates merged, noise dropped, every citation mapped.
  await optimizeSample(page, "RAG, 108 retrieved chunks");
  await clickButton(page, "Documents", { exact: true });
  await settle(page, 500);
  await shot(page, "04-playground-citations");

  await page.goto(`${BASE}/runs`, { waitUntil: "networkidle2" });
  await settle(page);
  await shot(page, "05-runs");

  await page.click("table tbody tr");
  await settle(page, 1000);
  await shot(page, "06-run-detail");

  await page.goto(`${BASE}/benchmarks`, { waitUntil: "networkidle2" });
  await settle(page, 1500);
  await shot(page, "07-benchmarks");

  await page.goto(`${BASE}/profiles`, { waitUntil: "networkidle2" });
  await settle(page);
  await shot(page, "08-profiles");

  await page.goto(`${BASE}/upstreams`, { waitUntil: "networkidle2" });
  await settle(page);
  await shot(page, "09-upstreams");

  await page.goto(`${BASE}/integrations`, { waitUntil: "networkidle2" });
  await settle(page);
  await shot(page, "10-integrations");

  await page.goto(`${BASE}/jobs`, { waitUntil: "networkidle2" });
  await settle(page);
  await shot(page, "11-jobs", { tour: false });

  // Dark mode: a second page in the same signed-in context, so its init script sets dark.
  const dark = await ctx.newPage();
  await dark.setViewport(DESKTOP);
  await dark.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "dark");
    } catch {}
  });
  await optimizeSample(dark, "Support thread, 166 messages");
  await shot(dark, "12-dark-mode");

  // Phone width.
  const phone = await ctx.newPage();
  await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await phone.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "light");
    } catch {}
  });
  await phone.goto(`${BASE}/`, { waitUntil: "networkidle2" });
  await settle(phone, 1800);
  await phone.screenshot({ path: path.join(SHOTS, "13-mobile.png") });
  console.log("saved 13-mobile");

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
