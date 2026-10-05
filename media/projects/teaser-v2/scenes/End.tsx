// Scene 5 (17.14–21.00): "Te dejo el link… y nos vemos bailando."
// The "Gratis" sticker arrives as the record (match cut), the app icon's tomato square pops in behind it, the
// wordmark lands letter by letter, then the sign-off and the call to action. No address on screen (the owner's
// call). Instagram keeps a Story's link sticker on screen for the whole clip, so the owner places it at the top,
// in the band above y 250 that every scene leaves empty (v2.3); the call to action sits right under it:
// "Link aquí arriba" with a drawn arrow pointing up to it, bobbing on the beat. The Reel (no link stickers there)
// says "Link en mi perfil" in the same place, without the arrow.
import React from "react";
import { AbsoluteFill } from "remotion";
import {
  AppIcon,
  Arrow,
  C,
  camera,
  kick,
  Letters,
  Record,
  rise,
  sec,
  sp,
  SPRING,
  Stripes,
  TYPE,
  useScene,
} from "../../../src/kit";
import { beats, downbeats, line, SCENES, word } from "../theme";
import { flight, RECORD_SPOT, STICKER } from "./Free";

export type Cta = "story" | "reel";
/** The band the owner keeps for Instagram's link sticker in the Story, all through the video: no element enters it. */
export const STICKER_BAND = { top: 0, bottom: 250 };

export const End: React.FC<{ cta: Cta }> = ({ cta }) => {
  const { frame, t } = useScene();
  const at = (s: number) => sec(s) - sec(SCENES.end);
  const cam = camera(t, SCENES.end, SCENES.out, { zoom: 0.03, driftX: 6, driftY: -8 });
  const fl = flight(frame);
  const icon = sp(frame, 4, SPRING.pop);
  const name = at(line("c4").start) - 2;
  const link = at(word("c4", "link")) - 3;
  const bye = at(word("c4", "nos")) - 3;
  const pulse = kick(t, downbeats(SCENES.end + 0.5, SCENES.out));
  const bob = kick(t, beats(SCENES.end + 1.2, SCENES.out));
  const ICON = 470;
  const ratio = fl.d / STICKER.d;
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill style={cam(0.6)}>
        {/* The call to action, right under the sticker's band: the arrow points up at the link. At top 276 with a
            14 px bob, the push-in and the spring's overshoot, the arrow's tip stays at y ≥ 258 on every frame
            (measured; at 268 with a 20 px bob it reached y 244, inside the band). */}
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: 276,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 0,
            ...rise(frame, link, { distance: 40 }),
          }}
        >
          {cta === "story" ? <Arrow size={132} weight={3.2} style={{ translate: `0px ${-14 * bob}px` }} /> : null}
          <div style={{ ...TYPE.sans(68), textAlign: "center" }}>
            {cta === "story" ? "Link aquí arriba" : "Link en mi perfil"}
          </div>
        </div>
      </AbsoluteFill>
      <Stripes frame={frame} start={-30} top={500} />
      <AbsoluteFill style={cam(1)}>
        <AppIcon
          size={ICON}
          style={{
            left: RECORD_SPOT.x - ICON / 2,
            top: RECORD_SPOT.y - ICON / 2,
            scale: `${(0.4 + 0.6 * icon) * (1 + 0.03 * pulse)}`,
            opacity: frame < 4 ? 0 : 1,
          }}
        />
        <Record
          size={fl.d}
          angle={-8 + fl.spin}
          style={{
            position: "absolute",
            left: fl.x - fl.d / 2,
            top: fl.y - fl.d / 2,
            scale: `${fl.scaleX * (1 + 0.03 * pulse)} ${fl.scaleY * (1 + 0.03 * pulse)}`,
            filter: `drop-shadow(0 ${10 + 30 * (1 - ratio)}px 24px rgba(42,15,20,0.3))`,
          }}
        />
      </AbsoluteFill>
      <AbsoluteFill style={cam(0.6)}>
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: RECORD_SPOT.y + 300,
            textAlign: "center",
            ...TYPE.display(168, C.tomato600),
            lineHeight: 1,
            whiteSpace: "pre",
          }}
        >
          <Letters frame={frame} start={name} text="Pa' Bailar" step={1.4} seed="end" />
        </div>
        <div
          style={{
            position: "absolute",
            left: 80,
            right: 80,
            top: RECORD_SPOT.y + 490,
            textAlign: "center",
            ...TYPE.serif(66),
            ...rise(frame, bye, { distance: 50 }),
          }}
        >
          Nos vemos bailando.
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
