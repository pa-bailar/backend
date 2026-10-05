// The teaser's walk through the LIVE site, captured in one run: every screen and every position scenes/App.tsx
// points at.
//
//   node media/projects/teaser-v2/capture.mjs [--now 2026-10-10T19:00:00-05:00] [--styles Salsa,Bachata] [--event <id>]
//   → public/teaser-v2/app/*.png|webp and data/app.json
//
// ⚠ Written for the site before Oct 4, 2026: section 2 opens the "Ritmo ▾" checklist (#jump-style), which the
// pinned filter bar replaced with rhythm chips (#jump-chips) and a "Cuándo" menu. Update sections 2–3 (and the
// matching beats in scenes/App.tsx) before re-capturing for a v2.3. Everything else uses stable hooks.
//
//   top.png              the page as it opens
//   menu-0.png …         the rhythm checklist open: nothing chosen, then each of --styles ticked in turn
//   list-full.png        the whole list filtered to --styles (full page), with each period's top
//   bar-<period>.png     the sticky bar when scrolled to that period, if the site shows it there
//   detail-open.png, detail-sheet.png, detail-rows.png   one event's details: opened, the half sheet, pulled up
//   pile-<n>.webp        real flyers of upcoming events (whole, with their aspect ratio)
//   app.json             positions (CSS px) of everything a scene points at, and the shelf life
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { arg, comingSaturday, loadAll, MEDIA, openPhone, openSite, periodsOnPage, rectOf, shot, wait } from "../../tools/capture.mjs";

const OUT = path.join(MEDIA, "public", "teaser-v2", "app");
const DATA = path.join(MEDIA, "projects", "teaser-v2", "data", "app.json");
const SITE = "https://pa-bailar.github.io/";
const NOW_ISO = arg("now", comingSaturday());
const NOW = new Date(NOW_ISO);
const STYLES = arg("styles", "Salsa,Bachata").split(",");
const PERIODS = ["hoy", "fin-de-semana", "proxima-semana"]; // the three the voice names

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });
const { browser, page } = await openPhone({ now: NOW_ISO });
const meta = { url: SITE, now: NOW_ISO, capturedAt: new Date().toISOString(), viewport: "360x640@3", styles: STYLES };
const snap = (name, options = {}) => shot(page, path.join(OUT, `${name}.png`), options);
/** A row of the open rhythm menu by its visible label. */
const menuItem = (label) =>
  page.locator("#jump-style-menu .bar-menu__item").filter({ has: page.locator(".bar-menu__label", { hasText: new RegExp(`^${label}$`) }) });

// ---------- 1. Flyers for the opening pile (the unfiltered list) ----------
console.log(`now = ${NOW_ISO}`);
await openSite(page);
await snap("top");
meta.top = { bar: await rectOf(page.locator("#jump-bar")), styleButton: await rectOf(page.locator("#jump-style")) };
await loadAll(page);
const all = await periodsOnPage(page);
const soon = all.flatMap((p) => p.events); // in date order
const cards = await page.evaluate((ids) => {
  return ids.map((id) => {
    const card = document.querySelector(`[data-event="${id}"]`)?.closest("article");
    const img = card?.querySelector("img");
    const media = card?.querySelector("[data-flyer-ratio]");
    return {
      id,
      src: img?.currentSrc || img?.src,
      ratio: Number(media?.dataset.flyerRatio || 1),
      styles: card?.querySelector(".style-list")?.textContent?.toLowerCase() ?? "",
      account: card?.querySelector("[data-account]")?.dataset.account ?? "",
    };
  });
}, soon);
const wanted = STYLES.map((s) => s.toLowerCase());
const seen = new Set();
const pile = [];
const isWanted = (c) => wanted.some((w) => c.styles.includes(w));
// The rhythms chosen first (in date order); others only if there are fewer than 5.
for (const c of [...cards.filter(isWanted), ...cards.filter((c) => !isWanted(c))]) {
  if (pile.length === 5 || !c.src || seen.has(c.account) || c.ratio < 0.6 || c.ratio > 1.25) continue;
  seen.add(c.account);
  const res = await page.request.get(c.src);
  const file = `pile-${pile.length}${path.extname(new URL(c.src).pathname) || ".webp"}`;
  await writeFile(path.join(OUT, file), await res.body());
  pile.push({ file, id: c.id, ratio: c.ratio, account: c.account, styles: c.styles, chosen: isWanted(c) });
}
meta.pile = pile;
console.log("   pile:", pile.map((p) => p.id).join(", "));

// ---------- 2. The "Ritmo ▾" checklist: open, tick each style ----------
await page.evaluate(() => window.scrollTo(0, 0));
await wait(page, 400);
await page.click("#jump-style");
await wait(page, 500);
const menuRect = async () => rectOf(page.locator("#jump-style-menu"));
meta.menu = { rect: await menuRect(), items: {}, frames: [] };
await snap("menu-0");
meta.menu.frames.push({ file: "menu-0.png", chosen: [] });
for (const [i, style] of STYLES.entries()) {
  const item = menuItem(style);
  meta.menu.items[style] = await rectOf(item);
  await item.click();
  await wait(page, 500);
  await snap(`menu-${i + 1}`);
  meta.menu.frames.push({ file: `menu-${i + 1}.png`, chosen: STYLES.slice(0, i + 1) });
}
meta.menu.done = await rectOf(page.locator("#jump-style-menu .bar-menu__done"));
await page.click("#jump-style-menu .bar-menu__done");
await wait(page, 700);
await snap("after-menu");
meta.styleLabel = (await page.locator("#jump-style-label").textContent())?.trim();

// ---------- 3. The filtered list, whole, and the bar at each period ----------
const height = await loadAll(page);
const periods = await periodsOnPage(page);
meta.periods = periods.map(({ key, label, top, events }) => ({ key, label, top, events }));
await page.screenshot({ path: path.join(OUT, "list-full.png"), fullPage: true });
meta.list = { cssHeight: height, file: "list-full.png" };
console.log("   list-full", periods.map((p) => `${p.label}@${Math.round(p.top)}`).join(", "));
meta.bars = {};
for (const key of PERIODS) {
  const p = periods.find((x) => x.key === key);
  if (!p) {
    console.warn(`   WARNING: no "${key}" period with ${STYLES.join("+")} at ${NOW_ISO}: pick another --now`);
    continue;
  }
  // Like a thumb: scroll past, then a little back up (the bar comes back on any scroll up).
  await page.evaluate((y) => window.scrollTo(0, y + 40), p.top - 64);
  await wait(page, 300);
  await page.evaluate((y) => window.scrollTo(0, y), p.top - 64);
  await wait(page, 700);
  const bar = await page.evaluate(() => {
    const el = document.getElementById("jump-bar");
    const r = el.getBoundingClientRect();
    return !el.hidden && !el.classList.contains("is-hidden") && r.bottom > 4 && r.top < 4 ? { h: r.height } : null;
  });
  if (bar) {
    await page.screenshot({ path: path.join(OUT, `bar-${key}.png`), clip: { x: 0, y: 0, width: 360, height: Math.ceil(bar.h) } });
    meta.bars[key] = { file: `bar-${key}.png`, h: bar.h, label: (await page.locator("#jump-period-label").textContent())?.trim() };
  }
}

// ---------- 4. One event's details, opened the way a visitor would ----------
const last = periods.find((p) => p.key === PERIODS.at(-1));
let detail = null;
for (const id of last?.events ?? []) {
  const ok = await page.evaluate((id) => {
    const card = document.querySelector(`[data-event="${id}"]`)?.closest("article");
    return !!card && !/gratis/i.test(card.textContent ?? "");
  }, id);
  if (ok) {
    detail = id;
    break;
  }
}
detail = arg("event", detail);
if (!detail) throw new Error("no event to open");
// Scroll the list to where the video leaves it (the last period under the bar), then tap.
await page.evaluate((y) => window.scrollTo(0, y), last.top - 64);
await wait(page, 700);
const card = page.locator(`article:has([data-event="${detail}"])`).first();
const details = card.getByRole("button", { name: /detalles/i });
const target = (await details.count()) ? details.first() : card.locator(`[data-event="${detail}"]`).first();
meta.detail = {
  event: detail,
  scrollTop: last.top - 64,
  card: await rectOf(card),
  tap: await rectOf(target),
  tapIsDetailsButton: (await details.count()) > 0,
};
await target.click();
await wait(page, 1600);
await snap("detail-open");

// In the browser: the slide on screen, its sheet (".viewer-panel"; the whole screen if there's none), the
// scroller that expands it, and the rects (viewport CSS px) of what the voice names.
const inSlide = (fn) =>
  page.evaluate(`(() => {
    const onScreen = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.left > -2 && r.right < innerWidth + 2; };
    const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
    const info = [...document.querySelectorAll(".event-dialog__info")].find(onScreen);
    const panel = info?.closest(".viewer-panel") ?? null;
    const slide = info?.parentElement?.closest("[class*=slide], .viewer-panel")?.parentElement ?? info;
    let scroller = info;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
    const list = info?.querySelector(".detail-list");
    const dts = list ? [...list.querySelectorAll("dt")] : [];
    const row = (term) => {
      const dt = dts.find((d) => d.textContent.trim() === term);
      const dd = dt?.nextElementSibling;
      if (!dt || !dd) return null;
      const a = dt.getBoundingClientRect(), b = dd.getBoundingClientRect();
      return { x: a.x, y: Math.min(a.y, b.y), w: b.right - a.x, h: Math.max(a.bottom, b.bottom) - Math.min(a.y, b.y) };
    };
    const how = [...(list?.querySelectorAll("a") ?? [])].find((a) => /c[oó]mo llegar/i.test(a.textContent ?? ""));
    const prices = info?.querySelector(".price-list");
    return (${fn})({ info, panel, slide, scroller, list, row, box, how, prices });
  })()`);

const half = await inSlide(`({ panel, info, row, box }) => ({
  panel: panel ? box(panel) : { x: 0, y: 0, w: innerWidth, h: innerHeight },
  hasPanel: !!panel,
  when: box(info.querySelector(".event-sheet__head .event-dialog__when, .event-dialog__when")),
  quickHow: box(info.querySelector(".event-sheet__quick [data-track=como-llegar]")),
  cuando: row("Cuándo"),
})`);
// The sheet at half height, cut out (the flyer above it is the rest of detail-open.png).
const panel = { ...half.panel, h: Math.min(half.panel.h, 640 - half.panel.y) };
await page.screenshot({ path: path.join(OUT, "detail-sheet.png"), clip: { x: panel.x, y: panel.y, width: panel.w, height: panel.h } });
console.log("   detail-sheet");

// Pull it up: scroll the slide so the rows sit just under the sheet's bar (expanding it to full height).
await inSlide(`({ scroller, list, info }) => {
  const bar = info.closest(".viewer-panel")?.querySelector(".viewer-bar") ?? document.querySelector(".viewer-bar");
  const barBottom = bar ? bar.getBoundingClientRect().height : 0;
  if (scroller && list) scroller.scrollTop += list.getBoundingClientRect().top - barBottom - 14;
}`);
await wait(page, 1200);
await inSlide(`({ scroller, list, info }) => {
  const bar = info.closest(".viewer-panel")?.querySelector(".viewer-bar") ?? document.querySelector(".viewer-bar");
  const barBottom = bar ? bar.getBoundingClientRect().bottom : 0;
  if (scroller && list) scroller.scrollTop += list.getBoundingClientRect().top - barBottom - 14;
}`);
await wait(page, 900);
await snap("detail-rows");
const full = await inSlide(`({ row, box, how, prices, info }) => ({
  cuando: row("Cuándo"),
  lugar: row("Lugar"),
  precio: row("Precio"),
  comoLlegar: box(how),
  precios: box(prices),
  preciosHeading: box(prices?.previousElementSibling),
  panelTop: (info.closest(".viewer-panel") ?? info).getBoundingClientRect().top,
})`);
meta.detail.sheet = { file: "detail-sheet.png", ...panel, hasPanel: half.hasPanel, fullScreen: panel.y < 2 && panel.h > 630 };
meta.detail.half = { when: half.when, quickHow: half.quickHow, cuando: half.cuando }; // viewport CSS px
meta.detail.rows = full; // viewport CSS px, in detail-rows.png (the sheet pulled up)
console.log("   detail", detail, JSON.stringify(meta.detail.sheet));

// ---------- shelf life ----------
const saturday = new Date(NOW.getTime() - 5 * 3600e3);
meta.shelfLife = `${saturday.toISOString().slice(0, 10)} (the screens' "Hoy"; post before it's over)`;

await browser.close();
await writeFile(DATA, JSON.stringify(meta, null, 1));
console.log(`done: ${OUT}\nshelf life: ${meta.shelfLife}`);
