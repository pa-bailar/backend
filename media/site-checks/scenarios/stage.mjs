// The image beside the details on a desktop (the owner and a review, 6 Oct): ← → go through an event's photos first,
// then the next event (← back: the previous one's last photo); from the details ↓ walks the whole list to its last
// event; the details of an event deep in the list survive a reload, and back then stays on the site.
import { Skip } from "../lib.mjs";

const visibleCards = '[role="tabpanel"]:not([hidden]) [data-event-card]';

export default {
  name: "stage",
  summary: "photos then events with ← →, the whole list from the details, a reload with them open (desktop)",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check, skip } = ctx;
    if (ctx.touch) throw new Skip("the image beside the details is a desktop's");
    await ctx.goto("/");
    if (!(await ctx.cards().count())) throw new Skip("no events on the list");

    // (1) An event with several photos: → photo 2 … its last, then the next event; ← its last photo again
    const multi = page.locator(`${visibleCards}:has([data-carousel])`).first();
    if (await multi.count()) {
      const id = await multi.getAttribute("data-event-card");
      await multi.locator("[data-card-image]").first().click();
      await ctx.settle();
      const a = await ctx.step("photos: image clicked");
      const total = Number(a.stage.split("/")[1]);
      check("photos: the image opens on 1/N", a.drawer === id && a.stage.startsWith("1/") && total > 1, a);
      const counts = [];
      let s = a;
      for (let i = 0; i < total + 2 && s.drawer === id; i++) {
        await ctx.key("ArrowRight");
        s = await ctx.snap();
        counts.push(s.drawer === id ? s.stage : `next`);
      }
      ctx.log("photos: → …", counts.join(" "));
      const expected = [...Array.from({ length: total - 1 }, (_, i) => `${i + 2}/${total}`), "next"];
      check(
        "photos: → goes through every photo, then the next event",
        counts.join(" ") === expected.join(" ") && s.stage,
        `${counts.join(" ")} (expected ${expected.join(" ")})`,
      );
      await ctx.key("ArrowLeft");
      const d = await ctx.step("photos: ←");
      check("photos: ← back to its last photo", d.drawer === id && d.stage === `${total}/${total}`, d);
      await ctx.key("Escape");
    } else skip("photos", "no event with several photos in today's data");

    // (2) From the details, ↓ to the end: the whole list, card by card, ends on its last card (the list shows every
    // event since 8 Oct 2026: no block to open on the way)
    await ctx.goto("/");
    const lastId = await page.locator(visibleCards).last().getAttribute("data-event-card");
    await ctx.key("ArrowDown");
    await ctx.key("Enter");
    let prev = await ctx.step("walk: Enter on the first card");
    for (let i = 0; i < 400; i++) {
      await ctx.key("ArrowDown");
      const now = await ctx.snap();
      if (now.drawer === prev.drawer) break;
      prev = now;
    }
    const end = await ctx.step("walk: the end");
    check("walk: ↓ from the details reaches the list's last event", end.drawer === lastId, `${end.drawer} (last: ${lastId})`);
    await ctx.key("Escape");

    // (3) The details of an event deep in the list: a reload keeps them; back then closes them, on the site
    await ctx.goto("/");
    const deep = page.locator(visibleCards).last();
    const deepId = await deep.getAttribute("data-event-card");
    await deep.locator("[data-card-image]").first().click();
    await ctx.settle();
    await page.reload({ waitUntil: "load" });
    await ctx.settle();
    const r = await ctx.step("history: reload (details open)");
    check("history: a reload keeps the event's details", r.drawer === deepId, `${deepId} → ${r.drawer || "closed"} (${r.url})`);
    await ctx.back();
    const rb = await ctx.step("history: back");
    check("history: back after the reload closes them, on the site", rb.url === "/" && !rb.drawer, rb);
  },
};
