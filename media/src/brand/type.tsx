// Kinetic type: words follow the voice one by one (each 2–3 frames before it's said), wordmarks land letter by letter.
import React from "react";
import { interpolate } from "remotion";
import { clamp, jit, sp, SPRING } from "../lib/motion";

/** One word: drops in on a spring with a small tilt that settles (follow-through). Negative `distance` drops from above. */
export const Word: React.FC<{
  frame: number;
  start: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
  pulse?: number;
  distance?: number;
}> = ({ frame, start, children, style, pulse = 0, distance = 60 }) => {
  const s = sp(frame, start, SPRING.snap);
  return (
    <span
      style={{
        display: "inline-block",
        opacity: interpolate(frame, [start, start + 4], [0, 1], clamp),
        translate: `0px ${distance * (1 - s)}px`,
        rotate: `${6 * (1 - s)}deg`,
        scale: `${1 + 0.06 * pulse}`,
        transformOrigin: "50% 80%",
        ...style,
      }}
    >
      {children}
    </span>
  );
};

/**
 * Words in a row, each at its own frame: `words` = [text, start frame][]. With timing.ts:
 * `[["¿Quieres", at(word("a1", "quieres"))], …]`.
 */
export const Words: React.FC<{ frame: number; words: [string, number][]; distance?: number }> = ({
  frame,
  words,
  distance,
}) => (
  <>
    {words.map(([text, start], i) => (
      <React.Fragment key={i}>
        {i > 0 ? " " : null}
        <Word frame={frame} start={start} distance={distance}>
          {text}
        </Word>
      </React.Fragment>
    ))}
  </>
);

/**
 * A wordmark landing letter by letter from above: one letter every `step` frames with ±1 frame of irregular jitter
 * (seeded by `seed`, so two wordmarks differ). The parent sets the face and `whiteSpace: "pre"`.
 */
export const Letters: React.FC<{
  frame: number;
  start: number;
  text: string;
  step?: number;
  seed?: string;
  distance?: number;
}> = ({ frame, start, text, step = 1, seed = "letters", distance = -90 }) => (
  <>
    {[...text].map((ch, i) => (
      <Word key={i} frame={frame} start={start + Math.round(i * step) + jit(`${seed}${i}`, 1)} distance={distance}>
        {ch}
      </Word>
    ))}
  </>
);
