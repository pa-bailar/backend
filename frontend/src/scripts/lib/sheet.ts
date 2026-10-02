// Bottom sheets (the event viewer on phones, the filter sheet), with the behavior of native ones
// (values from Material/iOS sheets and Apple's "fluid interfaces" guidance):
//   - drag down to dismiss: the sheet follows the finger 1:1, shrinks slightly and the backdrop fades
//     with it; dragging up past the top resists like a rubber band;
//   - on release it decides by velocity first, then distance: a flick down closes, a flick up cancels;
//   - closing continues from where the finger left it, at the finger's speed (a flick never slows down);
//   - every way of closing (×, Escape, back, drag) slides it away instead of making it vanish.
// The motion itself is CSS (styles/components/sheet.css): .sheet, .is-dragging, .is-closing, --drag.

const CLOSE_DISTANCE = 110; // px: minimum drag that closes on release…
const CLOSE_FRACTION = 0.22; // …or this share of the screen height, whichever is larger
const FLICK_DOWN = 0.5; // px/ms (500 px/s): a flick down this fast closes, however short
const FLICK_UP = -0.3; // px/ms: a flick back up cancels, however far it was dragged
const VELOCITY_WINDOW = 80; // ms of recent movement used to measure the release velocity
const EXIT_MIN = 160; // ms
const EXIT_MAX = 280; // ms
const EXIT_MIN_SPEED = 1.2; // px/ms: slow releases still leave briskly
const SHRINK = 0.04; // scale lost at full drag progress
const BACKDROP_FADE = 0.8; // backdrop opacity lost at full drag progress
const RUBBER_BAND = 60; // px: most it moves when dragged up past the top
const DIRECTION_SLOP = 10; // px moved before deciding between a drag and a scroll/swipe

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const closing = new WeakSet<HTMLDialogElement>();

/**
 * Slide the sheet away, then close it. `velocity` (px/ms) carries a flick's speed into the exit;
 * `instant` closes without animating (reduced motion, or the browser already animated a back swipe).
 */
export function dismissSheet(sheet: HTMLDialogElement, { velocity = 0, instant = false } = {}) {
  if (!sheet.open || closing.has(sheet)) return;
  if (instant || prefersReducedMotion()) {
    sheet.close();
    return;
  }
  closing.add(sheet);
  const offset = new DOMMatrix(getComputedStyle(sheet).transform).m42; // px already dragged
  const remaining = Math.max(sheet.offsetHeight - offset, 0);
  const duration = Math.round(
    Math.min(Math.max(remaining / Math.max(velocity, EXIT_MIN_SPEED), EXIT_MIN), EXIT_MAX),
  );
  sheet.style.setProperty("--sheet-exit-duration", `${duration}ms`);
  // Same frame: drop the finger's position and add the exit state, so it continues from where it is.
  sheet.classList.remove("is-dragging");
  sheet.style.removeProperty("transform");
  sheet.classList.add("is-closing");
  window.setTimeout(() => {
    sheet.close();
    sheet.classList.remove("is-closing", "is-dragging");
    for (const property of ["--drag", "--sheet-exit-duration"]) sheet.style.removeProperty(property);
    closing.delete(sheet);
  }, duration);
}

/**
 * Drag down to dismiss. `canStartDrag(target)` says whether a touch there may drag the sheet: usually
 * its top bar, or its content when scrolled to the top (otherwise the touch scrolls the content).
 * Escape also slides the sheet away instead of the browser's instant close.
 */
export function initSheet(sheet: HTMLDialogElement, canStartDrag: (target: HTMLElement) => boolean) {
  let startX = 0;
  let startY = 0;
  let dragging: boolean | null = null; // null = direction not decided yet; false = not a drag
  let offset = 0; // px the sheet is moved down (negative: rubber band above the top)
  let samples: { y: number; time: number }[] = [];

  const velocity = () => {
    const recent = samples.filter((sample) => samples[samples.length - 1].time - sample.time <= VELOCITY_WINDOW);
    const [first, last] = [recent[0], recent[recent.length - 1]];
    return first && last && last.time > first.time ? (last.y - first.y) / (last.time - first.time) : 0;
  };

  const springBack = () => {
    sheet.classList.remove("is-dragging");
    sheet.style.removeProperty("transform");
    sheet.style.removeProperty("--drag");
  };

  sheet.addEventListener(
    "touchstart",
    (touch) => {
      // Not while it's already leaving, and only where dragging makes sense.
      dragging = !closing.has(sheet) && canStartDrag(touch.target as HTMLElement) ? null : false;
      startX = touch.touches[0].clientX;
      startY = touch.touches[0].clientY;
      offset = 0;
      samples = [{ y: startY, time: touch.timeStamp }];
    },
    { passive: true },
  );

  // Not passive: once the sheet owns the gesture it stops the content (and iOS) from scrolling too.
  sheet.addEventListener(
    "touchmove",
    (touch) => {
      if (dragging === false) return;
      const x = touch.touches[0].clientX;
      const y = touch.touches[0].clientY;
      if (dragging === null) {
        const [dx, dy] = [x - startX, y - startY];
        if (Math.abs(dx) < DIRECTION_SLOP && Math.abs(dy) < DIRECTION_SLOP) return;
        dragging = dy > 0 && Math.abs(dy) > Math.abs(dx); // down: drag; sideways or up: swipe or scroll
        if (!dragging) return;
        sheet.classList.add("is-dragging");
      }
      touch.preventDefault();
      samples.push({ y, time: touch.timeStamp });
      const dy = y - startY;
      offset = dy >= 0 ? dy : -(1 - 1 / (1 + Math.abs(dy) / 300)) * RUBBER_BAND;
      const progress = Math.min(Math.max(offset, 0) / (window.innerHeight * 0.5), 1);
      sheet.style.transform = `translateY(${offset}px) scale(${1 - SHRINK * progress})`;
      sheet.style.setProperty("--drag", String(progress * BACKDROP_FADE));
    },
    { passive: false },
  );

  const release = () => {
    if (!dragging) return;
    dragging = false;
    const speed = velocity();
    const farEnough = offset > Math.max(CLOSE_DISTANCE, window.innerHeight * CLOSE_FRACTION);
    if (speed > FLICK_DOWN || (farEnough && speed > FLICK_UP)) dismissSheet(sheet, { velocity: speed });
    else springBack(); // the transition animates it back
  };
  sheet.addEventListener("touchend", release);
  sheet.addEventListener("touchcancel", release);

  sheet.addEventListener("cancel", (cancel) => {
    cancel.preventDefault();
    dismissSheet(sheet);
  });
}
