// Captions of the voice, opt-in per video: video.json's "captions" ({ style: "minimal" | "kinetic", … }; absent, the
// default, draws nothing, so existing renders don't change). Pages come from src/lib/captions.ts
// (@remotion/captions over data/timing.json). Instrument Sans (digits read in it, the Bodoni's don't), cream on a flat
// ink card like the site's selected chips (a paper card vanished over the site's own cream screens), inside the words' zone of the format (TEXT_ZONE: a Story's safe zone, which also clears the sticker band; a
// Reel's, which also clears the right-hand buttons). They don't move: a card fades in when a run of phrases starts and
// out when it ends; inside a run the phrase swaps in place (MOTION.md, "the motion vocabulary").
import React from "react";
import { interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import {
  CAPTION_LEAD_MS,
  captionAt,
  captionPages,
  captionsOn,
  type CaptionsSettings,
  currentToken,
  formatOf,
} from "../lib/captions";
import { clamp } from "../lib/motion";
import type { TimingJson } from "../lib/timing";
import { C, HEIGHT, TEXT_ZONE, TYPE, WIDTH } from "../lib/tokens";

const SIZE = 54;
const FADE = 3; // frames

/**
 * The captions layer: put it inside the video's `VideoShell`, after the scenes. `video` is the video.json (its
 * "captions"); `timing` its data/timing.json. `format` decides the zone; by default a composition whose id ends with
 * "-reel" is a Reel.
 */
export const Captions: React.FC<{ video: object; timing: TimingJson; format?: "story" | "reel" }> = ({
  video,
  timing,
  format,
}) => {
  const frame = useCurrentFrame();
  const { fps, id } = useVideoConfig();
  const settings = (video as { captions?: CaptionsSettings }).captions;
  const pages = React.useMemo(() => (settings ? captionPages(timing, settings) : []), [settings, timing]);
  if (!settings || !captionsOn(settings, id)) return null;
  const ms = (frame / fps) * 1000;
  const shown = captionAt(pages, ms, (FADE * 1000) / fps);
  if (!shown) return null;
  const { page, opacity } = shown;
  const zone = TEXT_ZONE[format ?? formatOf(id)];
  const place: React.CSSProperties =
    settings.place === "high" ? { top: zone.top + 26 } : { bottom: HEIGHT - zone.bottom + 40 };
  const now = settings.style === "kinetic" ? currentToken(page, ms + CAPTION_LEAD_MS) : -1;
  return (
    <div
      style={{
        position: "absolute",
        left: zone.left,
        right: WIDTH - zone.right,
        ...place,
        display: "flex",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          ...TYPE.sans(SIZE, C.cream50),
          lineHeight: 1.2,
          textAlign: "center",
          background: C.wine900,
          borderRadius: 18,
          padding: "12px 26px 14px",
        }}
      >
        {page.tokens.map((t, i) => {
          // "kinetic": the word being said turns marigold over 2 frames (lit by the time it's said), and back when
          // the next one lights.
          const lit =
            i === now ? interpolate(ms + CAPTION_LEAD_MS - t.fromMs, [0, CAPTION_LEAD_MS], [0, 1], clamp) : 0;
          const color = t.emphasis ? C.marigold400 : interpolateColors(lit, [0, 1], [C.cream50, C.marigold400]);
          return (
            <React.Fragment key={i}>
              {i > 0 ? " " : null}
              <span style={{ color, fontWeight: t.emphasis ? 700 : 600 }}>{t.text}</span>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
