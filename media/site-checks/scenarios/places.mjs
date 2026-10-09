// Where the keys start and the page keeping its place (the bug-squash pass of 6 Oct, site #145; the code-quality pass
// of 7 Oct): a click in the list's gaps or a card clicked (Safari doesn't focus it) leaves the arrows a start; the
// skip link too; scrolled away from the card in focus, an arrow starts on screen; closing the side panel keeps what
// the visitor sees; Escape in the toolbar's search ends it, and the next one closes the panel; Enter on a month's block
// ("Ver los 22 eventos") moves the panel to the first new event, and so does Space. From deep in the list, Guardados
// and a search start at the top, under the toolbar (site #167: the sticky toolbar read 0 once pinned, and the page never went back up).
// Desktop, 1366 × 768 or the device's size.
import { Skip, VIEW, fmt, focusedCardId } from "../lib.mjs";

/** The first two cards side by side under the toolbar, and the gap between them, after scrolling to `y`. */
const gapAt = (page, y) =>
  page.evaluate(
    ({ VIEW, y }) => {
      window.scrollTo(0, y);
      const cards = [...document.querySelectorAll(`${VIEW} [data-event-card]`)].filter((c) => {
        const r = c.getBoundingClientRect();
        return r.top > 120 && r.top < innerHeight - 160;
      });
      const a = cards[0];
      const b = a && cards.find((c) => c !== a && Math.abs(c.getBoundingClientRect().top - a.getBoundingClientRect().top) < 2);
      if (!a || !b) return null;
      const [ra, rb] = [a.getBoundingClientRect(), b.getBoundingClientRect()];
      return { x: (ra.right + rb.left) / 2, y: ra.top + 60 };
    },
    { VIEW, y },
  );

/** The list's first piece in sight (a card, a heading, a block), marked, and its top: what closing keeps in place. */
const markAnchor = (page) =>
  page.evaluate((VIEW) => {
    const bar = document.querySelector(".toolbar")?.getBoundingClientRect().bottom ?? 0;
    const pieces = [...document.querySelectorAll(`${VIEW} [data-event-card], ${VIEW} .agenda-group__header, ${VIEW} [data-show-period]`)]
      .filter((e) => e.getClientRects().length)
      .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    const piece = pieces.find((e) => {
      const r = e.getBoundingClientRect();
      return r.bottom > bar && r.top < innerHeight;
    });
    piece?.setAttribute("data-check-anchor", "");
    return piece ? Math.round(piece.getBoundingClientRect().top) : null;
  }, VIEW);
const anchorTop = (page) =>
  page.evaluate(() => Math.round(document.querySelector("[data-check-anchor]")?.getBoundingClientRect().top ?? NaN));

/** The bottom of the pinned toolbar, and the top of the view's content (<main>), on screen. */
const tops = (page) =>
  page.evaluate(() => ({
    toolbar: Math.round(document.querySelector(".toolbar").getBoundingClientRect().bottom),
    main: Math.round(document.querySelector("main").getBoundingClientRect().top),
    y: Math.round(scrollY),
  }));
/** The view's content starts at its top: right under the toolbar (2 px for rounding), high on the first screen. */
const atTheTop = ({ toolbar, main }) => main >= toolbar - 2 && main < 400;

/** The stop in focus (a card or a block): its top on screen, or null. */
const focusedStopTop = (page) =>
  page.evaluate(() => {
    const stop = document.activeElement?.closest("[data-event-card], [data-show-period]");
    return stop ? Math.round(stop.getBoundingClientRect().top) : null;
  });

export default {
  name: "places",
  summary: "where the keys start (a click, the skip link, scrolled away) and the page keeping its place (closing, Escape, a month's block)",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("the keyboard and the side panel are a desktop's");
    await ctx.goto("/");
    if ((await ctx.cards().count()) < 6) throw new Skip("fewer than 6 events on the list");

    // A click in the gap between two cards, then ↓: a card on screen, the side panel on it (<main> never took the focus)
    const gap = await gapAt(page, 900);
    if (!gap) return ctx.skip("a click in a gap", "no two cards side by side on screen");
    await page.mouse.click(gap.x, gap.y);
    const clicked = await ctx.snap();
    check("a click in the list's gaps focuses nothing", clicked.focus === "body", clicked);
    await ctx.key("ArrowDown");
    await ctx.settle();
    const down = await ctx.snap();
    check("…then ↓: a card on screen, the panel on it", focusedCardId(down) && down.drawer === focusedCardId(down), down);

    // A card's title clicked, Escape, →: the focus back on that card, then the next (Safari doesn't focus on a click)
    await ctx.goto("/");
    const second = await ctx.cards().nth(1).getAttribute("data-event-card");
    await ctx.cards().nth(1).locator("a.event-card__hit").click();
    await ctx.settle();
    await ctx.key("Escape");
    await ctx.settle();
    const escaped = await ctx.snap();
    check("a card clicked, then Escape: the focus back on it", escaped.focus === `card:${second}`, escaped);
    await ctx.key("ArrowRight");
    await ctx.settle();
    const right = await ctx.snap();
    check("…then →: the next card, the panel on it", focusedCardId(right) !== second && right.drawer === focusedCardId(right), right);

    // The skip link (Chrome: Safari's Tab skips links by default), then ↓: <main> focused, then a card and the panel
    if (ctx.engine !== "webkit") {
      await ctx.goto("/");
      await ctx.key("Tab");
      await ctx.key("Enter");
      const skipped = await ctx.snap();
      check("the skip link focuses the list, no #contenido in the address", skipped.focus === "#contenido" && !skipped.url.includes("#"), skipped);
      await ctx.key("ArrowDown");
      await ctx.settle();
      const after = await ctx.snap();
      check("…then ↓: a card, the panel on it", focusedCardId(after) && after.drawer === focusedCardId(after), after);
    }

    // Scrolled away from the card in focus (the wheel), →: a stop on screen, no jump back up
    await ctx.goto("/");
    await ctx.key("ArrowDown");
    await ctx.settle();
    await page.mouse.move(300, 400);
    for (let i = 0; i < 5; i++) await page.mouse.wheel(0, 500);
    await page.waitForTimeout(600);
    const yAway = (await ctx.snap()).y;
    await ctx.key("ArrowRight");
    await ctx.settle();
    const away = await ctx.snap();
    const top = await focusedStopTop(page);
    check("scrolled away from the card in focus, →: a stop on screen, no jump back", away.y >= yAway - 200 && top !== null && top > -400 && top < 900, `y ${yAway} → ${away.y}, the stop's top ${top}`);

    // The panel open on a card, the page scrolled, the panel closed: what the visitor sees keeps its place
    await ctx.goto("/");
    await ctx.cards().nth(3).locator("a.event-card__hit").click();
    await ctx.settle();
    for (let i = 0; i < 6; i++) await page.mouse.wheel(0, 400);
    await page.waitForTimeout(600);
    const before = await markAnchor(page);
    await page.click("#event-drawer .drawer__close");
    await ctx.settle();
    const after = await anchorTop(page);
    check("closing the panel after scrolling: what's seen keeps its place", before !== null && Math.abs(after - before) <= 3, `${before} → ${after}`);

    // Escape in the toolbar's search with the panel open: the search ends, the panel stays; the next Escape closes it
    await ctx.goto("/");
    await ctx.key("ArrowDown");
    await ctx.settle();
    await page.click(".toolbar [data-search]");
    await page.keyboard.type("salsa");
    await page.waitForTimeout(400);
    await ctx.key("Escape");
    await ctx.settle();
    const first = await page.evaluate(() => ({ search: document.querySelector(".toolbar [data-search]").value, panel: Boolean(document.querySelector("#event-drawer[open]")) }));
    check("Escape in the search ends it, the panel stays", first.search === "" && first.panel, first);
    await ctx.key("Escape");
    await ctx.settle();
    check("…the next Escape closes the panel", !(await ctx.snap()).drawer, await ctx.snap());

    // From deep in the list, Guardados (its tab) opens at its top, under the toolbar, not at the page's bottom
    await ctx.goto("/");
    await page.evaluate(() => window.scrollTo(0, 3000));
    await ctx.settle();
    await page.click('.toolbar [role="tab"][data-view="saved"]');
    await ctx.settle();
    const saved = await tops(page);
    check("from deep in the list, Guardados opens at its top", atTheTop(saved), saved);

    // From deep in the list, a search's results start on screen, under the toolbar
    await ctx.goto("/");
    await page.evaluate(() => window.scrollTo(0, 3000));
    await ctx.settle();
    await page.click(".toolbar [data-search]");
    await page.keyboard.type("salsa");
    await page.waitForTimeout(500); // the results come after a pause in the typing (150 ms, main.ts), then the scroll
    await ctx.settle();
    const searched = await tops(page);
    check("from deep in the list, a search's results start at the top", atTheTop(searched), searched);

    // Enter on a month's block with the panel open: the panel on the first new event, the focus there
    await ctx.goto("/");
    if (!(await page.locator(`${VIEW} [data-show-period]`).count())) return ctx.skip("Enter and Space on a block", "no folded period today");
    await ctx.key("ArrowDown");
    await ctx.settle();
    await page.evaluate((VIEW) => document.querySelector(`${VIEW} [data-show-period]`).focus(), VIEW);
    await ctx.key("Enter");
    await ctx.settle();
    const more = await ctx.snap();
    check("Enter on a block: the panel on the new card in focus", focusedCardId(more) && more.drawer === focusedCardId(more), more);

    // Space does the same as Enter: the new card on screen, the panel on it (it was left 184 px above, the panel behind)
    await ctx.goto("/");
    await ctx.key("ArrowDown");
    await ctx.settle();
    await page.evaluate((VIEW) => document.querySelector(`${VIEW} [data-show-period]`).focus(), VIEW);
    await ctx.key("Space");
    await ctx.settle();
    const spaced = await ctx.snap();
    const spacedTop = await focusedStopTop(page);
    check(
      "Space on a block: the new card in focus, on screen, the panel on it",
      focusedCardId(spaced) && spaced.drawer === focusedCardId(spaced) && spacedTop !== null && spacedTop >= 0,
      `${fmt(spaced)}, the stop's top ${spacedTop}`,
    );
  },
};
