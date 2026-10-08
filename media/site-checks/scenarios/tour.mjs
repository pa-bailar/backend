// A visitor's tour on a phone (from the Safari-on-iPhone checks, 6 Oct): a first visit, scrolling, the details and back
// (the scroll kept), a carousel swipe, saving → Guardados → reload, the calendar, the search, Filtros and a period's
// "Ver más", each with back. Any engine and device; on a desktop the bar's parts become the header's.
import { Skip } from "../lib.mjs";

/** The first visible match of `selector`, or null. */
async function visible(page, selector) {
  const all = page.locator(selector);
  for (let i = 0; i < (await all.count()); i++) if (await all.nth(i).isVisible()) return all.nth(i);
  return null;
}

export default {
  name: "tour",
  summary: "a visitor's phone tour: details, carousel, save, Guardados, calendar, search, Filtros, Ver más, with back",
  devices: ["phone"],
  async run(ctx) {
    const { page, check, skip } = ctx;
    const overflow = [];
    const look = async (label) => {
      const s = await ctx.step(label);
      if (s.ox) overflow.push(`${label} ${s.ox}px`);
      return s;
    };
    const count = () => ctx.cards().count();

    // A first visit
    await ctx.goto("/");
    const first = await look("first visit");
    if (!(await count())) throw new Skip("no events on the list");
    check(
      "first visit: on the list, at the top",
      first.url === "/" && first.y === 0 && first.screen === "upcoming",
      first,
    );
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const sum =
      bg
        .match(/\d+/g)
        ?.slice(0, 3)
        .map(Number)
        .reduce((a, b) => a + b, 0) ?? -1;
    check(
      `the ${ctx.theme} theme's background`,
      !/rgba\(0, 0, 0, 0\)/.test(bg) && (ctx.theme === "light") === sum >= 450,
      bg,
    );
    await ctx.shot("1-top");

    await page.evaluate(() => scrollTo(0, Math.min(2200, document.documentElement.scrollHeight - innerHeight)));
    await ctx.settle();
    await look("scrolled down");
    await ctx.shot("2-scrolled");

    // A card's details, then back: the list where it was
    const card = ctx.cards().nth(Math.min(3, (await count()) - 1));
    const id = await card.getAttribute("data-event-card");
    const opener = (await card.locator(".event-card__details").count())
      ? card.locator(".event-card__details")
      : card.locator("a.event-card__hit");
    await opener.scrollIntoViewIfNeeded();
    await ctx.settle();
    const before = await ctx.snap();
    await ctx.tap(opener);
    const opened = await look("details open");
    check("details: the card's event opens", opened.drawer === id && opened.url.startsWith("/evento/"), opened);
    // the list may move to keep the tapped card in view above the drawer (drawerSheet.ts cardScrollDelta)
    const inView = await card.evaluate((c) => {
      const r = c.getBoundingClientRect();
      return r.bottom > 0 && r.top < innerHeight;
    });
    check("details: the tapped card stays in view", inView, `scroll ${before.y} → ${opened.y}`);
    await ctx.shot("3-details");
    // Where the card is on screen: what back must keep. Not the scroll itself: on a wide screen the side panel takes
    // a column from the list (4 → 3) and gives it back on closing, so the page scrolls to keep the card in its place.
    const cardTop = () => card.evaluate((c) => Math.round(c.getBoundingClientRect().top));
    const topOpen = await cardTop();
    await ctx.back();
    const closed = await look("back");
    const topClosed = await cardTop();
    check(
      "back closes the details, the card where it was",
      !closed.drawer && closed.url === "/" && Math.abs(topClosed - topOpen) < 5,
      `${fmtY(opened, closed)}, the card's top ${topOpen} → ${topClosed}`,
    );

    // A carousel: one swipe → its second photo
    const carouselCard = ctx
      .cards()
      .filter({ has: page.locator("[data-carousel]") })
      .first();
    if (await carouselCard.count()) {
      const carousel = carouselCard.locator("[data-carousel]").first();
      await carousel.scrollIntoViewIfNeeded();
      await carousel.evaluate((el) => {
        const strip = [el, ...el.querySelectorAll("*")].find((n) => n.scrollWidth > n.clientWidth + 10);
        strip?.scrollBy({ left: strip.clientWidth, behavior: "instant" });
      });
      await ctx.settle();
      const n = (await carouselCard.locator("[data-carousel-count]").first().textContent())?.trim();
      check("carousel: a swipe shows photo 2", n?.startsWith("2/"), `count ${n}`);
      await ctx.shot("4-carousel");
    } else skip("carousel", "no carousel in today's data");

    // Save one → Guardados → reload
    const save = ctx.cards().first().locator("[data-save]").first();
    await save.scrollIntoViewIfNeeded();
    await ctx.settle();
    const ys = await page.evaluate(() => Math.round(scrollY));
    await ctx.tap(save);
    const saved = await look("saved one");
    check(
      "save: pressed, no scroll jump",
      (await save.getAttribute("aria-pressed")) === "true" && Math.abs(saved.y - ys) < 5,
      `${ys} → ${saved.y}`,
    );
    const nav = async (view) => visible(page, `[data-view="${view}"]`);
    await ctx.tap(await nav("saved"));
    const g = await look("Guardados");
    const gCards = await count();
    check(
      "Guardados: its own address, the saved event",
      g.url.startsWith("/guardados") && gCards === 1,
      `${g.url}, ${gCards} cards`,
    );
    await ctx.shot("5-guardados");
    await page.reload({ waitUntil: "load" });
    await ctx.settle();
    const rCards = await count();
    check("Guardados after a reload: still saved", rCards === 1, `${rCards} cards`);

    // The calendar, then back
    await ctx.tap(await nav("calendar"));
    const cal = await look("Calendario");
    check("calendar: its address", cal.url.startsWith("/calendario") && cal.screen === "calendar", cal);
    await ctx.shot("6-calendar");
    await ctx.back();
    const fromCal = await look("back");
    // between the calendar and Guardados the entry is replaced (site ARCHITECTURE, screenHistory.ts): back → the list
    check("back from the calendar: the list", fromCal.url === "/" && fromCal.screen === "upcoming", fromCal);

    // The search, then back
    await ctx.goto("/");
    const all = await count();
    const word = await ctx
      .cards()
      .first()
      .locator(".event-card__title")
      .first()
      .textContent()
      .then((t) => (t ?? "").split(/[^\p{L}]+/u).sort((a, b) => b.length - a.length)[0] ?? "");
    // the phone's bar opens a search field with its own history entry; the desktop's field is always there (Escape)
    const barSearch = await visible(page, "#bottom-search-open");
    await ctx.tap(barSearch ?? (await visible(page, "[data-search]")));
    await page.keyboard.type(word, { delay: 15 });
    await ctx.settle();
    const found = await count();
    await look(`search "${word}"`);
    check(`search "${word}": results`, found > 0 && found <= all, `${found} of ${all}`);
    await ctx.shot("7-search");
    if (barSearch) await ctx.back();
    else await ctx.key("Escape");
    const after = await look(barSearch ? "back" : "Escape");
    const query = await page.evaluate(() =>
      [...document.querySelectorAll("[data-search]")].map((i) => i.value).join(""),
    );
    check(
      `${barSearch ? "back" : "Escape"} ends the search`,
      after.url === "/" && !query && (await count()) === all,
      `${after.url} query "${query}", ${await count()} of ${all}`,
    );

    // Filtros, then back
    const filters = await visible(page, "#bottom-filters");
    if (filters) {
      await ctx.tap(filters);
      const f = await look("Filtros");
      check("Filtros opens its sheet", f.open.length > 0, f);
      await ctx.shot("8-filters");
      await ctx.back();
      const fc = await look("back");
      check("back closes Filtros", !fc.open.length && fc.url === "/", fc);
    } else skip("Filtros", "no Filtros button here (the desktop's pills)");

    // A period's "Ver más", then back
    const more = await visible(page, '[role="tabpanel"]:not([hidden]) [data-show-period]');
    if (more) {
      const period = await more.getAttribute("data-show-period");
      await more.scrollIntoViewIfNeeded();
      const folded = (await ctx.snap()).folded;
      await ctx.tap(more);
      const m = await look("Ver más");
      check("Ver más opens the period whole", !m.folded.includes(period) && m.folded.length === folded.length - 1, m);
      await ctx.back();
      const mb = await look("back");
      check("back folds it again", mb.folded.includes(period) && mb.url === "/", mb);
    } else skip("Ver más", "no folded period in today's data");

    check("no horizontal overflow", !overflow.length, overflow.join(", "));
  },
};

const fmtY = (a, b) => `drawer ${b.drawer || "closed"}, url ${b.url}, scroll ${a.y} → ${b.y}`;
