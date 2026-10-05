// Scenes that overlap: each is mounted a few frames before its start (`pre`) and kept a few after its end (`post`)
// so transitions (whips, irises, match cuts) can run across the cut instead of hard-cutting.
import React, { createContext, useContext } from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { clamp } from "./motion";
import { C, FPS } from "./tokens";

const SceneCtx = createContext({ start: 0, pre: 0 });

/**
 * The scene clock. `frame` is relative to the scene's start (negative during the pre-roll), `abs` is the video's
 * frame and `t` the video's time in seconds (for timings that come from the voice and the beat grid).
 */
export function useScene() {
  const f = useCurrentFrame();
  const { start, pre } = useContext(SceneCtx);
  const frame = f - pre;
  return { frame, abs: start + frame, t: (start + frame) / FPS };
}

/**
 * A scene from `start` to `end` (video frames). `move` positions the whole scene at each video frame (a whip pan,
 * the lean before it): `(abs) => style`.
 */
export const Scene: React.FC<{
  start: number;
  end: number;
  pre?: number;
  post?: number;
  name: string;
  children: React.ReactNode;
  move?: (abs: number) => React.CSSProperties;
}> = ({ start, end, pre = 0, post = 0, name, children, move }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence name={name} from={start - pre} durationInFrames={end - start + pre + post} premountFor={fps}>
      <SceneCtx.Provider value={{ start, pre }}>
        <Moving start={start} pre={pre} move={move}>
          {children}
        </Moving>
      </SceneCtx.Provider>
    </Sequence>
  );
};

const Moving: React.FC<{
  start: number;
  pre: number;
  move?: (abs: number) => React.CSSProperties;
  children: React.ReactNode;
}> = ({ start, pre, move, children }) => {
  const abs = useCurrentFrame() - pre + start;
  return <AbsoluteFill style={move ? move(abs) : undefined}>{children}</AbsoluteFill>;
};

/** Eases in from the paper over the first `frames` (no hard first frame); put it above the scenes. */
export const FadeIn: React.FC<{ frames?: number; color?: string }> = ({ frames = 8, color = C.paper }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{ background: color, opacity: interpolate(frame, [0, frames], [1, 0], clamp), pointerEvents: "none" }}
    />
  );
};
