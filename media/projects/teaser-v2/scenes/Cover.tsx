// Scene 2 (4.29–6.12): "Por eso hice Pa' Bailar."
// The app icon as a 70s salsa cover coming alive. It opens as a tomato disc growing out of the record's spot
// (an iris, the record's shape), the record drops in and spins up like a platter, the wordmark's letters
// land one after another as the name is said.
import React from "react";
import { AbsoluteFill } from "remotion";
import { C, camera, iris, kick, Letters, Record, rise, sec, sp, spinAngle, SPRING, TYPE, useScene } from "../../../src/kit";
import { BAR, SCENES, word } from "../theme";

export const IRIS_FRAMES = 8; // the iris opens over the last 8 frames of scene 1
const CENTER = { x: 540, y: 710 };

export const Cover: React.FC = () => {
  const { frame, t } = useScene();
  const at = (s: number) => sec(s) - sec(SCENES.cover);
  const cam = camera(t, SCENES.cover - IRIS_FRAMES / 30, SCENES.app, { zoom: 0.06, driftX: -10, driftY: -12 });
  const rec = sp(frame, -5, SPRING.weight);
  const beat = kick(t, [2 * BAR]); // the downbeat at 4.90
  const name = at(word("a2s", "Pa'")) - 3;
  return (
    <AbsoluteFill style={{ clipPath: iris(frame, CENTER, IRIS_FRAMES), background: C.tomato600 }}>
      <AbsoluteFill style={cam(1)}>
        <Record
          size={660}
          angle={spinAngle(t, SCENES.cover - IRIS_FRAMES / 30, 0.7) - 40}
          style={{
            position: "absolute",
            left: CENTER.x - 330,
            top: CENTER.y - 330,
            scale: `${(0.35 + 0.65 * rec) * (1 + 0.035 * beat)}`,
            filter: `drop-shadow(0 ${18 + 30 * (1 - rec)}px ${30 + 40 * (1 - rec)}px rgba(42,15,20,0.35))`,
          }}
        />
      </AbsoluteFill>
      <AbsoluteFill style={cam(0.6)}>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 1090,
            textAlign: "center",
            ...TYPE.display(168, C.cream50, C.wine900),
            lineHeight: 1,
            whiteSpace: "pre",
          }}
        >
          <Letters frame={frame} start={name} text="Pa' Bailar" step={0.9} seed="cover" />
        </div>
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: 1310,
            textAlign: "center",
            ...TYPE.serif(64, C.cream50),
            lineHeight: 1.2,
            ...rise(frame, name + 8, { distance: 50 }),
          }}
        >
          Sociales y talleres de baile
          <br />
          en Bogotá
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
