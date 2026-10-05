// Things on the table: real flyers (tossed onto a pile), the round sticker, the app icon.
import React from "react";
import { Img } from "remotion";
import { sp, SPRING } from "../lib/motion";
import { C, FONT } from "../lib/tokens";

/**
 * A real flyer, whole (never cropped, as the site shows it), with the site's card border. `src` is a staticFile
 * URL; `lift` 0 (on the table) … 1 (in the air) grows and softens its shadow.
 */
export const Flyer: React.FC<{ src: string; width: number; ratio: number; lift?: number; style?: React.CSSProperties }> = ({
  src,
  width,
  ratio,
  lift = 0,
  style,
}) => (
  <div
    style={{
      position: "absolute",
      width,
      height: width / ratio,
      borderRadius: 8,
      overflow: "hidden",
      border: `4.5px solid ${C.wine900}`,
      boxShadow: `0 ${10 + 50 * lift}px ${18 + 70 * lift}px rgba(42,15,20,${0.3 - 0.12 * lift})`,
      background: C.sunken,
      ...style,
    }}
  >
    <Img src={src} style={{ width: "100%", height: "100%", display: "block" }} />
  </div>
);

/**
 * A toss onto a table: thrown from the side `side` (−1 left, 1 right) at frame `go`, on an arc (across on `snap`,
 * down on `weight`, so it lands with a bounce from 1.22× its size), turning `spin`° less as it goes. Returns the
 * style for a Flyer at its resting place plus its `lift` (for the shadow). Add a wobble() to `rotate` when later
 * landings should nudge it.
 */
export function toss(
  frame: number,
  go: number,
  opts: { side: number; rot?: number; nudge?: number; fromX?: number; fromY?: number; arc?: number; spin?: number },
) {
  const { side, rot = 0, nudge = 0, fromX = 760, fromY = 520, arc = 90, spin = 28 } = opts;
  const k = sp(frame, go, SPRING.snap); // across the table
  const drop = sp(frame, go, SPRING.weight); // down onto it: the bounce
  return {
    lift: Math.max(0, Math.min(1, 1 - drop)),
    style: {
      opacity: frame < go ? 0 : 1,
      translate: `${side * fromX * (1 - k)}px ${fromY * (1 - k) - arc * Math.sin(Math.PI * Math.min(1, k))}px`,
      rotate: `${rot + side * spin * (1 - k) + nudge}deg`,
      scale: `${1 + 0.22 * (1 - drop)}`,
    } satisfies React.CSSProperties,
  };
}

/** The round sticker (like the site's date sticker): tomato, an ink offset shadow, centered content. */
export const Sticker: React.FC<{ d: number; children: React.ReactNode; style?: React.CSSProperties }> = ({
  d,
  children,
  style,
}) => (
  <div
    style={{
      position: "absolute",
      width: d,
      height: d,
      borderRadius: "50%",
      background: C.tomato600,
      boxShadow: `12px 12px 0 ${C.wine900}`,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      color: C.cream50,
      fontFamily: FONT.display,
      ...style,
    }}
  >
    {children}
  </div>
);

/** The app icon's tomato squircle (the record goes on top of it). */
export const AppIcon: React.FC<{ size: number; style?: React.CSSProperties }> = ({ size, style }) => (
  <div
    style={{
      position: "absolute",
      width: size,
      height: size,
      borderRadius: size * (104 / 470), // the phone's app-icon squircle
      background: C.tomato600,
      boxShadow: `10px 10px 0 ${C.wine900}`,
      ...style,
    }}
  />
);

/**
 * A drawn arrow (round caps, the ink's weight), pointing `to` up, down, left or right. For calls to action that point
 * at something on screen (e.g. Instagram's link sticker): cleaner than an emoji hand, and it takes the brand's color.
 */
export const Arrow: React.FC<{
  size: number;
  to?: "up" | "down" | "left" | "right";
  color?: string;
  weight?: number;
  style?: React.CSSProperties;
}> = ({ size, to = "up", color = C.tomato600, weight = 2.6, style }) => {
  const turn = { up: 0, right: 90, down: 180, left: 270 }[to];
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} style={{ display: "block", rotate: `${turn}deg`, ...style }} aria-hidden>
      <path
        d="M12 20V4M5 11l7-7 7 7"
        fill="none"
        stroke={color}
        strokeWidth={weight}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};
