// The site checks' shared helpers (media/site-checks/README.md): open the site in a browser like a visitor would, read
// its state in one compact line, record checks, and act on the page. Local only: never run in GitHub Actions.
//
// Reused from tools/capture.mjs: the frozen clock (page.clock), Bogotá's zone and es-CO, the first-visit flags preset,
// analytics blocked. Here every third party is blocked except Google Fonts (they change the layout).
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { chromium, devices, webkit } from "playwright-core";

export const LOCAL = "http://localhost:4322/";
export const LIVE = "https://pa-bailar.github.io/";
export const SHOTS = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "out", "site-checks", "shots");
export const STEP_TIMEOUT = 8000;

/** The devices: a desktop window, an Android phone at 375 px, and an iPhone (Safari's settings, at 375 px). */
export const DEVICES = {
  desktop: { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 },
  phone: {
    viewport: { width: 375, height: 812 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    userAgent:
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  },
  iphone: (({ defaultBrowserType, ...d }) => d)(devices["iPhone SE (3rd gen)"]),
};
export const ENGINES = {
  chrome: () => chromium.launch({ channel: "chrome", headless: true }),
  webkit: () => webkit.launch(),
};

const ALLOWED_THIRD_PARTIES = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;
const pageInfo = new WeakMap(); // page → { touch, base }

/**
 * A browser on the site. `now` freezes the clock (an ISO date); `fresh` leaves the first-visit flags unset (the
 * details hint, the install offer). Returns `{ browser, context, page, errors, close }`; `errors` collects page
 * errors, console errors and failed same-site requests, as short strings.
 */
export async function open({
  engine = "chrome",
  device = "desktop",
  theme = "light",
  base = LOCAL,
  now,
  fresh = false,
} = {}) {
  if (!ENGINES[engine]) throw new Error(`unknown engine ${engine} (chrome, webkit)`);
  if (!DEVICES[device]) throw new Error(`unknown device ${device} (${Object.keys(DEVICES).join(", ")})`);
  const browser = await ENGINES[engine]();
  const context = await browser.newContext({
    ...DEVICES[device],
    colorScheme: theme,
    locale: "es-CO",
    timezoneId: "America/Bogota",
  });
  const origin = new URL(base).origin;
  const blocked = new Set();
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (url.startsWith(origin) || url.startsWith("data:") || url.startsWith("blob:") || ALLOWED_THIRD_PARTIES.test(url))
      return route.continue();
    blocked.add(url);
    return route.abort("blockedbyclient");
  });
  await context.addInitScript(
    ({ theme, fresh }) => {
      try {
        localStorage.setItem("theme", theme);
        if (!fresh) {
          localStorage.setItem("details-hint-seen", "1"); // the first card's Detalles would pulse (views/detailsHint.ts)
          localStorage.setItem("install-dismissed-at", String(Date.now()));
        }
      } catch {}
    },
    { theme, fresh },
  );
  const page = await context.newPage();
  page.setDefaultTimeout(STEP_TIMEOUT);
  page.setDefaultNavigationTimeout(STEP_TIMEOUT * 2);
  if (now) await page.clock.setFixedTime(new Date(now));
  pageInfo.set(page, { touch: Boolean(DEVICES[device].hasTouch), base });

  const errors = [];
  const add = (e) => {
    const short = e.replace(/\s+/g, " ").slice(0, 200);
    if (!errors.includes(short)) errors.push(short);
  };
  page.on("pageerror", (e) => add(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    // Playwright's screenshots inject a style (hiding the caret) that the site's CSP refuses: not the site's.
    if (/^Refused to apply a stylesheet/.test(text) && Date.now() - (pageInfo.get(page)?.shotAt ?? 0) < 3000) return;
    if (/^Failed to load resource/.test(text)) return; // reported by the response below, with its URL
    if (/Blocked by Web Inspector|ERR_BLOCKED_BY_CLIENT/.test(text)) return; // a third party blocked here (analytics)
    add(`console: ${text}`);
  });
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText ?? "";
    // a load the page itself cancelled (a clip or an image dropped as the view changes) isn't a failure
    if (/ERR_ABORTED|cancelled/i.test(why)) return;
    if (r.url().startsWith(origin) && !blocked.has(r.url())) add(`failed: ${why} ${r.url().slice(origin.length)}`);
  });
  page.on("response", (r) => {
    if (r.url().startsWith(origin) && r.status() >= 400) add(`http ${r.status()}: ${r.url().slice(origin.length)}`);
  });
  return { browser, context, page, errors, blocked, close: () => browser.close().catch(() => {}) };
}

/** Whether the page was opened on a touch device (the phone, the iPhone). */
export const isTouch = (page) => Boolean(pageInfo.get(page)?.touch);

/** A path of the site (or a full URL), loaded, settled. */
export async function goto(page, where = "/") {
  // Git Bash turns an argument like /calendario/ into C:/Program Files/Git/calendario/: undo it
  const path = where.replace(/^[A-Za-z]:[\\/].*?[\\/]Git([\\/].*)$/, "$1").replaceAll("\\", "/");
  const url = new URL(path, pageInfo.get(page)?.base ?? LOCAL).href;
  await page.goto(url, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await waitSettled(page);
}

/**
 * Wait until the page is still: no finite animation running and the scroll unchanged for three checks, at most `max`
 * ms. Cheaper and steadier than fixed waits.
 */
export async function waitSettled(page, max = 2000) {
  const end = Date.now() + max;
  let same = 0;
  let last = null;
  await page.waitForTimeout(60);
  while (Date.now() < end) {
    const now = await page
      .evaluate(() => {
        const running = document
          .getAnimations()
          .filter((a) => a.playState === "running" && a.effect?.getTiming().iterations !== Infinity).length;
        return `${running}|${Math.round(scrollY)}|${location.href}`;
      })
      .catch(() => "navigating");
    same = now === last && now.startsWith("0|") ? same + 1 : 0;
    if (same >= 2) return;
    last = now;
    await page.waitForTimeout(50);
  }
}

/** Tap on a touch device, click otherwise. `target` is a Locator or a selector. */
export async function tapOrClick(page, target) {
  const loc = typeof target === "string" ? page.locator(target).first() : target;
  if (isTouch(page)) await loc.tap();
  else await loc.click();
  await waitSettled(page);
}

/** Press a key `n` times, letting the page settle after each. */
export async function key(page, k, n = 1) {
  for (let i = 0; i < n; i++) {
    await page.keyboard.press(k);
    await waitSettled(page);
  }
}

/** Back or forward in the history, settled. */
export async function back(page) {
  await page.goBack({ waitUntil: "commit" }).catch(() => {});
  await waitSettled(page);
}
export async function forward(page) {
  await page.goForward({ waitUntil: "commit" }).catch(() => {});
  await waitSettled(page);
}

/** The visible view's cards (Locator). */
export const cards = (page) => page.locator('[role="tabpanel"]:not([hidden]) [data-event-card]');

/**
 * The page's state in one compact object: what a check usually needs. Falsy parts are left out of `fmt()`.
 *   url, y (scrollY), focus ("card:<id>", "#id", "[Ver 7 más]" or a tag), drawer (its event id, or ""), stage ("2/5"
 *   when the image stage is open), open (other open dialogs' ids), screen (body data-screen), folded (the periods
 *   still summarized in the visible view), ox (horizontal overflow, px)
 */
export const snapshot = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    const card = a?.closest?.("[data-event-card]")?.dataset.eventCard;
    const focus = a?.dataset?.showPeriod
      ? `[${a.dataset.showPeriod}: ${a.textContent.trim().replace(/\s+/g, " ")}]`
      : card
        ? `card:${card}`
        : a?.id
          ? `#${a.id}`
          : (a?.tagName?.toLowerCase() ?? "");
    const drawerOpen = Boolean(document.querySelector("#event-drawer[open]"));
    const fromPath = decodeURIComponent(location.pathname).match(/^\/evento\/([^/]+)/)?.[1];
    const stage = document.getElementById("lightbox");
    return {
      url: location.pathname + location.search,
      y: Math.round(scrollY),
      focus,
      drawer: drawerOpen ? (fromPath ?? "?") : "",
      stage: stage?.open ? document.getElementById("lightbox-count")?.textContent?.trim() || "open" : "",
      open: [...document.querySelectorAll("dialog[open]")]
        .map((d) => d.id || d.className.toString().split(" ")[0] || "dialog")
        .filter((id) => id !== "event-drawer" && id !== "lightbox"),
      screen: document.body.dataset.screen ?? "",
      folded: [...document.querySelectorAll('[role="tabpanel"]:not([hidden]) [data-show-period]')].map(
        (b) => b.dataset.showPeriod,
      ),
      ox: Math.max(0, document.documentElement.scrollWidth - innerWidth),
    };
  });

const cut = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
/** A snapshot as one short line. */
export function fmt(s) {
  const parts = [s.url, `y=${s.y}`];
  if (s.focus) parts.push(`focus=${cut(s.focus, 28)}`);
  if (s.drawer) parts.push(`drawer=${cut(s.drawer, 28)}`);
  if (s.stage) parts.push(`stage=${s.stage}`);
  if (s.open?.length) parts.push(`open=${s.open.join(",")}`);
  if (s.screen) parts.push(`screen=${s.screen}`);
  if (s.folded?.length) parts.push(`folded=${s.folded.length}`);
  if (s.ox) parts.push(`OVERFLOW=${s.ox}px`);
  return parts.join(" ");
}

/** A screenshot into out/site-checks/shots/<name>.png (the caret left alone: the hiding style breaks the CSP). */
export async function shot(page, name) {
  await mkdir(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${name.replace(/[^\w.-]+/g, "-")}.png`);
  const info = pageInfo.get(page);
  if (info) info.shotAt = Date.now();
  await page.screenshot({ path: file, caret: "initial" });
  if (info) info.shotAt = Date.now();
  return file;
}

/**
 * The command line shared by run.mjs and probe.mjs: --live, --url <u>, --engine a,b, --device a,b, --theme a,b,
 * --now <iso>, --shots, --verbose, --fresh, and `extra` options (node:util parseArgs' format).
 */
export function cli(extra = {}) {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      live: { type: "boolean" },
      url: { type: "string" },
      engine: { type: "string" },
      device: { type: "string" },
      theme: { type: "string" },
      now: { type: "string" },
      shots: { type: "boolean" },
      verbose: { type: "boolean", short: "v" },
      fresh: { type: "boolean" },
      help: { type: "boolean", short: "h" },
      ...extra,
    },
  });
  const list = (v) =>
    v
      ? v
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : undefined;
  return {
    ...values,
    base: values.url ?? (values.live ? LIVE : LOCAL),
    engines: list(values.engine),
    devices: list(values.device),
    themes: list(values.theme),
    positionals,
  };
}

// ---------- the record: checks, skips and the step log of one run ----------

let active; // the latest recorder
const text = (v) => (typeof v === "string" ? v : v && "url" in v && "y" in v ? fmt(v) : JSON.stringify(v));

/**
 * A run's record and its functions, bound to it (a scenario stopped by the timeout can't write into the next run's).
 * `echo` prints each step as it happens (--verbose, probe). The module's `check`, `skip` and `log` use the latest one.
 */
export function recorder({ echo = false } = {}) {
  const result = { checks: 0, fails: [], skips: [], logs: [] };
  const r = {
    result,
    /** One step's line, truncated: kept for --verbose. */
    log(label, value = "") {
      const line = cut(`  ${label.padEnd(26)} ${text(value)}`, 170);
      result.logs.push(line);
      if (echo) console.log(line);
    },
    /** PASS when `condition` is truthy; a FAIL records `details` (a string, a snapshot or a value). */
    check(label, condition, details = "") {
      result.checks++;
      const detail = condition ? "" : text(details);
      if (!condition) result.fails.push(`${label}${detail ? `: ${cut(detail, 240)}` : ""}`);
      r.log(`${condition ? "PASS" : "FAIL"} ${label}`, detail);
      return Boolean(condition);
    },
    /** A part that today's data can't exercise (no carousel, no folded period…): not a failure. */
    skip(label, reason) {
      result.skips.push(`${label}: ${reason}`);
      r.log(`SKIP ${label}`, reason);
    },
  };
  active = r;
  return r;
}
active = recorder({ echo: true });
export const log = (label, value) => active.log(label, value);
export const check = (label, condition, details) => active.check(label, condition, details);
export const skip = (label, reason) => active.skip(label, reason);

/** Thrown to skip a whole scenario on this device or engine (e.g. the side panel on a phone). */
export class Skip extends Error {}
