// Motivated transitions instead of hard cuts: whip pans (with motion blur, lib/blur.tsx), an iris out of a shape,
// and match cuts (the same shape and spin on both sides of the cut: share one function between the two scenes,
// as projects/teaser-v2/scenes/Free.tsx does with `flight`).
import { Easing, interpolate } from "remotion";
import { clamp, sp, SPRING } from "./motion";

/** Frames a whip starts before its cut. */
export const WHIP_LEAD = 5;

/**
 * A whip pan around the cut at `cut` (video frames): `p` goes 0 → 1 on a stiff spring (a hair past, then back),
 * starting `lead` frames before the cut; `dip` is the anticipation, a 22 px lean the other way just before it goes.
 * The outgoing scene moves by −p × the screen, the incoming one by (1 − p): see the teaser's Teaser.tsx.
 */
export function whip(abs: number, cut: number, lead = WHIP_LEAD) {
  const p = sp(abs, cut - lead, SPRING.whip);
  const dip = 22 * Math.sin(Math.PI * interpolate(abs, [cut - lead - 6, cut - lead], [0, 1], clamp));
  return { p, dip };
}

/** The frames around a whip that need motion blur (with many samples). */
export const whipBlur = (cut: number, lead = WHIP_LEAD): [number, number] => [cut - lead - 1, cut + 7];

/**
 * An iris: a circle opening from (x, y) over `frames` before the scene's start, accelerating. Returns a CSS
 * clip-path for the incoming scene (mounted with `pre` = frames).
 */
export function iris(frame: number, at: { x: number; y: number }, frames = 8, radius = 1400): string {
  const r = interpolate(frame, [-frames, 1], [0, radius], { ...clamp, easing: Easing.in(Easing.quad) });
  return `circle(${r}px at ${at.x}px ${at.y}px)`;
}
