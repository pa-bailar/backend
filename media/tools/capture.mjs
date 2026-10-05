// Screens of the LIVE site (https://pa-bailar.github.io/) on a phone, for videos: a library and a one-shot CLI.
//
//   node media/tools/capture.mjs <video> <name> [--path /evento/<id>/] [--now 2026-10-10T19:00:00-05:00]
//        [--theme light|dark] [--full] [--scroll <css px>] [--click <selector>] [--wait <ms>]
//   → public/<video>/screens/<name>.png (1080×1920, or the whole page with --full) and its entry in
//     projects/<video>/data/screens.json (path, clock, theme, page height)
//
// The phone: 360×640 CSS px at device scale 3 (= 1080×1920), es-CO, Bogotá time, the install banner and the swipe
// hint already dismissed, analytics blocked, the theme forced through the site's own localStorage key. The clock is
// frozen at --now (default: the coming Saturday, 7 p. m. Bogotá) so "Hoy" and "Este fin de semana" are full of real
// events; a video showing those dates has a shelf life: post it before that day is over.
//
// A video with a scripted walk through the site (menus, scrolls, the details sheet) writes its own capture script
// that imports these helpers: projects/teaser-v2/capture.mjs is the example. Read the page through stable hooks
// (ids, data attributes, visible text) so a capture survives design changes; when the site changes, fix the hooks
// here and in the video's script.
//
// playwright-core (a dev dependency here) drives the installed Chrome (its "chrome" channel: no path to keep).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const SITE = "https://pa-bailar.github.io/";

/** `--name value` from the command line, or `fallback`. */
export const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
export const flag = (name) => process.argv.includes(`--${name}`);

/** The command line's positional arguments: everything but the flags and the values of those that take one. */
export function positionals(withValue) {
  const out = [];
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith("--")) i += withValue.includes(args[i].slice(2)) ? 1 : 0;
    else out.push(args[i]);
  }
  return out;
}

/** The coming Saturday at 19:00 Bogotá (UTC−5, no DST); today if it's Saturday before 19:00. */
export function comingSaturday() {
  const bogota = new Date(Date.now() - 5 * 3600e3); // wall clock in Bogotá, read with UTC getters
  let days = (6 - bogota.getUTCDay() + 7) % 7;
  if (days === 0 && bogota.getUTCHours() >= 19) days = 7;
  const d = new Date(Date.UTC(bogota.getUTCFullYear(), bogota.getUTCMonth(), bogota.getUTCDate() + days));
  return `${d.toISOString().slice(0, 10)}T19:00:00-05:00`;
}

/** A phone with the site's state preset and the clock frozen at `now`. Close `browser` when done. */
export async function openPhone({ now = comingSaturday(), theme = "light" } = {}) {
  const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--hide-scrollbars"] });
  const context = await browser.newContext({
    viewport: { width: 360, height: 640 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    colorScheme: theme,
    locale: "es-CO",
    timezoneId: "America/Bogota",
    userAgent:
      "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  });
  await context.route(/goatcounter/, (route) => route.abort());
  await context.addInitScript((t) => {
    localStorage.setItem("theme", t);
    localStorage.setItem("install-dismissed-at", String(Date.now()));
    localStorage.setItem("details-hint-seen", "1"); // the first card's Detalles would pulse (views/detailsHint.ts)
  }, theme);
  const page = await context.newPage();
  await page.clock.setFixedTime(new Date(now));
  return { browser, context, page, now, theme };
}

export const wait = (page, ms) => page.waitForTimeout(ms);

/** Open a page of the site (cache-busted: GitHub Pages caches ~10 min), fonts loaded, the theme checked. */
export async function openSite(page, pagePath = "/", theme = "light") {
  const url = new URL(pagePath, SITE);
  url.searchParams.set("v", String(Date.now()));
  await page.goto(url.href, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await wait(page, 900);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const sum = bg.match(/\d+/g).slice(0, 3).map(Number).reduce((a, b) => a + b, 0);
  if ((theme === "light") !== sum >= 450) throw new Error(`not the ${theme} theme (body ${bg})`);
}

/** A locator's rect in page CSS px (y includes the scroll). */
export const rectOf = (handle) =>
  handle.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y + window.scrollY, w: r.width, h: r.height };
  });

/** Scroll through the page so every lazy flyer loads, then back to the top. Returns the page height. */
export async function loadAll(page) {
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  for (let y = 0; y < height; y += 450) {
    await page.evaluate((v) => window.scrollTo(0, v), y);
    await wait(page, 110);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await wait(page, 700);
  return height;
}

/** The list's period groups (Hoy, Este fin de semana…): key, label, top (CSS px) and their events' ids. */
export const periodsOnPage = (page) =>
  page.evaluate(() =>
    [...document.querySelectorAll(".agenda-group")].map((g) => ({
      key: g.dataset.period,
      label: g.querySelector(".agenda-group__heading")?.textContent?.trim(),
      top: g.getBoundingClientRect().top + window.scrollY,
      events: [...g.querySelectorAll("[data-event]")].map((a) => a.dataset.event).filter((v, i, all) => all.indexOf(v) === i),
    })),
  );

/** A screenshot after things settle; `options` are Playwright's (clip, fullPage). */
export async function shot(page, file, options = {}) {
  await wait(page, 450);
  await mkdir(path.dirname(file), { recursive: true });
  await page.screenshot({ path: file, ...options });
  console.log("  ", path.relative(MEDIA, file).replaceAll("\\", "/"));
}

// ---------- the CLI: one screen ----------
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [video, name] = positionals(["path", "now", "theme", "scroll", "click", "wait"]);
  if (!video || !name) {
    console.error("usage: node media/tools/capture.mjs <video> <name> [--path /…] [--now ISO] [--theme light|dark] [--full] [--scroll px] [--click selector] [--wait ms]");
    process.exit(1);
  }
  const theme = arg("theme", "light");
  const pagePath = arg("path", "/");
  const { browser, page, now } = await openPhone({ now: arg("now", comingSaturday()), theme });
  await openSite(page, pagePath, theme);
  if (flag("full")) await loadAll(page);
  const click = arg("click");
  if (click) {
    await page.click(click);
    await wait(page, 900);
  }
  const scroll = Number(arg("scroll", 0));
  if (scroll) {
    await page.evaluate((y) => window.scrollTo(0, y), scroll);
    await wait(page, 700);
  }
  await wait(page, Number(arg("wait", 0)));
  const file = path.join(MEDIA, "public", video, "screens", `${name}.png`);
  await shot(page, file, { fullPage: flag("full") });
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await browser.close();

  const index = path.join(MEDIA, "projects", video, "data", "screens.json");
  const screens = JSON.parse(await readFile(index, "utf8").catch(() => "{}"));
  screens[name] = {
    file: `screens/${name}.png`,
    path: pagePath,
    now,
    theme,
    full: flag("full"),
    scroll,
    click: click ?? null,
    cssHeight: height,
    capturedAt: new Date().toISOString(),
  };
  await mkdir(path.dirname(index), { recursive: true });
  await writeFile(index, JSON.stringify(screens, null, 1));
}
