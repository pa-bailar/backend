// ↓ all the way down the list on a desktop (the owner, 6 Oct): the arrows go on past the cards to the summarized
// periods ("Ver los 23 eventos", "Ver 7 más"), Enter opens one and the focus lands on its first new event, the walk
// reaches the list's last card, and the focus never leaves the screen. Then back folds a period again.
import { Skip } from "../lib.mjs";

const focusInfo = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    // a card's focus shows on the whole card (its link, the title, can sit below the fold while the card is in view)
    const r = (a?.closest("[data-event-card]") ?? a)?.getBoundingClientRect();
    return {
      button: a?.dataset.showPeriod ?? null,
      period: a?.closest("[data-period]")?.dataset.period ?? null,
      card: a?.closest("[data-event-card]")?.dataset.eventCard ?? null,
      visible: r ? r.top < innerHeight && r.bottom > 0 : false,
    };
  });
const periodCards = (page, period) =>
  page.evaluate(
    (p) =>
      [...document.querySelectorAll(`#view-upcoming [data-period="${p}"] [data-event-card]`)].map(
        (c) => c.dataset.eventCard,
      ),
    period,
  );

export default {
  name: "walk",
  summary:
    "↓ through the whole list on a desktop: every period's button opens it, focus on its first new event, to the end",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("the arrows are a desktop's");
    await ctx.goto("/");
    const start = await ctx.step("start");
    if (!(await ctx.cards().count())) throw new Skip("no events on the list");
    if (!start.folded.length) ctx.skip("periods' buttons", "no folded period in today's data");

    await ctx.key("ArrowDown");
    const opened = [];
    const badLanding = [];
    const offScreen = [];
    let last = null;
    let stuck = 0;
    for (let i = 0; i < 500; i++) {
      const f = await focusInfo(page);
      if (!f.visible) offScreen.push(f.button ? `[${f.button}]` : (f.card?.slice(0, 24) ?? "?"));
      if (f.button) {
        const before = await periodCards(page, f.button);
        await ctx.key("Enter");
        const s = await ctx.step(`Enter on [${f.button}]`);
        const g = await focusInfo(page);
        opened.push(f.button);
        if (s.folded.includes(f.button) || g.period !== f.button || !g.card || before.includes(g.card))
          badLanding.push(`${f.button}: focus ${g.card?.slice(0, 24) ?? s.focus} in ${g.period}`);
        continue;
      }
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
    if (start.folded.length) {
      check(
        "every period's button reached and opened",
        opened.length === start.folded.length && !end.folded.length,
        `opened ${opened.join(",")} of ${start.folded.join(",")}`,
      );
      check("Enter on a button: focus on its first new event", !badLanding.length, badLanding.join("; "));
    }
    check("the walk reaches the list's last card", last === lastCard, `ended on ${last} | last ${lastCard}`);
    check("the focus never leaves the screen", !offScreen.length, offScreen.join(", "));

    if (opened.length) {
      await ctx.back();
      const b = await ctx.step("back");
      check(
        "back folds the last period opened again, on the list",
        b.url === "/" && b.folded.includes(opened.at(-1)),
        b,
      );
    }
  },
};
