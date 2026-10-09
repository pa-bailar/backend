// Tab on a desktop: one stop per event (the owner, 6 Oct). From the toolbar, Tab walks the list in its reading order,
// each event once (never one of its own buttons), the periods' Compartir where they are, the side panel following
// each event, then the footer, and out of the page (never into the panel, never round
// again). Enter goes into the panel; past its last control Tab goes on to the next event; Shift+Tab from its start
// goes back to the event it shows; Escape closes it; Shift+Tab walks the list back like ←. WebKit checks Safari's
// default: its Tab skips links (the cards, the footer's) unless "Press Tab to highlight each item" is on, which a test
// can't turn on (nor Option+Tab, a Mac-only shortcut): the buttons only, in order, and never stuck or into the panel.
import { Skip } from "../lib.mjs";

/** Where the focus is: "card:<id>", "control:<id>" (one of a card's own), "panel", "page" or the element's name. */
const where = (page) =>
  page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return "page";
    if (a.closest("#event-drawer, #lightbox")) return "panel";
    const card = a.closest("[data-event-card]")?.dataset.eventCard;
    if (card) return a.matches("a.event-card__hit") ? `card:${card}` : `control:${card}`;
    return (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().replace(/\s+/g, " ").slice(0, 30);
  });

/** The list's stops in its reading order, as Tab should meet them: cards and the periods' share buttons. */
const expectedStops = (page) =>
  page.evaluate(() => {
    const view = document.querySelector('[role="tabpanel"]:not([hidden])');
    return [...view.querySelectorAll("a.event-card__hit, .agenda-group__header button")]
      .filter((e) => e.getClientRects().length > 0)
      .map((e) => (e.matches("a.event-card__hit") ? `card:${e.closest("[data-event-card]").dataset.eventCard}` : (e.getAttribute("aria-label") || e.textContent).trim().replace(/\s+/g, " ").slice(0, 30)));
  });

/** The focus on the toolbar's last visible control (where Tab into the list starts). */
const toToolbarEnd = (page) =>
  page.evaluate(() => {
    const visible = [...document.querySelectorAll(".toolbar button, .toolbar input")].filter(
      (e) => e.getClientRects().length && e.tabIndex >= 0 && !e.closest("[hidden], [role=menu], dialog"),
    );
    visible.at(-1)?.focus();
  });

export default {
  name: "tab",
  summary: "Tab on a desktop: each event once in reading order (the panel follows), blocks, footer, out; Enter/Esc/Shift+Tab with the panel",
  devices: ["desktop"],
  async run(ctx) {
    const { page, check } = ctx;
    if (ctx.touch) throw new Skip("Tab with a keyboard is a desktop's");
    const TAB = "Tab";
    const BACK = "Shift+Tab";
    const linksTabbable = ctx.engine !== "webkit"; // Safari's default (see the header)
    await ctx.goto("/");
    const all = await expectedStops(page);
    const expected = linksTabbable ? all : all.filter((s) => !s.startsWith("card:"));
    if (all.filter((s) => s.startsWith("card:")).length < 3) throw new Skip("fewer than 3 events on the list");

    // The whole walk: the list's stops in order, the panel following every event, then the footer and out
    await toToolbarEnd(page);
    const walk = [];
    const panelWrong = [];
    for (let i = 0; i < expected.length + 12; i++) {
      await page.keyboard.press(TAB);
      await page.waitForTimeout(60);
      const w = await where(page);
      walk.push(w);
      if (w.startsWith("card:")) {
        const s = await ctx.snap();
        if (s.drawer !== w.slice(5)) panelWrong.push(`${w.slice(5, 30)} (panel: ${s.drawer})`);
      }
      if (w === "page") break;
    }
    const inList = walk.slice(0, expected.length);
    check(linksTabbable ? "Tab meets every event and block in reading order, nothing else" : "Safari's default Tab: the list's buttons in order (its links need its setting)", JSON.stringify(inList) === JSON.stringify(expected), `${inList.length} of ${expected.length}; first difference at ${inList.findIndex((w, i) => w !== expected[i])}: ${inList.find((w, i) => w !== expected[i])}`);
    check("never one of a card's own buttons", !walk.some((w) => w.startsWith("control:")), walk.filter((w) => w.startsWith("control:")).join(", "));
    check("the side panel follows each event Tab lands on", !panelWrong.length, panelWrong.slice(0, 3).join("; "));
    check("after the list, the footer, then out of the page (not into the panel, not round again)", walk.at(-1) === "page" && !walk.includes("panel"), walk.slice(expected.length).join(" → "));

    // Enter: into the panel. Past its last control: on to the next event. Shift+Tab from its start: back to the event.
    if (!linksTabbable) return ctx.skip("the panel by Tab", "Safari tabs to links only with its setting, which a test can't turn on");
    await ctx.goto("/");
    await toToolbarEnd(page);
    let at = "";
    for (let i = 0; i < 4 && !at.startsWith("card:"); i++) {
      await ctx.key(TAB);
      at = await where(page);
    }
    const first = at.slice(5);
    const second = expected.filter((s) => s.startsWith("card:"))[1]?.slice(5);
    await ctx.key("Enter");
    await ctx.settle();
    check("Enter on an event goes into the panel", (await where(page)) === "panel", await where(page));
    let out = "panel";
    for (let i = 0; i < 25 && out === "panel"; i++) {
      await ctx.key(TAB);
      out = await where(page);
    }
    check("past the panel's last control, Tab goes on to the next event", out === `card:${second}`, `${out} (expected card:${second})`);
    const followed = await ctx.snap();
    check("…and the panel follows it", followed.drawer === second, followed.drawer);
    await page.evaluate(() => document.getElementById("drawer-title")?.focus());
    await ctx.key(BACK);
    check("Shift+Tab from the panel's start: back to the event it shows", (await where(page)) === `card:${second}`, await where(page));
    await ctx.key(BACK);
    check("Shift+Tab walks the list back like ←", (await where(page)) === `card:${first}`, await where(page));
    await ctx.key("Escape");
    await ctx.settle();
    const closed = await ctx.snap();
    check("Escape closes the panel, the focus stays on the event", !closed.drawer && (await where(page)) === `card:${first}`, `${await where(page)} drawer=${closed.drawer}`);
    await ctx.key(TAB);
    const reopened = await ctx.snap();
    check("the next Tab: the next event, the panel open on it again", (await where(page)) === `card:${second}` && reopened.drawer === second, `${await where(page)} drawer=${reopened.drawer}`);
  },
};
