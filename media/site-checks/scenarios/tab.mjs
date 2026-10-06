// Tab on a desktop (the owner, 6 Oct): the list is one Tab stop, the selected card. Tab from the toolbar lands on it;
// on it, Tab goes through its own controls, then into the side panel when it's open, then out of the list (no other
// card on the way); Shift+Tab from the panel's start goes back to the card the panel shows; Tab and the arrows agree.
import { Skip } from "../lib.mjs";

/** Where the focus is: "card:<id>" (the card itself), "card:<id>/control", "panel", or the element's name. */
const where = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return "body";
    if (a.closest("#event-drawer")) return "panel";
    const card = a.closest("[data-event-card]")?.dataset.eventCard;
    if (card) return a.matches("a.event-card__hit") ? `card:${card}` : `card:${card}/control`;
    if (a.closest(".toolbar")) return "toolbar";
    return (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().slice(0, 30);
  });

/** The focus on the toolbar's last visible control (where Tab into the list starts). */
const toToolbarEnd = (page) =>
  page.evaluate(() => {
    const visible = [...document.querySelectorAll(".toolbar button, .toolbar input")].filter(
      (e) => e.getClientRects().length && e.tabIndex >= 0 && !e.closest("[hidden], [role=menu], dialog"),
    );
    visible.at(-1)?.focus();
    return visible.at(-1)?.textContent?.trim() || visible.at(-1)?.getAttribute("aria-label");
  });

export default {
  name: "tab",
  summary: "Tab on a desktop: the list is one stop (the selected card), then its controls, the panel, out; agrees with the arrows",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("Tab with a keyboard is a desktop's");
    await ctx.goto("/");
    const cards = ctx.cards();
    if ((await cards.count()) < 3) throw new Skip("fewer than 3 events on the list");
    const first = await cards.nth(0).getAttribute("data-event-card");

    // From the toolbar's last control, Tab: past the period's share button, onto the first card (the selected one)
    await toToolbarEnd(page);
    const path = [];
    for (let i = 0; i < 4 && !path.at(-1)?.startsWith("card:"); i++) {
      await ctx.key("Tab");
      path.push(await where(page));
    }
    check("Tab from the toolbar lands on the selected card", path.at(-1) === `card:${first}`, path.join(" → "));

    // Its controls, then out of the list: never another card's
    const walk = [];
    for (let i = 0; i < 12; i++) {
      await ctx.key("Tab");
      walk.push(await where(page));
    }
    const left = walk.findIndex((w) => !w.startsWith(`card:${first}`));
    const others = walk.filter((w) => w.startsWith("card:") && !w.startsWith(`card:${first}`));
    check("Tab goes through the card's own controls first", left > 1, walk.slice(0, left + 1).join(" → "));
    check("…then out of the list, past every other card", !others.length, others.join(", ") || walk.join(" → "));

    // The arrows move the selection: Tab from the toolbar now lands there
    await cards.nth(0).locator("a.event-card__hit").focus();
    await ctx.key("ArrowRight");
    const second = await cards.nth(1).getAttribute("data-event-card");
    await page.keyboard.press("Escape"); // the reading pane closes; the selection stays
    await ctx.settle();
    await toToolbarEnd(page);
    let landed = "";
    for (let i = 0; i < 4 && !landed.startsWith("card:"); i++) {
      await ctx.key("Tab");
      landed = await where(page);
    }
    check("after → the selection moved: Tab lands on the second card", landed === `card:${second}`, landed);

    // With the side panel open: past the card's controls into the panel; Shift+Tab from its start back to the card
    await cards.nth(1).locator("a.event-card__hit").focus();
    await ctx.key("ArrowLeft"); // the reading pane opens on the first card
    await ctx.settle();
    const open = await ctx.snap();
    if (!open.drawer) return ctx.skip("the panel", "the reading pane didn't open (a narrow window?)");
    let reached = "";
    for (let i = 0; i < 10 && reached !== "panel"; i++) {
      await ctx.key("Tab");
      reached = await where(page);
    }
    check("past the card's controls, Tab goes into the open side panel", reached === "panel", reached);
    await ctx.key("ArrowRight"); // in the panel: the next event
    await ctx.settle();
    const moved = await ctx.snap();
    await page.evaluate(() => document.getElementById("drawer-title")?.focus());
    await ctx.key("Shift+Tab");
    const backTo = await where(page);
    check(
      "Shift+Tab from the panel's start: back to the card it shows (its last control)",
      backTo === `card:${moved.drawer}/control`,
      `${backTo} (panel shows ${moved.drawer})`,
    );
  },
};
