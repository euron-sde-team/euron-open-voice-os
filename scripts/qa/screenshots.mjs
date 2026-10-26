/**
 * Curated README screenshots and tour frames from a freshly seeded stack.
 *
 *   make up && make demo
 *   cd scripts/qa && node screenshots.mjs
 *   ../../scripts/qa/make-tour.sh        (stitches the frames into docs/assets/tour.gif)
 *
 * The Talk captures are a real conversation: Chromium's fake microphone plays the
 * committed question (e2e/audio/en-booking.wav) and the agent answers through the stack.
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:4510";
const EMAIL = process.env.QA_EMAIL ?? "admin@voiceos.local";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.VOS_DEMO_PASSWORD ?? "";
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const MIC = path.resolve(HERE, "../../e2e/audio/en-booking.wav");
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

async function open(page, url, ms = 1500) {
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 45_000 });
  await settle(page, ms);
}

async function clickButton(page, text) {
  const buttons = await page.$$("button");
  for (const b of buttons) {
    const t = ((await b.evaluate((el) => el.textContent)) ?? "").trim();
    if (t.includes(text)) {
      await b.click();
      return;
    }
  }
  throw new Error(`button ${text} not found`);
}

async function waitForText(page, selector, pattern, timeout = 90_000) {
  await page.waitForFunction(
    (sel, src) => [...document.querySelectorAll(sel)].some((el) => new RegExp(src).test(el.textContent ?? "")),
    { timeout, polling: 500 },
    selector,
    pattern,
  );
}

async function main() {
  if (!PASSWORD) throw new Error("set QA_PASSWORD or VOS_DEMO_PASSWORD (the demo password in deploy/compose/.env)");
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: [
      "--no-sandbox",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${MIC}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const ctx = await browser.createBrowserContext();
  await ctx.overridePermissions(BASE, ["microphone"]);
  const page = await ctx.newPage();
  await page.setViewport(DESKTOP);
  await page.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "light");
    } catch {}
  });

  await open(page, "/login", 800);
  await shot(page, "14-login", { tour: false });
  await page.type("#email", EMAIL);
  await page.type("#password", PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);

  const agents = await page.evaluate(async () => (await (await fetch("/api/v1/agents")).json()) ?? []);
  const frontDesk = agents.find((a) => a.name === "Front desk") ?? agents[0];

  await open(page, "/", 2500);
  await shot(page, "01-overview");

  // A live conversation, captured while the agent answers.
  await open(page, `/talk?agent=${frontDesk.id}`);
  await clickButton(page, "WebSocket");
  await clickButton(page, "Start talking");
  await waitForText(page, '[data-who="agent"]', "answered in");
  await sleep(600);
  await shot(page, "02-talk");
  await clickButton(page, "End conversation");
  await sleep(4000);

  const latest = await page.evaluate(async () => (await (await fetch("/api/v1/sessions?limit=1")).json()).items?.[0]?.id);
  await open(page, `/sessions?session=${latest}`, 2500);
  await shot(page, "03-session-detail");

  await open(page, "/sessions");
  await shot(page, "04-sessions");

  await open(page, "/agents");
  await shot(page, "05-agents");

  await clickButton(page, "New agent");
  await sleep(900);
  await shot(page, "06-new-agent", { tour: true });
  await page.keyboard.press("Escape");
  await sleep(400);

  await open(page, `/agents/${frontDesk.id}`);
  await shot(page, "07-agent-editor");

  await open(page, "/providers");
  await shot(page, "08-providers");

  await open(page, "/benchmarks", 2000);
  await shot(page, "09-benchmarks");

  await open(page, "/integrations");
  await shot(page, "10-integrations");

  await open(page, "/keys");
  await shot(page, "11-keys", { tour: false });

  // Dark mode: a second page in the same signed-in context, so its init script sets dark.
  const dark = await ctx.newPage();
  await dark.setViewport(DESKTOP);
  await dark.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "dark");
    } catch {}
  });
  await open(dark, `/sessions?session=${latest}`, 2500);
  await shot(dark, "12-dark-mode");

  // Phone width.
  const phone = await ctx.newPage();
  await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await phone.evaluateOnNewDocument(() => {
    try {
      localStorage.setItem("theme", "light");
    } catch {}
  });
  await open(phone, "/", 2500);
  await phone.screenshot({ path: path.join(SHOTS, "13-mobile.png") });
  console.log("saved 13-mobile");

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
