// Scene 4 (14.69–17.14): "No hay que registrarse, es gratis."
// The two objections removed, in the site's own language: the stripes, and a round sticker like the date
// sticker. The sticker pops in on "gratis", sways on the beat, then (anticipation: it squashes) launches up and
// becomes the record of the end card: a match cut on its shape and spin.
import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import {
  C,
  camera,
  clamp,
  FONT,
  FPS,
  kick,
  leave,
  sec,
  sp,
  spinAngle,
  SPRING,
  Sticker,
  Stripes,
  TYPE,
  useScene,
  Word,
} from "../../../src/kit";
import { beats, line, SCENES, word } from "../theme";

const END = sec(SCENES.end) - sec(SCENES.free); // the cut, in scene frames
export const STICKER = { x: 540, y: 1090, d: 540 };
export const RECORD_SPOT = { x: 540, y: 600, d: 400 };
export const LAUNCH = -5; // frames before the cut when the sticker takes off

/**
 * The sticker's (then the record's) flight, shared by both scenes: the match cut. From its place to the record's
 * spot on a weighty spring, spinning faster as it goes. `rel` = frames relative to the cut.
 */
export function flight(rel: number) {
  const k = sp(rel, LAUNCH, SPRING.weight);
  const squash = interpolate(rel, [LAUNCH - 7, LAUNCH - 2, LAUNCH + 1], [0, 1, 0], clamp);
  const speed = sp(rel, LAUNCH, SPRING.snap) - sp(rel - 1, LAUNCH, SPRING.snap);
  return {
    x: STICKER.x + (RECORD_SPOT.x - STICKER.x) * k,
    y: STICKER.y + (RECORD_SPOT.y - STICKER.y) * k,
    d: STICKER.d + (RECORD_SPOT.d - STICKER.d) * k,
    scaleX: 1 + 0.06 * squash - 0.1 * speed,
    scaleY: 1 - 0.08 * squash + 0.25 * speed,
    // spin: a turntable spin-up from the launch, carried on by the record after the cut
    spin: spinAngle(rel / FPS, LAUNCH / FPS, 0.35),
  };
}

export const Free: React.FC = () => {
  const { frame, t } = useScene();
  const at = (s: number) => sec(s) - sec(SCENES.free);
  const cam = camera(t, SCENES.free, SCENES.end, { zoom: 0.04, driftX: -8, driftY: -10 });
  const say = at(line("c3").start);
  const reg = at(word("c3", "registrarse"));
  const gratis = at(word("c3", "gratis")) - 4;
  const out = (delay: number) => leave(frame, END - 9 + delay);
  const pop = sp(frame, gratis, SPRING.pop);
  const sway = kick(t, beats(SCENES.free + 1.6, SCENES.end)); // a nudge on each beat once it's in
  const fl = flight(frame - END);
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <Stripes frame={frame} start={-3} top={270} />
      <AbsoluteFill style={cam(0.5)}>
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: 380,
            ...TYPE.display(124),
            opacity: 1 - out(0),
            translate: `0px ${-40 * out(0)}px`,
          }}
        >
          <Word frame={frame} start={say - 2}>
            Sin
          </Word>{" "}
          <Word frame={frame} start={say + 3} style={{ color: C.tomato600 }}>
            registro.
          </Word>
        </div>
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: 548,
            ...TYPE.serif(68),
            opacity: 1 - out(2),
            translate: `0px ${-40 * out(2)}px`,
          }}
        >
          <Word frame={frame} start={reg - 2} distance={40}>
            Ni cuentas,
          </Word>{" "}
          <Word frame={frame} start={reg + 5} distance={40}>
            ni contraseñas.
          </Word>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={cam(1)}>
        {frame >= gratis ? (
          <Sticker
            d={fl.d}
            style={{
              left: fl.x - fl.d / 2,
              top: fl.y - fl.d / 2,
              rotate: `${-8 - 30 * (1 - pop) + 3 * sway + fl.spin}deg`,
              scale: `${pop * fl.scaleX} ${pop * fl.scaleY}`,
            }}
          >
            <div style={{ fontFamily: FONT.display, fontSize: 132 * (fl.d / STICKER.d), lineHeight: 1 }}>Gratis</div>
            <div style={{ ...TYPE.sans(60 * (fl.d / STICKER.d), C.cream50), marginTop: 10 }}>$0</div>
          </Sticker>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
