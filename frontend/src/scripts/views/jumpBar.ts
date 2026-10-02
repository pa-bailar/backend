// Phones only (CSS hides it where the toolbar is sticky): a slim bar stuck to the top of the screen with
// a "Filtros" button (opens the filter sheet) and one chip per period ("Hoy · Finde · Próx. semana · Nov").
//   - Tapping a chip jumps to that period; the chip of the period on screen is highlighted (scroll-spy).
//   - Like Instagram's header, the bar hides while scrolling down and comes back on any scroll up.

import type { AgendaGroup } from "../state";
import { byId, escapeHtml } from "../lib/dom";

const SCROLL_THRESHOLD = 8; // px of movement before reacting, so small jitters don't toggle the bar
const BAND_TOP = 64; // px: just below the bar (--jump-bar-height + a little)
const ALWAYS_SHOWN_ABOVE = 200; // px from the top of the page where the bar never hides

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let observer: IntersectionObserver | null = null;
let jumping = false; // a jump scrolls on purpose: don't hide the bar or move the highlight meanwhile
let periodKeys: string[] = [];

export function sectionId(group: AgendaGroup): string {
  return `periodo-${group.key}`;
}

function setActive(key: string) {
  const periods = byId("jump-periods");
  periods.querySelectorAll<HTMLElement>("[data-jump]").forEach((chip) => {
    const active = chip.dataset.jump === key;
    if (active) {
      chip.setAttribute("aria-current", "true");
      // Keep the active chip visible inside the horizontally scrolling row (never scrolls the page).
      const left = chip.offsetLeft - periods.clientWidth / 2 + chip.offsetWidth / 2;
      periods.scrollTo({ left, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    } else {
      chip.removeAttribute("aria-current");
    }
  });
}

function atPageBottom(): boolean {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
}

/**
 * The edges of the page, where no section crosses the band: above the list the first period is
 * highlighted; at the very bottom, the last period on screen (it can't scroll up to the band).
 */
function highlightAtEdges() {
  if (jumping || !periodKeys.length) return;
  const first = document.getElementById(`periodo-${periodKeys[0]}`);
  if (first && first.getBoundingClientRect().top > BAND_TOP) {
    setActive(periodKeys[0]);
    return;
  }
  if (!atPageBottom()) return;
  const onScreen = periodKeys.filter((key) => {
    const section = document.getElementById(`periodo-${key}`);
    return section && section.getBoundingClientRect().top < window.innerHeight;
  });
  if (onScreen.length) setActive(onScreen[onScreen.length - 1]);
}

/** Scroll-spy: highlight the period whose section is at the top of the screen. */
function watchSections(groups: AgendaGroup[]) {
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

/** Renders the chips for the list's periods and the number of active filters. */
export function renderJumpBar(groups: AgendaGroup[], activeFilters: number) {
  const bar = byId("jump-bar");
  bar.hidden = false;
  byId("jump-periods").innerHTML = groups
    .map(
      (group) =>
        `<a class="chip jump-bar__chip" href="#${sectionId(group)}" data-jump="${escapeHtml(group.key)}">${escapeHtml(group.shortLabel)}</a>`,
    )
    .join("");
  const filters = byId("jump-filters");
  filters.textContent = activeFilters ? `Filtros · ${activeFilters}` : "Filtros";
  filters.setAttribute("aria-label", activeFilters ? `Filtros, ${activeFilters} activos` : "Filtros");
  periodKeys = groups.map((group) => group.key);
  if (groups.length) setActive(groups[0].key);
  watchSections(groups);
}

export function hideJumpBar() {
  observer?.disconnect();
  byId("jump-bar").hidden = true;
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

/** Filtros: the filter sheet slides up from the bottom; the list stays where it was behind it. */
function initFilterSheet() {
  const sheet = byId<HTMLDialogElement>("filter-sheet");
  sheet.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    // "Ver N eventos", × or a tap on the backdrop (the dialog element itself) closes it.
    if (target === sheet || target.closest("[data-close-sheet]")) sheet.close();
  });
}

/** Hide while scrolling down, show on any scroll up (and near the top, and when it holds focus). */
function initHideOnScroll() {
  const bar = byId("jump-bar");
  let lastY = window.scrollY;
  let ticking = false;
  const update = () => {
    ticking = false;
    const y = window.scrollY;
    const delta = y - lastY;
    if (Math.abs(delta) < SCROLL_THRESHOLD) return;
    highlightAtEdges();
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
  byId("jump-bar").addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    const chip = target.closest<HTMLElement>("[data-jump]");
    if (chip) {
      domEvent.preventDefault(); // the href works without JavaScript; with it, scroll smoothly and keep the URL
      jumpTo(chip.dataset.jump!);
    } else if (target.closest("#jump-filters")) {
      byId<HTMLDialogElement>("filter-sheet").showModal();
    }
  });
  initHideOnScroll();
  initFilterSheet();
}
