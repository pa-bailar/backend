// The end card every video closes on (teaser v2.3 set it): the call to action right under the sticker band, the
// stripes, the app icon with the record (the video's own: a match cut, a pop), the wordmark letter by letter and an
// optional sign-off.
import React from "react";
import { AbsoluteFill } from "remotion";
import { rise } from "../lib/motion";
import { C, STICKER_BAND, TYPE } from "../lib/tokens";
import { Arrow } from "./objects";
import { Stripes } from "./paper";
import { Letters } from "./type";

/** "story": "Link aquí arriba" with the drawn arrow up at the link sticker; "reel": "Link en mi perfil", no arrow. */
export type Cta = "story" | "reel";

/**
 * Where the call to action sits: right under the band, low enough that the arrow's tip (bobbing `CTA_BOB` px up, the
 * spring's overshoot and a 3% push-in at depth 0.6) stays below y 252 on every frame. Measured in teaser v2.4
 * (closest: y 258) and este-finde v1 (y 256) with tools/review.py band.
 */
export const CTA_TOP = STICKER_BAND.bottom + 26;
export const CTA_BOB = 14;

/**
 * The Reel's end card keeps clear of the like, comment and share column (`REEL_SAFE.right`: nothing past x 960),
 * still centered on the icon: the stripes x 150–930 (their spring overshoots 2%, to x 946) and the wordmark at most
 * 140 px (about x 165–915; the camera's 1.8% push-in at depth 0.6 takes it to about x 925). The Story's card keeps the
 * full width (stripes x 80–1000, the wordmark at 168). Measured in teaser v2.5 with tools/review.py reel.
 */
export const REEL_END = { stripes: { left: 150, width: 780 }, nameMax: 140 };

export const EndCard: React.FC<{
  cta: Cta;
  /** The clock the times below are on (a scene's frame, or the video's). */
  frame: number;
  /** The camera at a depth (camera(t, from, to, …)): the call to action and the wordmark at 0.6, the center at 1. */
  cam: (depth: number) => React.CSSProperties;
  /** When the call to action rises (frame). */
  link: number;
  /** The arrow's bob, 0–1 (kick() on the beats). */
  bob: number;
  /** When the stripes wipe in (frame). */
  stripesAt: number;
  /** The wordmark: when it starts (frame), its size, its letter step and its jitter seed. */
  name: { at: number; size?: number; step?: number; seed: string };
  /** The center of the icon and the record; the wordmark sits 300 px below it, the sign-off 490. */
  spot: { x: number; y: number };
  /** An optional line under the wordmark, in the Bodoni (no digits). */
  signoff?: { text: string; at: number };
  /** The card's own background (when the scenes behind it should not show). */
  background?: string;
  /** The icon and the record, on the main layer (depth 1). */
  children: React.ReactNode;
}> = ({ cta, frame, cam, link, bob, stripesAt, name, spot, signoff, background, children }) => {
  const reel = cta === "reel";
  const size = name.size ?? 168;
  // A Reel's smaller wordmark stays centered in the Story's slot (between the icon and the sign-off).
  const nameSize = reel ? Math.min(size, REEL_END.nameMax) : size;
  const nameTop = spot.y + 300 + (reel ? Math.round((size - nameSize) / 2) : 0);
  return (
    <AbsoluteFill style={background ? { background } : undefined}>
      <AbsoluteFill style={cam(0.6)}>
        {/* The call to action, right under the sticker's band: the arrow points up at the link. */}
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: CTA_TOP,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 0,
            ...rise(frame, link, { distance: 40 }),
          }}
        >
          {cta === "story" ? <Arrow size={132} weight={3.2} style={{ translate: `0px ${-CTA_BOB * bob}px` }} /> : null}
          <div style={{ ...TYPE.sans(68), textAlign: "center" }}>
            {cta === "story" ? "Link aquí arriba" : "Link en mi perfil"}
          </div>
        </div>
      </AbsoluteFill>
      {reel ? (
        <Stripes frame={frame} start={stripesAt} top={500} {...REEL_END.stripes} />
      ) : (
        <Stripes frame={frame} start={stripesAt} top={500} />
      )}
      <AbsoluteFill style={cam(1)}>{children}</AbsoluteFill>
      <AbsoluteFill style={cam(0.6)}>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: nameTop,
            textAlign: "center",
            ...TYPE.display(nameSize, C.tomato600),
            lineHeight: 1,
            whiteSpace: "pre",
          }}
        >
          <Letters frame={frame} start={name.at} text="Pa' Bailar" step={name.step ?? 1.4} seed={name.seed} />
        </div>
        {signoff ? (
          <div
            style={{
              position: "absolute",
              left: 80,
              right: 80,
              top: spot.y + 490,
              textAlign: "center",
              ...TYPE.serif(66),
              ...rise(frame, signoff.at, { distance: 50 }),
            }}
          >
            {signoff.text}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
