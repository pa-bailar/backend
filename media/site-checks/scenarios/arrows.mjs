// The keyboard's ↑ ↓ on a desktop (bug-squash and the owner, 6 Oct): from nothing selected, on the list, with the
// details and the image open; mid-page (the card focused is on screen, clear of the pinned bar); the Cuándo menu keeps
// its own arrows; the calendar's cards are reached.
import { Skip, focusedCardId } from "../lib.mjs";

/** A card's place on the page: [left, top + scrollY], or null. */
const place = (page, id) =>
  page.evaluate((id) => {
    const c = id && document.querySelector(`[role="tabpanel"]:not([hidden]) [data-event-card="${CSS.escape(id)}"]`);
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top + scrollY)];
  }, id);

/** The focused card: on screen, and what covers its top (another element than the card: the pinned bar?). */
const focusedCard = (page) =>
  page.evaluate(() => {
    const card = document.activeElement?.closest("[data-event-card]");
    if (!card) return null;
    const r = card.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, Math.max(1, r.top + 12));
    return {
      id: card.dataset.eventCard,
      // its top on screen (the site focuses without scrolling when the top is in view)
      onScreen: r.top >= 0 && r.top < innerHeight - 40,
      top: Math.round(r.top),
      coveredBy:
        hit && !card.contains(hit) ? (hit.closest("[id]")?.id ?? hit.className?.toString().slice(0, 30)) : null,
    };
  });


export default {
  name: "arrows",
  summary: "↑ ↓ on a desktop: the list, the details and image, mid-page, the Cuándo menu, the calendar",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("the arrows are a desktop's");
    await ctx.goto("/");
    const a = await ctx.step("start");
    if (!(await ctx.cards().count())) throw new Skip("no events on the list");

    await ctx.key("ArrowDown");
    const b = await ctx.step("↓ (nothing selected)");
    check("↓ from nothing focuses a card, the page stays", focusedCardId(b) && b.y === a.y, b);
    await ctx.key("ArrowDown");
    const c = await ctx.step("↓ on the list");
    const [pb, pc] = [await place(page, focusedCardId(b)), await place(page, focusedCardId(c))];
    check(
      "↓ on the list: the card below, same column",
      focusedCardId(c) && pb && pc && pc[0] === pb[0] && pc[1] > pb[1],
      `${b.focus} ${pb} → ${c.focus} ${pc}`,
    );

    await ctx.key("Enter");
    const d = await ctx.step("Enter");
    check("Enter opens the details and the image", d.drawer === focusedCardId(c) && d.stage, d);
    await ctx.key("ArrowDown");
    const e = await ctx.step("↓ in the details");
    const [pd, pe] = [await place(page, d.drawer), await place(page, e.drawer)];
    check(
      "↓ with the details: the event below, image kept",
      e.drawer && e.drawer !== d.drawer && pe?.[0] === pd?.[0] && pe?.[1] > pd?.[1] && e.stage,
      `${d.drawer} ${pd} → ${e.drawer} ${pe} stage=${e.stage}`,
    );
    await ctx.key("ArrowUp");
    const f = await ctx.step("↑ in the details");
    check("↑ with the details: back to the event above", f.drawer === d.drawer, f);
    await ctx.key("Escape");
    const g = await ctx.step("Escape");
    check("Escape closes both", !g.drawer && !g.stage && g.url === "/", g);

    // Mid-page, nothing focused: ↓ focuses a card on screen, not under the pinned bar
    const height = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    const bad = [];
    for (const y of [0.25, 0.4, 0.55].map((k) => Math.round(height * k))) {
      await page.evaluate((y) => {
        document.activeElement?.blur();
        scrollTo(0, y);
      }, y);
      await ctx.settle();
      await ctx.key("ArrowDown");
      const fc = await focusedCard(page);
      ctx.log(`↓ at y=${y}`, fc ?? (await ctx.snap()));
      // a period's button can be what comes first: that's fine too
      const s = await ctx.snap();
      if (!fc && !s.focus.startsWith("[")) bad.push(`y=${y}: focus ${s.focus}`);
      else if (fc && (!fc.onScreen || fc.coveredBy))
        bad.push(`y=${y}: ${fc.id.slice(0, 24)} on screen ${fc.onScreen}, covered by ${fc.coveredBy}`);
    }
    check("↓ mid-page: a card on screen, clear of the bar", !bad.length, bad.join("; "));

    // The Cuándo menu keeps its arrows
    await ctx.goto("/");
    const when = page.locator('[aria-haspopup="menu"]').first();
    if ((await when.count()) && (await when.isVisible())) {
      await when.click();
      await ctx.settle();
      await ctx.key("ArrowDown");
      const m = await page.evaluate(() => ({
        role: document.activeElement?.getAttribute("role"),
        inCard: Boolean(document.activeElement?.closest("[data-event-card]")),
      }));
      ctx.log("Cuándo open, ↓", m);
      check("the Cuándo menu keeps ↓", /^menuitem/.test(m.role ?? "") && !m.inCard, m);
      await ctx.key("Escape");
    } else ctx.skip("Cuándo menu", "no menu button visible");

    // The calendar: a day with events (today's, or the next one with two or more), then ↓ from nothing
    await ctx.goto("/calendario/");
    if (!(await ctx.cards().count())) {
      const day = await page.evaluate(() => {
        const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/Bogota" });
        return [...document.querySelectorAll("button[data-day]")].find(
          (b) => b.dataset.day >= today && b.querySelectorAll(".cal-pill").length >= 2,
        )?.dataset.day;
      });
      if (day) {
        await page.locator(`button[data-day="${day}"]`).click();
        await page.evaluate(() => document.activeElement?.blur());
        await ctx.settle();
        ctx.log(`calendar: picked ${day}`);
      }
    }
    if ((await ctx.cards().count()) < 2) ctx.skip("calendar", "no day with two events ahead");
    else {
      await ctx.key("ArrowDown");
      const k1 = await ctx.step("calendar ↓");
      const fc1 = await focusedCard(page);
      await ctx.key("ArrowRight");
      const k2 = await ctx.step("calendar →");
      const fc2 = await focusedCard(page);
      check("calendar: ↓ reaches a card on screen", fc1?.onScreen && !fc1.coveredBy, fc1 ?? k1);
      check(
        "calendar: → the next card, on screen",
        focusedCardId(k2) && focusedCardId(k2) !== focusedCardId(k1) && fc2?.onScreen,
        `${k1.focus} → ${k2.focus} ${JSON.stringify(fc2)}`,
      );
    }
  },
};
