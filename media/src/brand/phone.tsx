// The site on a phone: a flat phone, real screenshots placed by their CSS rects (tools/capture.mjs), a thumb that
// taps and drags, and a frame that points at things.
import React from "react";
import { Easing, Img, interpolate } from "remotion";
import { clamp, mix, sp, SPRING } from "../lib/motion";
import { C, WIDTH } from "../lib/tokens";

/** A rect in the site's CSS px (what tools/capture.mjs records). */
export type Rect = { x: number; y: number; w: number; h: number };
export const mid = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });
export const pad = (r: Rect, px: number, py: number): Rect => ({
  x: r.x - px,
  y: r.y - py,
  w: r.w + 2 * px,
  h: r.h + 2 * py,
});
export const union = (a: Rect, b: Rect): Rect => {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
};

/**
 * Where the phone sits (video px). The captures are 360×640 CSS px at device scale 3 (= 1080×1920), so `css` is
 * how many video px one site CSS px is inside the phone, and sx/sy map a screen point to the scene.
 */
export function phoneAt(opts: { width?: number; top?: number; bezel?: number; radius?: number } = {}) {
  const { width = 760, top = 530, bezel = 16, radius = 60 } = opts;
  const left = (WIDTH - width) / 2;
  const css = (3 * width) / 1080;
  return {
    width,
    left,
    top,
    bezel,
    radius,
    height: (width * 16) / 9,
    css,
    sx: (x: number) => left + x * css,
    sy: (y: number) => top + y * css,
  };
}
export type PhoneGeometry = ReturnType<typeof phoneAt>;
/** The teaser's phone: 760 px wide, its screen's top at y 530. */
export const PHONE = phoneAt();

/** A flat phone: bezel and outline around a 9:16 screen. Its children are positioned in screen pixels. */
export const Phone: React.FC<{ children: React.ReactNode; at?: PhoneGeometry; style?: React.CSSProperties }> = ({
  children,
  at = PHONE,
  style,
}) => (
  <div
    style={{
      position: "absolute",
      left: at.left - at.bezel,
      top: at.top - at.bezel,
      width: at.width + 2 * at.bezel,
      height: at.height + 2 * at.bezel,
      borderRadius: at.radius + at.bezel,
      background: C.bezel,
      boxShadow: `0 0 0 3px ${C.bezelEdge}, 0 50px 90px rgba(42,15,20,0.28), 0 12px 24px rgba(42,15,20,0.18)`,
      ...style,
    }}
  >
    <div
      style={{
        position: "absolute",
        left: at.bezel,
        top: at.bezel,
        width: at.width,
        height: at.height,
        borderRadius: at.radius,
        overflow: "hidden",
        background: C.paper,
      }}
    >
      {children}
    </div>
  </div>
);

/**
 * Part of a screenshot (`src`, a staticFile URL), cut to `r` (CSS px, + a margin `m` for its shadow), drawn where it
 * sits on the screen. For a menu or a card that animates on its own over the rest of the screen.
 */
export const Crop: React.FC<{
  src: string;
  r: Rect;
  m?: number;
  at?: PhoneGeometry;
  style?: React.CSSProperties;
  origin?: string;
}> = ({ src, r, m = 14, at = PHONE, style, origin }) => (
  <div
    style={{
      position: "absolute",
      left: (r.x - m) * at.css,
      top: (r.y - m) * at.css,
      width: (r.w + 2 * m) * at.css,
      height: (r.h + 2 * m) * at.css,
      overflow: "hidden",
      transformOrigin: origin,
      ...style,
    }}
  >
    <Img src={src} style={{ position: "absolute", left: -(r.x - m) * at.css, top: -(r.y - m) * at.css, width: at.width }} />
  </div>
);

/**
 * A touch, as phones show it in screen recordings: a soft disc that arrives on an arc, presses (shrinks, a ring
 * ripples out), drags while pressed, and lifts. Keys are in frames and scene pixels (use the phone's sx/sy).
 */
export type ThumbKey = { f: number; x: number; y: number; tap?: boolean; down?: boolean };
export const Thumb: React.FC<{ frame: number; keys: ThumbKey[] }> = ({ frame, keys }) => {
  const first = keys[0];
  const last = keys[keys.length - 1];
  if (frame < first.f - 8 || frame > last.f + 10) return null;
  let x = first.x;
  let y = first.y;
  let down = 0;
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (frame >= a.f) {
      const k = interpolate(frame, [a.f, b.f], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
      const arc = a.down ? 0 : Math.sin(Math.PI * k) * Math.min(60, Math.hypot(b.x - a.x, b.y - a.y) * 0.25);
      x = mix(a.x, b.x, k) + arc * 0.4;
      y = mix(a.y, b.y, k) - arc;
      if (a.down && frame < b.f) down = Math.max(down, 1);
    }
  }
  // Taps: press in 2 frames, release over 6; the ring ripples out.
  let ring = -1;
  for (const k of keys) {
    if (!k.tap) continue;
    const d = frame - k.f;
    if (d >= -2 && d < 8) down = Math.max(down, d < 0 ? (d + 2) / 2 : Math.max(0, 1 - d / 6));
    if (d >= 0 && d < 12) ring = d / 12;
  }
  const appear = interpolate(frame, [first.f - 8, first.f - 2], [0, 1], clamp);
  const leave = interpolate(frame, [last.f + 3, last.f + 10], [1, 0], clamp);
  const size = 104;
  return (
    <div
      style={{
        position: "absolute",
        left: x - size / 2,
        top: y - size / 2,
        width: size,
        height: size,
        opacity: appear * leave,
      }}
    >
      {ring >= 0 ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            border: `4px solid ${C.cream50}`,
            scale: `${1 + 0.9 * ring}`,
            opacity: 0.9 * (1 - ring),
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: "50%",
          background: "rgba(42,15,20,0.32)",
          border: `4px solid rgba(255,248,236,0.95)`,
          boxShadow: "0 6px 18px rgba(42,15,20,0.25)",
          scale: `${(1 - 0.18 * down) * mix(0.7, 1, appear)}`,
        }}
      />
    </div>
  );
};

/**
 * A frame that points at things on the screen and springs from one to the next, overshooting a little. `cues` are
 * rects (CSS px, already where they are on screen at this frame) with the frame each one starts; it pops in on the
 * first. `opacity` lets it step aside (e.g. while a sheet is pulled up).
 */
export const Highlight: React.FC<{
  frame: number;
  cues: { at: number; box: Rect }[];
  at?: PhoneGeometry;
  opacity?: number;
}> = ({ frame, cues, at = PHONE, opacity = 1 }) => {
  if (!cues.length || frame < cues[0].at) return null;
  const k = (key: keyof Rect) => {
    let v = cues[0].box[key];
    for (let i = 1; i < cues.length; i++) v += (cues[i].box[key] - cues[i - 1].box[key]) * sp(frame, cues[i].at, SPRING.snap);
    return v;
  };
  const pop = sp(frame, cues[0].at, SPRING.pop);
  return (
    <div
      style={{
        position: "absolute",
        left: k("x") * at.css,
        top: k("y") * at.css,
        width: k("w") * at.css,
        height: k("h") * at.css,
        border: `6px solid ${C.tomato600}`,
        borderRadius: 10,
        boxShadow: `0 0 0 4px ${C.cream50}, 0 8px 22px rgba(42,15,20,0.25)`,
        opacity: interpolate(frame, [cues[0].at, cues[0].at + 3], [0, 1], clamp) * opacity,
        scale: `${mix(1.25, 1, pop)}`,
      }}
    />
  );
};
