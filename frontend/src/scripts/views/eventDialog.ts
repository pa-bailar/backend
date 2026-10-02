// Event viewer on the home page: a dialog with one slide per event on screen, in list order.
//   - Swipe sideways (or ‹ ›, or the arrow keys) for the previous/next event; scroll up/down to read.
//   - Each event fills the width, like an Instagram post. Swiping is signaled by the "3 de 9" counter with
//     ‹ › and, until the visitor first swipes, a nudge that briefly shows the next event.
//   - Close with ×, Escape, the phone's back button, or by dragging it down (lib/sheet.ts); every way
//     of closing slides it away instead of making it vanish.
// The address bar shows the current event's own URL (/evento/<id>/): opening pushes it to the history,
// so "back" closes the viewer; swiping replaces it, so back still closes instead of stepping events.

import type { DanceEvent } from "../types";
import { byId } from "../lib/dom";
import { trackPageview } from "../lib/analytics";
import { eventPath } from "../lib/links";
import { dismissSheet, initSheet } from "../lib/sheet";
import { eventDetailHtml, handleMediaTabClick } from "./eventDetail";

const HINT_KEY = "swipe-hint-seen";
const SETTLE_DELAY = 120; // ms without scrolling that count as "the swipe ended"

let list: DanceEvent[] = [];
let index = 0;
let findEvent: (id: string) => DanceEvent | undefined = () => undefined;

interface HistoryState {
  eventId?: string;
}

const dialog = () => byId<HTMLDialogElement>("event-dialog");
const track = () => byId("viewer-track");
const slides = () => [...track().children] as HTMLElement[];
const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function slideHtml(event: DanceEvent, position: number): string {
  return `
    <article class="viewer-slide event-dialog__layout" data-slide="${position}" role="group"
      aria-roledescription="evento" aria-label="${position + 1} de ${list.length}">
      ${eventDetailHtml(event, 0, { headingLevel: 2, titleId: `event-title-${position}` })}
    </article>`;
}

function scrollToSlide(position: number, smooth: boolean) {
  const slide = slides()[position];
  if (!slide) return;
  const left = slide.offsetLeft - (track().clientWidth - slide.clientWidth) / 2;
  track().scrollTo({ left, behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto" });
}

/** Make `position` the current event: counter, arrows, URL, and only its slide reachable by keyboard. */
function setCurrent(position: number, { updateUrl }: { updateUrl: boolean }) {
  index = position;
  const event = list[position];
  byId("viewer-count").textContent = `${position + 1} de ${list.length}`;
  dialog().querySelector<HTMLButtonElement>('[data-step="-1"]')!.disabled = position === 0;
  dialog().querySelector<HTMLButtonElement>('[data-step="1"]')!.disabled = position === list.length - 1;
  dialog().setAttribute("aria-labelledby", `event-title-${position}`);
  slides().forEach((slide, i) => (slide.inert = i !== position));
  if (updateUrl) history.replaceState({ eventId: event.id } satisfies HistoryState, "", eventPath(event));
  trackPageview(eventPath(event), event.title); // which events people look at
}

function step(delta: number) {
  const next = Math.min(Math.max(index + delta, 0), list.length - 1);
  if (next === index) return;
  scrollToSlide(next, true);
  setCurrent(next, { updateUrl: true });
  markHintSeen();
}

/** After a swipe settles, the slide closest to the center is the current one. */
function onTrackScroll() {
  const center = track().scrollLeft + track().clientWidth / 2;
  let closest = index;
  slides().forEach((slide, i) => {
    const distance = Math.abs(slide.offsetLeft + slide.clientWidth / 2 - center);
    const best = Math.abs(slides()[closest].offsetLeft + slides()[closest].clientWidth / 2 - center);
    if (distance < best) closest = i;
  });
  if (closest !== index) {
    setCurrent(closest, { updateUrl: true });
    markHintSeen();
  }
}

// ---------- one-time swipe hint ----------

function hintSeen(): boolean {
  try {
    return localStorage.getItem(HINT_KEY) === "1";
  } catch {
    return true; // no storage (private mode…): don't nudge every time
  }
}

function markHintSeen() {
  try {
    localStorage.setItem(HINT_KEY, "1");
  } catch {
    // Not saved: the hint shows again next time, which is harmless.
  }
}

function maybeHint() {
  if (list.length < 2 || hintSeen() || prefersReducedMotion()) return;
  const hint = `is-hinting-${index < list.length - 1 ? "next" : "previous"}`;
  const stop = () => track().classList.remove(hint);
  track().classList.add(hint);
  track().addEventListener("animationend", stop, { once: true });
  dialog().addEventListener("touchstart", stop, { once: true, passive: true }); // the visitor took over
}

// ---------- open, close, history ----------

/** Opens `event`, with `events` (the list on screen, in order) as the slides to swipe through. */
export function openEventDialog(event: DanceEvent, events: DanceEvent[], { pushHistory = true } = {}) {
  list = events.some((item) => item.id === event.id) ? events : [event];
  const position = list.findIndex((item) => item.id === event.id);
  track().innerHTML = list.map(slideHtml).join("");
  if (!dialog().open) dialog().showModal();
  scrollToSlide(position, false);
  setCurrent(position, { updateUrl: false });
  if (pushHistory) history.pushState({ eventId: event.id } satisfies HistoryState, "", eventPath(event));
  maybeHint();
}

/** `find` looks an event up by id, to reopen it when the visitor goes forward in history. */
export function initEventDialog(find: (id: string) => DanceEvent | undefined) {
  findEvent = find;
  const element = dialog();

  element.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    const slide = target.closest<HTMLElement>("[data-slide]");
    if (slide) {
      const position = Number(slide.dataset.slide);
      const rerender = (selected: number) => {
        slide.innerHTML = eventDetailHtml(list[position], selected, {
          headingLevel: 2,
          titleId: `event-title-${position}`,
        });
      };
      if (handleMediaTabClick(slide, target, rerender)) return;
    }
    const stepButton = target.closest<HTMLElement>("[data-step]");
    if (stepButton) step(Number(stepButton.dataset.step));
    // Close on × or a tap on the backdrop (the dialog element itself).
    else if (target === element || target.closest("[data-close-dialog]")) dismissSheet(element);
  });

  element.addEventListener("keydown", (key) => {
    if (key.key === "ArrowRight") step(1);
    else if (key.key === "ArrowLeft") step(-1);
  });

  let settleTimer = 0;
  track().addEventListener(
    "scroll",
    () => {
      clearTimeout(settleTimer);
      settleTimer = window.setTimeout(onTrackScroll, SETTLE_DELAY);
    },
    { passive: true },
  );

  // Closed by ×, backdrop, Escape or pull-down: leave the event's URL the way the back button would.
  element.addEventListener("close", () => {
    if ((history.state as HistoryState | null)?.eventId) history.back();
  });

  // Back (or forward) button: follow the URL.
  window.addEventListener("popstate", (domEvent) => {
    const eventId = (domEvent.state as HistoryState | null)?.eventId;
    const event = eventId ? findEvent(eventId) : undefined;
    // Safari's edge swipe already animates going back: close at once instead of animating twice.
    const browserAnimated = (domEvent as PopStateEvent & { hasUAVisualTransition?: boolean }).hasUAVisualTransition;
    if (event) openEventDialog(event, list.length ? list : [event], { pushHistory: false });
    else if (element.open) dismissSheet(element, { instant: Boolean(browserAnimated) });
  });

  // Drag down from the top bar, or from the event when it's scrolled to the top.
  initSheet(element, (target) => Boolean(target.closest(".viewer-bar")) || (slides()[index]?.scrollTop ?? 0) <= 0);
}
