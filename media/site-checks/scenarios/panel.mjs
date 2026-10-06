// The desktop's side panel and the image beside it (6 Oct): the panel follows the card clicked or focused, the image
// opens beside it with the panel still usable, → moves both to the next event, Escape, × and back close both, and the
// list stays where it was.
import { Skip } from "../lib.mjs";

/** The open details' title and the image stage's alt text (it names the event). */
const shown = (page) =>
  page.evaluate(() => ({
    title:
      document
        .querySelector("#event-drawer[open] #drawer-title, #event-drawer[open] .event-detail__title")
        ?.textContent?.trim() ?? "",
    alt: document.getElementById("lightbox")?.open ? (document.getElementById("lightbox-image")?.alt ?? "") : "",
  }));
const sameEvent = ({ title, alt }) => title && alt && alt.toLowerCase().includes(title.slice(0, 12).toLowerCase());
const cardId = (s) => (s.focus.startsWith("card:") ? s.focus.slice(5) : null);

export default {
  name: "panel",
  summary: "the desktop's side panel and image: follows the card, → moves both, Escape/×/back close, scroll kept",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("the side panel is a desktop's");
    await ctx.goto("/");
    const cards = ctx.cards();
    if ((await cards.count()) < 4) throw new Skip("fewer than 4 events on the list");
    const id = (n) => cards.nth(n).getAttribute("data-event-card");

    // A card clicked: its details in the panel; another card's image: the panel follows, the image beside it
    await cards.nth(0).locator("a.event-card__hit").click();
    await ctx.settle();
    const a = await ctx.step("click card 1");
    check("a card's click opens its details, no image", a.drawer === (await id(0)) && !a.stage, a);
    await cards.nth(2).locator("[data-card-image]").first().click();
    await ctx.settle();
    const b = await ctx.step("click card 3's image");
    check("another card's image: the panel follows, the image opens", b.drawer === (await id(2)) && b.stage, b);
    check("image and panel show the same event", sameEvent(await shown(page)), await shown(page));
    const reachable = await page.evaluate(() => {
      const el = document.querySelector("#event-drawer[open] .quick-actions > *");
      if (!el) return "no quick actions";
      const r = el.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest("#event-drawer")
        ? true
        : "covered";
    });
    check("the panel's buttons stay usable beside the image", reachable === true, String(reachable));
    await ctx.shot("image-beside-panel");

    // → goes through the event's photos, then the next event: both move
    let c = b;
    for (let i = 0; i < 12 && c.drawer === b.drawer; i++) {
      await ctx.key("ArrowRight");
      c = await ctx.snap();
    }
    ctx.log("→… next event", c);
    check("→ moves the panel and the image to the next event", c.drawer && c.drawer !== b.drawer && c.stage, c);
    check("…still the same event in both", sameEvent(await shown(page)), await shown(page));
    await ctx.key("Escape");
    const d = await ctx.step("Escape");
    check("Escape closes both", !d.drawer && !d.stage && d.url === "/", d);

    // The panel open, the arrows on the list carry it along
    await cards.nth(1).locator("a.event-card__hit").click();
    await ctx.settle();
    await cards.nth(1).locator("a.event-card__hit").focus();
    await ctx.key("ArrowRight");
    const e = await ctx.step("panel open, → on the list");
    check("the panel follows the focus", e.drawer && e.drawer === cardId(e) && e.drawer !== (await id(1)), e);

    // The focus lost by a click on the panel's text: ↓ goes on from the panel's event
    await page.locator("#event-drawer[open] #drawer-title, #event-drawer[open] .event-detail__title").first().click();
    await ctx.settle();
    const f0 = await ctx.step("click the panel's title");
    await ctx.key("ArrowDown");
    const f = await ctx.step("↓");
    // the focus stays in the panel (as after Enter): the arrows move the panel itself
    check(
      "↓ after a click in the panel: the panel's next event",
      f.drawer && f.drawer !== f0.drawer,
      `${f0.drawer} → ${f.drawer}`,
    );
    await ctx.key("Escape");

    // × on the image, and back, close both
    await ctx.goto("/");
    await cards.nth(3).locator("[data-card-image]").first().click();
    await ctx.settle();
    await page.locator("[data-lightbox-close]").first().click();
    await ctx.settle();
    const g = await ctx.step("× on the image");
    check("× on the image closes both", !g.drawer && !g.stage && g.url === "/", g);
    await cards.nth(3).locator("[data-card-image]").first().click();
    await ctx.settle();
    await ctx.back();
    const h = await ctx.step("image, then back");
    check("back closes both", !h.drawer && !h.stage && h.url === "/", h);

    // Mid-page: an image clicked, then Escape: the list where it was
    const height = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    const moved = [];
    for (const y of [0, Math.round(height * 0.3), Math.round(height * 0.6)]) {
      await page.evaluate((y) => scrollTo(0, y), y);
      await ctx.settle();
      const at = await page.evaluate(() => {
        const room = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
        const img = [
          ...document.querySelectorAll('[role="tabpanel"]:not([hidden]) [data-event-card] [data-card-image]'),
        ].find((el) => {
          const r = el.getBoundingClientRect();
          const m = r.top + r.height / 2;
          return m > room + 20 && m < innerHeight - 80;
        });
        if (!img) return null;
        const r = img.getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
      });
      if (!at) {
        ctx.log(`y=${y}`, "no image on screen");
        continue;
      }
      const before = await ctx.snap();
      await page.mouse.click(at[0], at[1]);
      await ctx.settle();
      const open = await ctx.snap();
      await ctx.key("Escape");
      if ((await ctx.snap()).drawer) await ctx.key("Escape");
      const after = await ctx.step(`y=${before.y}: image, Escape`);
      if (!open.stage || after.drawer || after.stage || after.y !== before.y)
        moved.push(
          `y=${before.y}: opened ${Boolean(open.stage)}, after ${after.y} drawer=${after.drawer || "-"} stage=${after.stage || "-"}`,
        );
    }
    check("image then Escape: the list stays where it was", !moved.length, moved.join("; "));
  },
};
