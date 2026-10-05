// The page's furniture: the grain over everything, the 70s stripes, the period-style title.
import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { clamp, jit, sp, SPRING } from "../lib/motion";
import { C, FONT, STRIPES } from "../lib/tokens";

/** Paper/offset grain over everything: fractal noise multiplied into the page, a new seed every 2 frames (15 fps). */
export const Grain: React.FC<{ opacity?: number }> = ({ opacity = 0.1 }) => {
  const frame = useCurrentFrame();
  const seed = Math.floor(frame / 2);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity, mixBlendMode: "multiply" }}>
      <svg width="100%" height="100%" viewBox="0 0 540 960" preserveAspectRatio="none">
        <filter id={`grain-${seed}`} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={seed} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="540" height="960" filter={`url(#grain-${seed})`} />
      </svg>
    </AbsoluteFill>
  );
};

/**
 * The 70s triple stripe (the site's stripes.css: 5 px bands, 3 px gaps; ×3 for video), as page heads use it. Each
 * band wipes in from the left on a spring, staggered.
 */
export const Stripes: React.FC<{ frame: number; start: number; top: number; left?: number; width?: number }> = ({
  frame,
  start,
  top,
  left = 80,
  width = 920,
}) => (
  <div style={{ position: "absolute", top, left, width, display: "flex", flexDirection: "column", gap: 9 }}>
    {STRIPES.map((c, i) => (
      <div
        key={c}
        style={{
          height: 15,
          width: width * Math.max(0, sp(frame, start + i * 2 + jit(`stripe${i}${start}`, 1), SPRING.snap)),
          maxWidth: width * 1.02,
          background: c,
        }}
      />
    ))}
  </div>
);

/**
 * A title in the site's period-heading style: Shrikhand in --period-title with a soft offset shadow, between
 * tri-color rules. It builds in pieces (rule, word, rule), each on its own spring: overlapping action. Several in a
 * row (one per beat of the voice) replace each other: pass the next one's start as `exitAt`. `pulse` (0–1, e.g.
 * kick()) is a beat accent.
 */
export const PeriodTitle: React.FC<{
  children: React.ReactNode;
  frame: number;
  start: number;
  exitAt?: number;
  size?: number;
  top?: number;
  pulse?: number;
}> = ({ children, frame, start, exitAt, size = 100, top = 270, pulse = 0 }) => {
  const rule = `linear-gradient(to right, ${STRIPES[0]} 0 33.34%, ${STRIPES[1]} 33.34% 66.67%, ${STRIPES[2]} 66.67%)`;
  const out =
    exitAt === undefined
      ? 0
      : interpolate(frame, [exitAt, exitAt + 4], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  if (frame < start - 1 || out >= 1) return null;
  const r1 = sp(frame, start, SPRING.snap);
  const word = sp(frame, start + 2, SPRING.snap);
  const r2 = sp(frame, start + 4, SPRING.snap);
  const ruleStyle = (k: number, y: number): React.CSSProperties => ({
    position: "absolute",
    left: 0,
    top: y,
    height: 9,
    width: `${100 * Math.min(1, k)}%`,
    background: rule,
    backgroundSize: "920px 9px",
  });
  return (
    <div style={{ position: "absolute", left: 80, right: 80, top, height: size * 1.08 + 64, opacity: 1 - out }}>
      <div style={ruleStyle(r1, 0)} />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 34,
          fontFamily: FONT.display,
          fontSize: size,
          lineHeight: 1.08,
          whiteSpace: "nowrap",
          color: C.tomato700,
          textShadow: `6px 6px 0 ${C.cream300}`,
          transformOrigin: "0% 60%",
          opacity: interpolate(frame, [start + 2, start + 6], [0, 1], clamp),
          translate: `0px ${56 * (1 - word) + 26 * out}px`,
          rotate: `${-4 * (1 - word)}deg`,
          scale: `${1 + 0.05 * pulse}`,
        }}
      >
        {children}
      </div>
      <div style={ruleStyle(r2, size * 1.08 + 55)} />
    </div>
  );
};
