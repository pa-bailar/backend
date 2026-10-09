// ↓ all the way down the list on a desktop (the owner, 6 Oct): the arrows go through every card (the list shows every
// event since 8 Oct 2026: no "Ver N más" to open on the way), the walk reaches the list's last card, and the focus
// never leaves the screen. Then back closes the reading pane the arrows opened, on the list.
import { Skip } from "../lib.mjs";

const focusInfo = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    // a card's focus shows on the whole card (its link, the title, can sit below the fold while the card is in view)
    const r = (a?.closest("[data-event-card]") ?? a)?.getBoundingClientRect();
    return {
      card: a?.closest("[data-event-card]")?.dataset.eventCard ?? null,
      visible: r ? r.top < innerHeight && r.bottom > 0 : false,
    };
  });

export default {
  name: "walk",
  summary: "↓ through the whole list on a desktop, card by card, to its last card, the focus always on screen",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("the arrows are a desktop's");
    await ctx.goto("/");
    await ctx.step("start");
    if (!(await ctx.cards().count())) throw new Skip("no events on the list");

    await ctx.key("ArrowDown");
    const offScreen = [];
    let last = null;
    let stuck = 0;
    for (let i = 0; i < 500; i++) {
      const f = await focusInfo(page);
      if (!f.visible) offScreen.push(f.card?.slice(0, 24) ?? "?");
      if (f.card === last) {
        if (++stuck > 2) break;
      } else stuck = 0;
      last = f.card;
      await ctx.key("ArrowDown");
    }
    const end = await ctx.step("end of the walk");
    const lastCard = await page.evaluate(
      () => [...document.querySelectorAll("#view-upcoming [data-event-card]")].at(-1)?.dataset.eventCard,
    );
    check("the walk reaches the list's last card", last === lastCard, `ended on ${last} | last ${lastCard}`);
    check("the focus never leaves the screen", !offScreen.length, offScreen.join(", "));

    if (end.drawer) {
      // The arrows opened the side panel on the way (the reading pane, 6 Oct): back closes it, on the list.
      await ctx.back();
      const closed = await ctx.step("back");
      check("back closes the reading pane, on the list", !closed.drawer && closed.url === "/", closed);
    }
  },
};
