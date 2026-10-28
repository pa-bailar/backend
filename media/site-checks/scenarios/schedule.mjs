// A flyer's events of one day as one card with a schedule (the site, 28 Oct 2026): the flyer once and a row per event,
// each row its event's card. A row opens its own event and back closes it; the flyer opens the first; on a desktop ↓
// walks the rows one by one and then leaves the card, and ↓ from beside it never lands in its middle.
import { focusedCardId, Skip } from "../lib.mjs";

const SCHEDULE = '[role="tabpanel"]:not([hidden]) [data-flyer-card]';

export default {
  name: "schedule",
  summary: "a flyer's events of one day: one card, a row per event; rows open their own event; ↓ walks the rows",
  devices: ["phone", "desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    await ctx.goto("/");
    await ctx.step("start");
    const schedule = page.locator(SCHEDULE).first();
    if (!(await schedule.count())) throw new Skip("no flyer with several events on one day in today's data");

    const shape = await schedule.evaluate((card) => ({
      own: card.hasAttribute("data-event-card"),
      flyers: card.querySelectorAll(".event-card__flyer").length,
      rows: [...card.querySelectorAll(".schedule__row")].map((row) => ({
        id: row.dataset.eventCard ?? null,
        link: Boolean(row.querySelector("a.event-card__hit")),
        save: Boolean(row.querySelector("[data-save]")),
      })),
    }));
    const ids = shape.rows.map((row) => row.id);
    check(
      "one card: the flyer once, a row per event with its own link and Guardar",
      !shape.own && shape.flyers <= 1 && shape.rows.length >= 2 && shape.rows.every((r) => r.id && r.link && r.save),
      shape,
    );

    // A row opens its own event; back closes it.
    await ctx.tap(schedule.locator(".schedule__row a.event-card__hit").nth(1));
    const opened = await ctx.step("row 2");
    check("a row opens its own event", opened.drawer === ids[1], opened);
    await ctx.back();
    const closed = await ctx.step("back");
    check("back closes it, on the list", !closed.drawer && closed.url === "/", closed);

    // The flyer opens the first event (with a mouse on a wide screen, its image beside the details too).
    await ctx.tap(schedule.locator("[data-card-image]").first());
    const flyer = await ctx.step("flyer");
    check("the flyer opens the first event", flyer.drawer === ids[0], flyer);
    await ctx.key("Escape");
    if ((await ctx.step("Escape")).drawer) await ctx.back();

    if (ctx.touch) return ctx.skip("arrows", "the arrows are a desktop's");
    await schedule.locator(".schedule__row a.event-card__hit").first().focus();
    const walked = [];
    for (let i = 0; i < ids.length; i++) {
      await ctx.key("ArrowDown");
      walked.push(focusedCardId(await ctx.step(`↓ ${i + 1}`)));
    }
    check("↓ goes row by row", walked.slice(0, -1).every((id, i) => id === ids[i + 1]), { walked, ids });
    const after = walked.at(-1);
    check("↓ from the last row leaves the card", !ids.includes(after), { after, ids });

    // From the card before it (in reading order): beside it (another column), ↓ goes to the card below that one, never
    // into the schedule (before the fix, a schedule's short rows in a tall card were "the row below" the first column's
    // card: the site checks' arrows, 28 Oct 2026); right above it (the phones' feed, the same column), to its first row.
    const before = await schedule.evaluate((card) => {
      const all = [...document.querySelectorAll('[role="tabpanel"]:not([hidden]) [data-event-card]')];
      const prior = all.slice(0, all.indexOf(card.querySelector("[data-event-card]"))).filter((c) => !card.contains(c));
      const stop = prior.at(-1);
      if (!stop) return null;
      const outer = (stop.closest("[data-flyer-card]") ?? stop).getBoundingClientRect();
      return { id: stop.dataset.eventCard, sameColumn: Math.abs(outer.left - card.getBoundingClientRect().left) < 8 };
    });
    if (!before) return ctx.skip("↓ from the card before", "the schedule is the list's first card");
    await page.locator(`[role="tabpanel"]:not([hidden]) [data-event-card="${before.id}"] a.event-card__hit`).focus();
    await ctx.key("ArrowDown");
    const landed = focusedCardId(await ctx.step("↓ from the card before"));
    check(
      before.sameColumn ? "↓ from the card above enters at the first row" : "↓ from the card beside never lands in it",
      before.sameColumn ? landed === ids[0] : !ids.includes(landed),
      { before, landed, ids },
    );
  },
};
