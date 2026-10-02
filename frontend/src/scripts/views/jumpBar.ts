// Phones only (CSS hides it where the toolbar is sticky): one slim row stuck to the top of the screen,
// like the filter bars of Google Maps or Airbnb, and the only way to the filters there (the toolbar's
// chip rows are hidden on phones, toolbar.css):
//   [⚙ 2]  [Finde ▾]  |  Salsa · Bachata · Salsa caleña …
//   - ⚙ opens the filter sheet; the number is how many filters are active.
//   - "Finde ▾" names the period on screen (scroll-spy) and opens a menu to jump to another one.
//   - Rhythm chips, most frequent first: one tap filters, another tap clears.
// Like Instagram's header, the bar hides while scrolling down and comes back on any scroll up.

import type { AgendaGroup } from "../state";
import { byId, escapeHtml } from "../lib/dom";
import { capitalize } from "../lib/format";
import { ICONS } from "../lib/icons";
import { dismissSheet, initSheet } from "../lib/sheet";

const SCROLL_THRESHOLD = 8; // px of movement before reacting, so small jitters don't toggle the bar
const BAND_TOP = 64; // px: just below the bar (--jump-bar-height + a little)
const ALWAYS_SHOWN_ABOVE = 200; // px from the top of the page where the bar never hides

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let observer: IntersectionObserver | null = null;
let jumping = false; // a jump scrolls on purpose: don't hide the bar or move the highlight meanwhile
let groups: AgendaGroup[] = [];

export function sectionId(group: AgendaGroup): string {
  return `periodo-${group.key}`;
}

export interface JumpBarContent {
  groups: AgendaGroup[]; // periods of the upcoming list (none in the calendar)
  activeFilters: number;
  styles: string[]; // rhythm chips, most frequent first
  styleFilter: string;
}

/** The period on screen: its name on the period button, and marked in the menu. */
function setActive(key: string) {
  const group = groups.find((item) => item.key === key);
  if (!group) return;
  byId("jump-period-label").textContent = group.shortLabel;
  byId("jump-period-menu")
    .querySelectorAll<HTMLElement>("[data-jump]")
    .forEach((item) => item.toggleAttribute("aria-current", item.dataset.jump === key));
}

function atPageBottom(): boolean {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
}

/**
 * The edges of the page, where no section crosses the band: above the list the first period is
 * current; at the very bottom, the last period on screen (it can't scroll up to the band).
 */
function highlightAtEdges() {
  if (jumping || !groups.length) return;
  const first = document.getElementById(sectionId(groups[0]));
  if (first && first.getBoundingClientRect().top > BAND_TOP) {
    setActive(groups[0].key);
    return;
  }
  if (!atPageBottom()) return;
  const onScreen = groups.filter((group) => {
    const section = document.getElementById(sectionId(group));
    return section && section.getBoundingClientRect().top < window.innerHeight;
  });
  if (onScreen.length) setActive(onScreen[onScreen.length - 1].key);
}

/** Scroll-spy: the period whose section is at the top of the screen is the current one. */
function watchSections() {
  observer?.disconnect();
  const visible = new Set<string>();
  const order = groups.map((group) => group.key);
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const key = (entry.target as HTMLElement).dataset.period!;
        if (entry.isIntersecting) visible.add(key);
        else visible.delete(key);
      }
      // When two periods share the band, the one arriving (lower on the page) is the one being read.
      const current = order.findLast((key) => visible.has(key));
      if (current && !jumping && !atPageBottom()) setActive(current);
    },
    // A band just below the bar: the section crossing it is the one being read.
    { rootMargin: `-${BAND_TOP}px 0px -65% 0px` },
  );
  groups.forEach((group) => observer!.observe(byId(sectionId(group))));
}

export function renderJumpBar(content: JumpBarContent) {
  groups = content.groups;
  byId("jump-bar").hidden = false;

  const filters = byId("jump-filters");
  const count = content.activeFilters;
  filters.innerHTML = `${ICONS.sliders}${count ? `<span class="jump-bar__badge">${count}</span>` : ""}`;
  filters.setAttribute("aria-label", count ? `Filtros, ${count} activos` : "Filtros");

  // The period menu only makes sense with two or more periods.
  byId("jump-period").hidden = groups.length < 2;
  byId("jump-period-menu").innerHTML = groups
    .map(
      (group) => `
        <button class="period-menu__item" type="button" data-jump="${escapeHtml(group.key)}">
          <span>${escapeHtml(group.label)}</span><span class="period-menu__count">${group.events.length}</span>
        </button>`,
    )
    .join("");

  byId("jump-styles").innerHTML = content.styles
    .map((style) => {
      const active = style === content.styleFilter;
      return `<button class="chip" type="button" data-style="${escapeHtml(style)}" aria-pressed="${active}">${escapeHtml(capitalize(style))}</button>`;
    })
    .join("");

  if (groups.length) setActive(groups[0].key);
  watchSections();
}

function jumpTo(key: string) {
  const section = document.getElementById(`periodo-${key}`);
  if (!section) return;
  jumping = true;
  section.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  section.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true }); // screen readers follow the jump
  setActive(key);
  const done = () => (jumping = false);
  if ("onscrollend" in window) window.addEventListener("scrollend", done, { once: true });
  else setTimeout(done, 800);
}

/** ⚙: the filter sheet slides up from the bottom; the list stays where it was behind it. */
function initFilterSheet() {
  const sheet = byId<HTMLDialogElement>("filter-sheet");
  sheet.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    // "Ver N eventos", × or a tap on the backdrop (the dialog element itself) closes it.
    if (target === sheet || target.closest("[data-close-sheet]")) dismissSheet(sheet);
  });
  // Drag it down to dismiss, from the top or whenever its content is scrolled to the top.
  initSheet(sheet, (target) => Boolean(target.closest(".filter-sheet__head")) || sheet.scrollTop <= 0);
}

/** Hide while scrolling down, show on any scroll up (and near the top, and when it holds focus). */
function initHideOnScroll() {
  const bar = byId("jump-bar");
  const menu = byId("jump-period-menu");
  let lastY = window.scrollY;
  let ticking = false;
  const update = () => {
    ticking = false;
    const y = window.scrollY;
    const delta = y - lastY;
    if (Math.abs(delta) < SCROLL_THRESHOLD) return;
    highlightAtEdges();
    if (!jumping && menu.matches(":popover-open")) menu.hidePopover(); // the menu belongs to the bar
    const hide = delta > 0 && y > ALWAYS_SHOWN_ABOVE && !jumping && !bar.contains(document.activeElement);
    bar.classList.toggle("is-hidden", hide);
    lastY = y;
  };
  window.addEventListener(
    "scroll",
    () => {
      if (!ticking) requestAnimationFrame(update);
      ticking = true;
    },
    { passive: true },
  );
  bar.addEventListener("focusin", () => bar.classList.remove("is-hidden"));
}

export function initJumpBar() {
  byId("jump-filters").addEventListener("click", () => byId<HTMLDialogElement>("filter-sheet").showModal());
  const menu = byId("jump-period-menu");
  // Open the menu right under its button, wherever the bar is on the screen.
  menu.addEventListener("beforetoggle", (toggle) => {
    if ((toggle as ToggleEvent).newState !== "open") return;
    const button = byId("jump-period").getBoundingClientRect();
    menu.style.top = `${button.bottom + 4}px`;
    menu.style.left = `${button.left}px`;
  });
  menu.addEventListener("click", (domEvent) => {
    const item = (domEvent.target as HTMLElement).closest<HTMLElement>("[data-jump]");
    if (!item) return;
    byId("jump-period-menu").hidePopover();
    jumpTo(item.dataset.jump!);
  });
  initHideOnScroll();
  initFilterSheet();
}
