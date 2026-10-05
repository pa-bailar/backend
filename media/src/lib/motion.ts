// The ONE motion system (MOTION.md): springs with a little overshoot instead of fixed curves, irregular staggers,
// a slow camera on every scene, beat accents on downbeats only. Every video builds on these; tune a video by
// choosing among them, not by inventing new curves.
import type React from "react";
import { Easing, interpolate, random, spring } from "remotion";
import { FPS } from "./tokens";

/**
 * The springs (Remotion's spring(): mass, damping, stiffness). Overshoot and settle time measured with
 * spring()/measureSpring() at 30 fps (threshold 1%).
 */
export const SPRING = {
  /** Text, titles, UI parts: ~7% overshoot, settled in 13 frames. The default entrance. */
  snap: { damping: 14, stiffness: 170, mass: 0.7 },
  /** Sheets, menus, the highlight frame: ~4%, 13 frames. */
  sheet: { damping: 18, stiffness: 200, mass: 0.8 },
  /** Things with weight (flyers landing, the record): ~14%, a visible bounce, ~24 frames. */
  weight: { damping: 12, stiffness: 120, mass: 1.1 },
  /** Stickers and icons popping in: ~22%, 19 frames. */
  pop: { damping: 9, stiffness: 180, mass: 0.6 },
  /** A scroll let go by a thumb: glides, ~2% past the stop, then back. */
  thumb: { damping: 15, stiffness: 120, mass: 0.9 },
  /** Whip pans: stiff, ~3% past, then back (the follow-through). */
  whip: { damping: 20, stiffness: 320, mass: 0.6 },
};
export type SpringConfig = { damping: number; stiffness: number; mass: number };

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Linear blend of two numbers. */
export const mix = (a: number, b: number, k: number) => a + (b - a) * k;

/** Spring progress 0→1 (overshooting a little) starting at `start` (frames). */
export function sp(frame: number, start: number, config: SpringConfig = SPRING.snap): number {
  return spring({ frame: Math.max(0, frame - start), fps: FPS, config });
}

/** Its speed in progress per frame (for squash and stretch, motion-driven blur, follow-through). */
export function spv(frame: number, start: number, config: SpringConfig = SPRING.snap): number {
  return sp(frame, start, config) - sp(frame - 1, start, config);
}

/** A deterministic, irregular offset in frames (−amount…amount) so staggers aren't a metronome. */
export function jit(seed: string | number, amount = 2): number {
  return Math.round((random(`jit-${seed}`) - 0.5) * 2 * amount);
}

/**
 * The ONE entrance, "rise": from `distance` px lower and transparent to place on a spring, overshooting a few px
 * and settling, stretched a touch along the move while fast (squash & stretch, subtle). Optional exit: accelerates
 * out (slow in, fast out) down and transparent in 6 frames. Things leave faster than they arrive.
 */
export function rise(
  frame: number,
  start: number,
  opts: { distance?: number; exitAt?: number; config?: SpringConfig } = {},
): React.CSSProperties {
  const { distance = 70, exitAt, config = SPRING.snap } = opts;
  const s = sp(frame, start, config);
  const v = spv(frame, start, config);
  const opacity = interpolate(frame, [start, start + 5], [0, 1], clamp);
  if (exitAt === undefined || frame < exitAt) {
    return {
      opacity,
      translate: `0px ${distance * (1 - s)}px`,
      scale: `${1 - 0.12 * v} ${1 + 0.3 * v}`,
    };
  }
  const k = interpolate(frame, [exitAt, exitAt + 6], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  return { opacity: 1 - k, translate: `0px ${30 * k}px` };
}

/** An exit progress 0→1 over `frames`, accelerating out (for anything that leaves). */
export function leave(frame: number, at: number, frames = 6): number {
  return interpolate(frame, [at, at + frames], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
}

/**
 * A musical grid: beats and bars (seconds) at `bpm` in 4/4. Cut and accent on downbeats, not every beat:
 * always-on-the-beat gets predictable.
 */
export function grid(bpm: number) {
  const BEAT = 60 / bpm;
  const BAR = 4 * BEAT;
  const every = (step: number) => (from: number, to: number) => {
    const out: number[] = [];
    for (let n = Math.ceil(from / step - 1e-6); n * step < to; n++) out.push(n * step);
    return out;
  };
  return { bpm, BEAT, BAR, beats: every(BEAT), downbeats: every(BAR) };
}

/** A kick after each time in `at` (seconds): 0 → 1 in ~2 frames, back to 0 in ~10. For beat accents. */
export function kick(tSec: number, at: number[]): number {
  let v = 0;
  for (const b of at) {
    const d = (tSec - b) * FPS;
    if (d >= 0) v = Math.max(v, (d / 2) * Math.exp(1 - d / 2));
  }
  return v;
}

/**
 * The camera: a slow push-in and drift over a scene (seconds), so nothing is ever still. `depth` makes parallax:
 * 1 for the main layer, less for things "further back" (titles 0.5–0.6), more for things nearer (a pile, 1.25).
 */
export function camera(
  tSec: number,
  from: number,
  to: number,
  opts: { zoom?: number; driftX?: number; driftY?: number; phase?: number } = {},
) {
  const { zoom = 0.04, driftX = 10, driftY = -14, phase = 0 } = opts;
  const p = interpolate(tSec, [from, to], [0, 1], clamp);
  const e = Easing.inOut(Easing.sin)(p);
  return (depth = 1): React.CSSProperties => ({
    scale: `${1 + zoom * e * depth}`,
    translate: `${driftX * Math.sin(Math.PI * (p + phase)) * depth}px ${driftY * e * depth}px`,
  });
}

/**
 * A damped wobble (degrees or px) after each time in `at` (frames): secondary action, e.g. a flyer below being
 * nudged when the next one lands.
 */
export function wobble(frame: number, at: number[], amount = 1.6): number {
  let v = 0;
  for (const a of at) {
    const d = frame - a;
    if (d >= 0) v += Math.exp(-d / 6) * Math.sin(d * 0.8) * amount;
  }
  return v;
}
