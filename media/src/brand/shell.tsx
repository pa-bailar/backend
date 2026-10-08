// What every video sits in: the paper, the fade-in, the grain over everything and the soundtrack, plus the props of a
// vertical <Composition>. A video's own scenes go inside.
import { Audio } from "@remotion/media";
import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, FadeOut } from "../lib/scene";
import { C, FPS, HEIGHT, SAFE, STORY_FIT, WIDTH } from "../lib/tokens";
import { Grain } from "./paper";

/**
 * The paper background, the scenes (children), a fade-in from the paper over `fadeIn` frames (0: none), the grain and
 * the soundtrack (`audio`, a staticFile URL). No fade-out by default: Stories fade in and never out (the owner,
 * 5 Oct 2026). `fadeOut` (frames) exists only for formats other than a Story. `story` fits the scenes under the
 * sticker band (`STORY_FIT`): pass it for a Story deliverable, never for a Reel.
 */
export const VideoShell: React.FC<{
  children: React.ReactNode;
  fadeIn?: number;
  fadeOut?: number;
  audio?: string;
  background?: string;
  story?: boolean;
}> = ({ children, fadeIn = 8, fadeOut = 0, audio, background = C.paper, story = false }) => (
  <AbsoluteFill style={{ background }}>
    {story ? <AbsoluteFill style={FIT}>{children}</AbsoluteFill> : children}
    {fadeIn > 0 ? <FadeIn frames={fadeIn} /> : null}
    {fadeOut > 0 ? <FadeOut frames={fadeOut} /> : null}
    <Grain />
    {audio ? <Audio src={audio} /> : null}
  </AbsoluteFill>
);

/** The safe area's top edge stays centered while it scales, then the whole moves down under the sticker band. */
const FIT: React.CSSProperties = {
  transformOrigin: `${WIDTH / 2}px ${SAFE.top}px`,
  transform: `translateY(${STORY_FIT.shift}px) scale(${STORY_FIT.scale})`,
};

/** A vertical composition's size, rate and length from its video.json: `<Composition {...vertical(settings)} …/>`. */
export const vertical = (settings: { duration: number }) => ({
  durationInFrames: Math.round(settings.duration * FPS),
  fps: FPS,
  width: WIDTH,
  height: HEIGHT,
});
