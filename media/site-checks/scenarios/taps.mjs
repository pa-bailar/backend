// Taps that change what's under the finger (site #165, the bug hunt of 7 Oct 2026): a double-tap's second tap never
// presses what the first one opened ("Ver N más"'s new cards, the view under a notice's button), and a tap on a
// sheet's own edge doesn't close it, while one on its backdrop does. Phones.
import { Skip, VIEW } from "../lib.mjs";

/** A finger's double-tap at the middle of `locator`: two taps `gap` ms apart, on the same spot. */
async function doubleTap(page, locator, gap = 150) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const [x, y] = [box.x + box.width / 2, box.y + box.height / 2];
  await page.touchscreen.tap(x, y);
  await page.waitForTimeout(gap);
  await page.touchscreen.tap(x, y);
}

export default {
  name: "taps",
  summary: "a double-tap's second tap never presses what the first opened (Ver N más, a notice's button); a sheet's edge doesn't close it",
  devices: ["phone", "iphone"],
  async run(ctx) {
    const { page, check } = ctx;
    if (!ctx.touch) throw new Skip("a finger's taps");

    // "Ver N más" or a folded period's "Ver los N eventos", double-tapped: the period opens, no event's details
    await ctx.goto("/");
    const more = page.locator(`${VIEW} [data-show-period]`).first();
    if (await more.count()) {
      const period = await more.getAttribute("data-show-period");
      await doubleTap(page, more);
      await ctx.settle();
      const opened = await ctx.step("a period's button double-tapped");
      check("a period's button double-tapped opens no event's details", !opened.drawer, opened);
      check("…and opens its period", !opened.folded.includes(period), opened);
    } else ctx.skip("a period's button double-tapped", "no folded period today");

    // A notice's "Ver guardados", double-tapped: Guardados, and no event's details under the finger
    await ctx.goto("/");
    const bookmark = ctx.cards().locator('[data-save][aria-pressed="false"]').first();
    if (!(await bookmark.count())) return ctx.skip("the notice's button double-tapped", "nothing left to save");
    await ctx.tap(bookmark);
    const action = page.locator("#notice .notice__action");
    if (!(await action.count())) return ctx.skip("the notice's button double-tapped", "no notice after saving");
    await doubleTap(page, action);
    await ctx.settle();
    const saved = await ctx.step("the notice's button double-tapped");
    check("the notice's button double-tapped: Guardados, no event's details", saved.screen === "saved" && !saved.drawer, saved);

    // A post open in the viewer (the details' main media link): a tap on the sheet's own right edge keeps it open;
    // a tap on the backdrop above it closes it
    await ctx.goto("/");
    await ctx.tap(ctx.cards().first().locator(".event-card__details"));
    await page.evaluate(() => document.querySelector("#event-drawer [data-media-link]")?.click());
    await ctx.settle();
    if (!(await ctx.snap()).open.includes("post-viewer")) return ctx.skip("a sheet's edge", "the viewer didn't open");
    const box = await page.locator("#post-viewer").boundingBox();
    await page.touchscreen.tap(box.x + box.width - 6, box.y + 120);
    await ctx.settle();
    const edge = await ctx.step("a tap on the viewer's edge");
    check("a tap on the viewer's own edge keeps it open", edge.open.includes("post-viewer"), edge);
    if (box.y < 80) return ctx.skip("a tap on the backdrop", "the viewer fills the screen");
    await page.touchscreen.tap(box.x + box.width / 2, box.y - 40);
    await ctx.settle();
    const backdrop = await ctx.step("a tap on the backdrop");
    check("a tap on the backdrop above it closes it", !backdrop.open.includes("post-viewer"), backdrop);
  },
};
