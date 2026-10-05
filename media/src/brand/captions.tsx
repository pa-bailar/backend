// Captions of the voice, opt-in per video: video.json's "captions" ({ style: "minimal" | "kinetic", … }; absent, the
// default, draws nothing, so existing renders don't change). Pages come from src/lib/captions.ts
// (@remotion/captions over data/timing.json). Instrument Sans (digits read in it, the Bodoni's don't), cream on a flat
// ink card like the site's selected chips (a paper card vanished over the site's own cream screens), inside the words' zone of the format (TEXT_ZONE: a Story's safe zone, which also clears the sticker band; a
// Reel's, which also clears the right-hand buttons). They don't move: a card fades in when a run of phrases starts and
// out when it ends; inside a run the phrase swaps in place (MOTION.md, "the motion vocabulary").
import React from "react";
import { interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";
import { captionPages, captionsOn, type CaptionPage, type CaptionsSettings, currentToken, pageAt } from "../lib/captions";
import { clamp } from "../lib/motion";
import type { TimingJson } from "../lib/timing";
import { C, HEIGHT, TEXT_ZONE, TYPE, WIDTH } from "../lib/tokens";

const SIZE = 54;
const FADE = 3; // frames
const GAP_MS = 250; // pages closer than this share the card (no fade between them)
const LEAD_MS = 70; // a word lights up ~2 frames before it's said, as the kit's kinetic type arrives

/** Whether the card is up at `ms`: 0–1, fading in over FADE frames when a run of pages starts, out when it ends. */
function cardOpacity(pages: CaptionPage[], ms: number, fps: number): number {
  const fadeMs = (FADE * 1000) / fps;
  const runs: [number, number][] = [];
  for (const p of pages) {
    const last = runs[runs.length - 1];
    if (last && p.startMs - last[1] < GAP_MS) last[1] = p.endMs;
    else runs.push([p.startMs, p.endMs]);
  }
  const run = runs.find(([a, b]) => ms >= a - 70 - fadeMs && ms < b + fadeMs);
  if (!run) return 0;
  return Math.min(
    interpolate(ms, [run[0] - 70 - fadeMs, run[0] - 70], [0, 1], clamp),
    interpolate(ms, [run[1], run[1] + fadeMs], [1, 0], clamp),
  );
}

/**
 * The captions layer: put it inside the video's `VideoShell`, after the scenes. `video` is the video.json (its
 * "captions"); `timing` its data/timing.json. `format` decides the zone; by default a composition whose id contains
 * "reel" is a Reel.
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
  const page = pageAt(pages, ms);
  const opacity = cardOpacity(pages, ms, fps);
  if (!page || opacity <= 0) return null;
  const zone = TEXT_ZONE[format ?? (id.includes("reel") ? "reel" : "story")];
  const place: React.CSSProperties =
    settings.place === "high" ? { top: zone.top + 26 } : { bottom: HEIGHT - zone.bottom + 40 };
  const now = settings.style === "kinetic" ? currentToken(page, ms + LEAD_MS) : -1;
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
          const lit = i === now ? interpolate(ms + LEAD_MS - t.fromMs, [0, LEAD_MS], [0, 1], clamp) : 0;
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
