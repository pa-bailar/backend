// Scene 1 (0.00–4.29): "¿Quieres salir a bailar este finde… y no sabes a dónde ir?"
// The question builds word by word with the voice; real flyers of upcoming events are tossed onto a pile, one
// per beat, each on an arc, landing with weight (a bounce, its shadow tightening) and nudging the ones below.
import React from "react";
import { AbsoluteFill } from "remotion";
import { C, camera, Flyer, jit, kick, sec, toss, TYPE, useScene, wobble, Word, Words } from "../../../src/kit";
import app from "../data/app.json";
import { BEAT, file, SCENES, word } from "../theme";

// Where each flyer rests: [x offset, y offset, rotation]; pile centered at (540, 1230). Landing on beats
// 0.5, 2, 3, 5, 6 (beat 4 belongs to the second line), each a frame or two off the grid.
const REST: [number, number, number][] = [
  [-170, -60, -9],
  [175, -20, 7],
  [-150, 170, 5],
  [170, 200, -6],
  [0, 110, -2],
];
const LAND = [0.5, 2, 3, 5, 6].map((b, i) => sec(b * BEAT) + jit(`land${i}`, 2));
const W = 500;

export const Question: React.FC = () => {
  const { frame, t } = useScene();
  const cam = camera(t, SCENES.question, SCENES.cover, { zoom: 0.06, driftX: 12, driftY: -18 });
  const at = (s: number) => sec(s) - 3; // words land a hair before they're said
  const accent = kick(t, [4 * BEAT]); // the downbeat right after "este finde"
  // Bottom of the pile first: other rhythms, then the chosen ones with the soonest on top (center).
  const pile = [...app.pile.filter((p) => !p.chosen), ...app.pile.filter((p) => p.chosen).reverse()].slice(
    -REST.length,
  );
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill style={cam(1.25)}>
        {pile.map((p, i) => {
          const [x, y, rot] = REST[i];
          // Airborne for ~7 frames before touching down; later landings nudge this one (secondary action).
          const flight = toss(frame, LAND[i] - 7, {
            side: i % 2 === 0 ? -1 : 1,
            rot,
            nudge: wobble(frame, LAND.slice(i + 1), 1.6 - 0.3 * (i % 3)),
          });
          return (
            <Flyer
              key={p.file}
              src={file(`app/${p.file}`)}
              width={W}
              ratio={p.ratio}
              lift={flight.lift}
              style={{ left: 540 - W / 2 + x, top: 1230 - W / p.ratio / 2 + y, ...flight.style }}
            />
          );
        })}
      </AbsoluteFill>
      <AbsoluteFill style={cam(0.5)}>
        <div style={{ position: "absolute", left: 80, right: 80, top: 278, ...TYPE.display(118), lineHeight: 1.06 }}>
          <Words
            frame={frame}
            words={[
              ["¿Quieres", at(word("a1", "quieres"))],
              ["salir", at(word("a1", "salir"))],
              ["a", at(word("a1", "a"))],
              ["bailar", at(word("a1", "bailar"))],
            ]}
          />{" "}
          <span
            style={{ color: C.tomato600, display: "inline-block", scale: `${1 + 0.06 * accent}`, transformOrigin: "30% 70%" }}
          >
            <Word frame={frame} start={at(word("a1", "este"))}>
              este
            </Word>{" "}
            <Word frame={frame} start={at(word("a1", "finde"))}>
              finde?
            </Word>
          </span>
        </div>
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: 680,
            ...TYPE.serif(76),
            textShadow: `0 0 24px ${C.paper}, 0 0 10px ${C.paper}`,
          }}
        >
          <Words
            frame={frame}
            distance={40}
            words={[
              ["¿Y", at(word("a1", "y"))],
              ["no", at(word("a1", "no"))],
              ["sabes", at(word("a1", "sabes"))],
              ["a", at(word("a1", "a", 1))],
              ["dónde", at(word("a1", "donde"))],
              ["ir?", at(word("a1", "ir"))],
            ]}
          />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** The tosses: motion blur on while a flyer is in the air (video frames; scene 1 starts at 0). */
export const QUESTION_BLUR = LAND.map((l) => [l - 7, l] as [number, number]);
