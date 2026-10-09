// The image beside the details on a desktop (the owner and a review, 6 Oct): ← → go through an event's photos first,
// then the next event (← back: the previous one's last photo); from the details, moving onto a period's block opens it
// and shows its first new event; with a block opened that way, Escape, back, forward and a reload stay sane.
import { Skip } from "../lib.mjs";

const visibleCards = '[role="tabpanel"]:not([hidden]) [data-event-card]';

export default {
  name: "stage",
  summary: "photos then events with ← →, blocks opened from the details, and the history after that (desktop)",
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

    // (2) From the details, ↓ to the end: every block on the way opens and shows its first new event
    await ctx.goto("/");
    const blocks = (await ctx.snap()).folded;
    if (blocks.length) {
      await ctx.key("ArrowDown");
      await ctx.key("Enter");
      let prev = await ctx.step("blocks: Enter on the first card");
      const silent = [];
      let opened = 0;
      for (let i = 0; i < 300; i++) {
        await ctx.key("ArrowDown");
        const now = await ctx.snap();
        if (now.folded.length < prev.folded.length) {
          opened += prev.folded.length - now.folded.length;
          ctx.log(`blocks: opened ${prev.folded.filter((p) => !now.folded.includes(p)).join(",")}`, now);
          if (now.drawer === prev.drawer) silent.push(prev.folded.find((p) => !now.folded.includes(p)));
        }
        if (now.drawer === prev.drawer && now.folded.length === prev.folded.length) break;
        prev = now;
      }
      const end = await ctx.step("blocks: the end");
      check(
        "blocks: every block opens on the way down",
        opened === blocks.length && !end.folded.length,
        `${opened} of ${blocks.length}, left ${end.folded.join(",")}`,
      );
      check("blocks: each shows its first new event", !silent.length, `stopped silently on ${silent.join(",")}`);
      await ctx.key("Escape");
    } else skip("blocks", "no folded period in today's data");

    // (3) A block opened from the details (→ from the card just before it): Escape, back, forward, reload
    /** The last card before the first folded period's block, in the page's order (null: none). */
    const cardBefore = (period) =>
      page.evaluate((p) => {
        const view = document.querySelector('[role="tabpanel"]:not([hidden])');
        const block = view.querySelector(`[data-period="${p}"]`);
        const before = [...view.querySelectorAll("[data-event-card]")].filter(
          (card) => card.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING,
        );
        return before.at(-1)?.dataset.eventCard ?? null;
      }, period);
    /** The list from a fresh entry: a reload of one with blocks open keeps them open (site, 8 Oct 2026). */
    const fresh = async () => {
      await page.evaluate(() => history.replaceState(null, "", location.pathname));
      await ctx.goto("/");
    };
    const intoBlock = async () => {
      await fresh();
      const period = (await ctx.snap()).folded[0];
      const last = page.locator(`[role="tabpanel"]:not([hidden]) [data-event-card="${await cardBefore(period)}"]`);
      await last.locator("[data-card-image]").first().click();
      await ctx.settle();
      let s = await ctx.snap();
      for (let i = 0; i < 12 && s.folded.includes(period); i++) {
        await ctx.key("ArrowRight");
        s = await ctx.snap();
      }
      ctx.log(`history: → into ${period}`, s);
      return { period, s };
    };
    await fresh();
    if (blocks.length && (await cardBefore(blocks[0]))) {
      let { period, s } = await intoBlock();
      check("history: → from the card before a block opens it", !s.folded.includes(period) && s.drawer, s);
      await ctx.key("Escape");
      const e = await ctx.step("history: Escape");
      check(
        "history: Escape closes the details, the block stays open",
        !e.drawer && !e.stage && e.url === "/" && !e.folded.includes(period),
        e,
      );
      await ctx.back();
      const b = await ctx.step("history: back");
      check("history: back folds the block", b.url === "/" && b.folded.includes(period) && !b.drawer, b);
      await ctx.forward();
      const f = await ctx.step("history: forward");
      check("history: forward opens it again, no details", f.url === "/" && !f.folded.includes(period) && !f.drawer, f);

      ({ period, s } = await intoBlock());
      await ctx.back();
      const b1 = await ctx.step("history: back (details open)");
      check(
        "history: back closes the details, the block stays",
        !b1.drawer && !b1.stage && b1.url === "/" && !b1.folded.includes(period),
        b1,
      );
      await ctx.back();
      const b2 = await ctx.step("history: back again");
      check("history: back again folds the block", b2.url === "/" && b2.folded.includes(period), b2);

      ({ period, s } = await intoBlock());
      await page.reload({ waitUntil: "load" });
      await ctx.settle();
      const r = await ctx.step("history: reload (details open)");
      check(
        "history: a reload keeps the event's details",
        r.drawer === s.drawer,
        `${s.drawer} → ${r.drawer || "closed"} (${r.url})`,
      );
      // The bug-squash pass of 8 Oct 2026: a reload folded the block, and the next back did nothing.
      check("history: a reload keeps the block open", !r.folded.includes(period), r);
      await ctx.back();
      const rb = await ctx.step("history: back");
      check("history: back after the reload closes them, on the site", rb.url === "/" && !rb.drawer, rb);
    } else skip("history", "no folded period after a card in today's data");
  },
};
