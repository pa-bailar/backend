// Scene 5 (17.14–21.00): "Te dejo el link… y nos vemos bailando."
// The "Gratis" sticker arrives as the record (match cut), the app icon's tomato square pops in behind it, the
// wordmark lands letter by letter, then the sign-off and the call to action. No address on screen (the owner's
// call). Instagram keeps a Story's link sticker on screen for the whole clip, so the owner places it at the top,
// in the band above y 250 that every scene leaves empty (v2.3); the call to action sits right under it:
// "Link aquí arriba" with a drawn arrow pointing up to it, bobbing on the beat. The Reel (no link stickers there)
// says "Link en mi perfil" in the same place, without the arrow. The card is the kit's EndCard (v2.4 moved the
// call to action 8 px down and the bob from 20 to 14 px: the arrow's tip reached y 244, inside the band).
import React from "react";
import {
  AppIcon,
  C,
  camera,
  type Cta,
  EndCard,
  kick,
  Record,
  sec,
  sp,
  SPRING,
  useScene,
} from "../../../src/kit";
import { beats, downbeats, line, SCENES, word } from "../theme";
import { flight, RECORD_SPOT, STICKER } from "./Free";

export type { Cta };

export const End: React.FC<{ cta: Cta }> = ({ cta }) => {
  const { frame, t } = useScene();
  const at = (s: number) => sec(s) - sec(SCENES.end);
  const cam = camera(t, SCENES.end, SCENES.out, { zoom: 0.03, driftX: 6, driftY: -8 });
  const fl = flight(frame);
  const icon = sp(frame, 4, SPRING.pop);
  const pulse = kick(t, downbeats(SCENES.end + 0.5, SCENES.out));
  const ICON = 470;
  const ratio = fl.d / STICKER.d;
  return (
    <EndCard
      cta={cta}
      frame={frame}
      cam={cam}
      link={at(word("c4", "link")) - 3}
      bob={kick(t, beats(SCENES.end + 1.2, SCENES.out))}
      stripesAt={-30}
      name={{ at: at(line("c4").start) - 2, seed: "end" }}
      spot={RECORD_SPOT}
      signoff={{ text: "Nos vemos bailando.", at: at(word("c4", "nos")) - 3 }}
      background={C.paper}
    >
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
    </EndCard>
  );
};
