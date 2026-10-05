// Motion blur on fast moves only (tosses, whips, flicks), with exact colors.
import React from "react";
import { AbsoluteFill, Freeze, useCurrentFrame } from "remotion";

/**
 * The frame rendered at `samples` moments across a 180° shutter (centered on the frame) and averaged with normal
 * blending (layer i at opacity 1/(i+1)), so colors stay exact. @remotion/motion-blur's HtmlInCanvasMotionBlur and
 * CameraMotionBlur add the samples ("lighter" / plus-lighter): that lifted the paper ~8 levels in 8-bit and
 * flickered the background on every blurred frame. Rendering cost grows with `samples`: 1 turns it off.
 */
export const Shutter: React.FC<{ samples: number; children: React.ReactNode }> = ({ samples, children }) => {
  const frame = useCurrentFrame();
  if (samples <= 1) return <>{children}</>;
  return (
    <AbsoluteFill style={{ isolation: "isolate" }}>
      {Array.from({ length: samples }, (_, i) => (
        <AbsoluteFill key={i} style={{ opacity: 1 / (i + 1) }}>
          <Freeze frame={frame - 0.25 + (0.5 * i) / (samples - 1)}>{children}</Freeze>
        </AbsoluteFill>
      ))}
    </AbsoluteFill>
  );
};

/** Inclusive frame ranges [from, to]. */
export type Ranges = [number, number][];
export const inRanges = (frame: number, ranges: Ranges) => ranges.some(([a, b]) => frame >= a && frame <= b);

/**
 * How many shutter samples a frame needs: 1 outside `ranges`, `normal` inside, `fast` inside `fastRanges`. Whips
 * move ~400 px a frame and need ~16 samples or the blur shows as separate copies; tosses and flicks look right
 * with 8.
 */
export function samplesFor(frame: number, ranges: Ranges, fastRanges: Ranges = [], normal = 8, fast = 16): number {
  if (inRanges(frame, fastRanges)) return fast;
  return inRanges(frame, ranges) ? normal : 1;
}

/**
 * Blur inside one layer, cheaper than the Shutter: draw `render(at)` at several moments of a 180° shutter when
 * `speed` (px per frame) is high. E.g. a long screenshot scrolling inside a phone.
 */
export function smear(frame: number, speed: number, render: (at: number, i: number, opacity: number) => React.ReactNode) {
  const n = speed < 3 ? 1 : Math.min(12, Math.ceil(speed / 6));
  return Array.from({ length: n }, (_, i) =>
    render(n === 1 ? frame : frame - 0.25 + (0.5 * i) / (n - 1), i, 1 / (i + 1)),
  );
}
