// The teaser's walk through the LIVE site, captured in one run: every screen and every position scenes/App.tsx
// points at. Rewritten for the site of 4 October 2026 (v2.3): rhythm chips in the pinned bar, the details drawer.
//
//   node media/projects/teaser-v2/capture.mjs [--now 2026-10-10T19:00:00-05:00] [--styles salsa,bachata] [--event <id>]
//   → public/teaser-v2/app/*.png|webp and data/app.json
//
//   top.png            the page as it opens (header, tabs, the bar with its chips, nothing chosen)
//   chips-1.png …      the same after tapping each of --styles in the bar (their chips pressed, the list filtered)
//   list-full.png      the whole list filtered to --styles (full page), with each period's top
//   bar.png            the pinned bar once the page is scrolled (chips and the "N eventos · Salsa, Bachata" line)
//   detail-half.png    one event's details drawer at half height over the list (the first of "Próxima semana" that
//                      isn't free and has a place), the list scrolled to that period
//   detail-full.png    the same drawer pulled up to full height
//   pile-<n>.webp      real flyers of upcoming events, one per account (whole, with their aspect ratio)
//   app.json           positions (CSS px) of everything a scene points at, and the shelf life
//
// It reads the page through the hooks the site's own code uses (ids, data attributes); when the site changes, fix
// them here and the matching beats in scenes/App.tsx (the README lists the last such change).
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { arg, comingSaturday, loadAll, MEDIA, openPhone, openSite, periodsOnPage, PUBLIC, rectOf, shot, SITE, wait } from "../../tools/capture.mjs";

const OUT = path.join(PUBLIC, "teaser-v2", "app"); // in the media home
const DATA = path.join(MEDIA, "projects", "teaser-v2", "data", "app.json");
const NOW_ISO = arg("now", comingSaturday());
const NOW = new Date(NOW_ISO);
const STYLES = arg("styles", "salsa,bachata").split(",");
const PERIODS = ["hoy", "fin-de-semana", "proxima-semana"]; // the three the voice names

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });
const { browser, page } = await openPhone({ now: NOW_ISO });
const meta = { url: SITE, now: NOW_ISO, capturedAt: new Date().toISOString(), viewport: "360x640@3", styles: STYLES };
const snap = (name, options = {}) => shot(page, path.join(OUT, `${name}.png`), options);
const chip = (value) => page.locator(`#jump-chips [data-filter="styles"][data-value="${value}"]`).first();
/** A rect in the viewport (CSS px), not the page. */
const viewRect = (locator) =>
  locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });

// ---------- 1. The page as it opens, and flyers for the opening pile (the unfiltered list) ----------
console.log(`now = ${NOW_ISO}`);
await openSite(page);
await snap("top");
meta.top = { bar: await rectOf(page.locator("#jump-bar")), chips: {} };
for (const style of STYLES) meta.top.chips[style] = await rectOf(chip(style));
await loadAll(page);
const all = await periodsOnPage(page);
const soon = all.flatMap((p) => p.events); // in date order
const cards = await page.evaluate((ids) => {
  return ids.map((id) => {
    const card = document.querySelector(`[data-event="${id}"]`)?.closest("article");
    const img = card?.querySelector("img.event-card__flyer");
    const media = card?.querySelector("[data-flyer-ratio]");
    return {
      id,
      src: img?.currentSrc || img?.src,
      ratio: Number(media?.dataset.flyerRatio || 1),
      styles: card?.querySelector(".style-list")?.textContent?.toLowerCase() ?? "",
      account: card?.querySelector("[data-profile]")?.dataset.profile ?? "",
    };
  });
}, soon);
const isWanted = (c) => STYLES.some((w) => c.styles.includes(w));
const seen = new Set();
const pile = [];
// The rhythms chosen first (in date order); others only if there are fewer than 5. One flyer per account.
for (const c of [...cards.filter(isWanted), ...cards.filter((c) => !isWanted(c))]) {
  if (pile.length === 5 || !c.src || !c.account || seen.has(c.account) || c.ratio < 0.6 || c.ratio > 1.25) continue;
  seen.add(c.account);
  const res = await page.request.get(c.src);
  const file = `pile-${pile.length}${path.extname(new URL(c.src).pathname) || ".webp"}`;
  await writeFile(path.join(OUT, file), await res.body());
  pile.push({ file, id: c.id, ratio: c.ratio, account: c.account, styles: c.styles, chosen: isWanted(c) });
}
meta.pile = pile;
console.log("   pile:", pile.map((p) => `${p.id} @${p.account}`).join(", "));

// ---------- 2. The rhythm chips, tapped one after another at the top of the page ----------
await page.evaluate(() => window.scrollTo(0, 0));
await wait(page, 600);
meta.chips = [];
for (const [i, style] of STYLES.entries()) {
  // Where the chip is when it's tapped: choosing one scrolls the row (the site reveals chosen chips).
  const at = await viewRect(chip(style));
  await chip(style).click();
  await wait(page, 700);
  await page.evaluate(() => window.scrollTo(0, 0));
  await snap(`chips-${i + 1}`);
  const label = (await chip(style).textContent())?.trim();
  meta.chips.push({ file: `chips-${i + 1}.png`, chosen: STYLES.slice(0, i + 1), style, label, tap: at });
}
meta.summary = (await page.locator("#jump-summary").textContent())?.replace(/\s+/g, " ").trim();

// ---------- 3. The filtered list, whole, and the pinned bar ----------
const height = await loadAll(page);
const periods = await periodsOnPage(page);
meta.periods = periods.map(({ key, label, top, events }) => ({ key, label, top, events }));
await page.screenshot({ path: path.join(OUT, "list-full.png"), fullPage: true });
meta.list = { cssHeight: height, file: "list-full.png" };
console.log("   list-full", periods.map((p) => `${p.label}@${Math.round(p.top)}`).join(", "));
// The bar pinned to the top (with the summary line under it) once the page is past it: how tall it is, and a copy.
await page.evaluate(() => window.scrollTo(0, 1200));
await wait(page, 900);
const sticky = await page.evaluate(() => {
  const bottoms = ["jump-bar", "jump-summary"]
    .map((id) => document.getElementById(id))
    .filter((el) => el && !el.hidden && el.getBoundingClientRect().height > 0)
    .map((el) => el.getBoundingClientRect().bottom);
  return Math.ceil(Math.max(...bottoms));
});
await page.screenshot({ path: path.join(OUT, "bar.png"), clip: { x: 0, y: 0, width: 360, height: sticky } });
meta.bar = { file: "bar.png", h: sticky };
// Every period the voice names must be on the page: a missing one is an error, not a warning (the scene would point at
// nothing).
const missing = PERIODS.filter((key) => !periods.find((x) => x.key === key));
if (missing.length) {
  await browser.close();
  throw new Error(`no ${missing.map((k) => `"${k}"`).join(", ")} with ${STYLES.join("+")} at ${NOW_ISO}: pick another --now or --styles`);
}

// ---------- 4. One event's details, opened the way a visitor would, at half then full height ----------
const last = periods.find((p) => p.key === PERIODS.at(-1));
let detail = arg("event", null);
for (const id of detail ? [] : (last?.events ?? [])) {
  const ok = await page.evaluate((id) => {
    const card = document.querySelector(`[data-event="${id}"]`)?.closest("article");
    const text = card?.textContent ?? "";
    return !!card && !/gratis/i.test(text) && /\$/.test(text);
  }, id);
  if (ok) {
    detail = id;
    break;
  }
}
if (!detail) throw new Error("no event to open");
const scrollTop = last.top - sticky; // the period right under the pinned bar, as the site jumps to it
await page.evaluate((y) => window.scrollTo(0, y), scrollTop);
await wait(page, 900);
const card = page.locator(`article:has([data-event="${detail}"])`).first();
const button = card.locator(".event-card__details");
meta.detail = { event: detail, scrollTop, tap: await viewRect(button) };
await button.click();
await wait(page, 1800); // the drawer's rise
await snap("detail-half");
// Opening the drawer scrolls the list so the tapped card stays in view under the bar (the site's drawer.ts).
meta.detail.scrollHalf = await page.evaluate(() => window.scrollY);
const drawerRects = () =>
  page.evaluate(() => {
    const d = document.getElementById("event-drawer");
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    };
    const row = (term) => {
      const dt = [...d.querySelectorAll(".detail-list dt")].find((x) => x.textContent.trim() === term);
      const dd = dt?.nextElementSibling;
      if (!dt || !dd) return null;
      const a = dt.getBoundingClientRect();
      const b = dd.getBoundingClientRect();
      return { x: a.x, y: Math.min(a.y, b.y), w: b.right - a.x, h: Math.max(a.bottom, b.bottom) - Math.min(a.y, b.y) };
    };
    return {
      panel: box(d.querySelector(".drawer__panel")),
      grip: box(d.querySelector(".drawer__grip")),
      when: box(d.querySelector(".event-detail__when")),
      quick: box(d.querySelector(".quick-actions")),
      cuando: row("Cuándo"),
      lugar: row("Lugar"),
      precio: row("Precio"),
      comoLlegar: box(d.querySelector('.detail-list [data-track="como-llegar"]')),
    };
  });
meta.detail.half = await drawerRects();
// Pulled up: the drawer's own control for its two heights (a drag on the grip does the same).
await page.locator("#event-drawer [data-detent-toggle]").first().click();
await wait(page, 1500);
await snap("detail-full");
meta.detail.full = await drawerRects();
console.log("   detail", detail, "half panel", Math.round(meta.detail.half.panel.y), "full panel", Math.round(meta.detail.full.panel.y));

// ---------- shelf life ----------
const saturday = new Date(NOW.getTime() - 5 * 3600e3);
meta.shelfLife = `${saturday.toISOString().slice(0, 10)} (the screens' "Hoy"; post before it's over)`;
await browser.close();
await writeFile(DATA, JSON.stringify(meta, null, 1));
console.log(`done: ${OUT}\nshelf life: ${meta.shelfLife}`);
