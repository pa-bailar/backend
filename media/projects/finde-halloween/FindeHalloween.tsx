// Este finde, Halloween (23–25 Oct 2026), v4: the whole video at night. Lightning opens it on "¿Ya tienes disfraz?" and
// strikes again on "¡Halloween!", where the record pops in dressed as a jack-o'-lantern, its carved face flickering
// like a candle. Then Saturday under a full moon (bats cross it as the page head comes in): the three Halloween socials
// land as she names them, their facts below; a whip to "Más sociales" and the other two. Then the rest of the weekend's flyers pile in fast while the count climbs
// to the real number ("treinta y dos planes"), and the end card stays at night (the kit's EndCard with `ink`). v1
// (afternoon into night, only the socials) felt slow to the owner: v2's take is livelier (a third shorter) and its
// cuts come quicker. The voice (Despina, one take) leads: each section on the beat at or just before its line, each
// flyer as its name is said. Music: puente's salsa (Tunetank, from 0:09.85, 90.51 bpm).
import React from "react";
import { AbsoluteFill, Composition, Folder, interpolate, interpolateColors } from "remotion";
import {
  assets,
  C,
  camera,
  capital,
  clamp,
  type Cta,
  type EndInk,
  EndCard,
  FPS,
  Flyer,
  gridOf,
  inRanges,
  jit,
  kick,
  leave,
  makeTiming,
  mix,
  priceLabel,
  Record,
  rise,
  sec,
  Shutter,
  sp,
  spinAngle,
  SPRING,
  timeLabel,
  toss,
  TYPE,
  useScene,
  type EventsSnapshot,
  vertical,
  type VideoEvent,
  VideoShell,
  whip,
  whipBlur,
  wobble,
  Word,
} from "../../src/kit";
import snapshot from "./data/events.json";
import timingJson from "./data/timing.json";
import settings from "./video.json";

/** Files in the media home's public/finde-halloween/ (flyers from tools/events.py, the mixed soundtrack). */
export const file = assets("finde-halloween");
const DURATION_S = settings.duration;
const { beats, downbeats, beatAt, BEAT } = gridOf(settings);
/** The frame of beat `n` (the song's grid from its first hit). */
const bt = (n: number) => sec(n * BEAT);
const data = snapshot as EventsSnapshot;
const { line, word } = makeTiming(timingJson);
/** The frame a word is said on. */
const said = (id: string, w: string) => sec(word(id, w));

// ---------- the night: this video's own palette (the flyers are black and orange) ----------

/** Night colors: the record's warm black, the stripes' pumpkin orange, cream type, a moonlit cream. */
const NIGHT = {
  bg: C.wine950,
  text: C.cream50,
  muted: C.cream300,
  title: C.orange600,
  shadow: "#0c0406", // the period shadow, darker than the night (the dark theme's way)
  border: C.cream300, // a flyer's frame: the black flyers need an edge on the black
  moon: "#f6ead2",
  flash: "#efe3cc", // lightning: the whole frame goes pale for a frame or two
};
const NIGHT_INK: EndInk = { text: NIGHT.text, arrow: NIGHT.title, name: NIGHT.title, shadow: NIGHT.shadow, signoff: NIGHT.muted };

// ---------- the sections, each on the beat at or just before its line ----------

const SAB = beatAt(line("sab").start);
const OTROS = beatAt(line("otros").start);
const MAS = beatAt(line("mas").start);
/** The two stages (Saturday's Halloween socials, then the two others): when each whips in and leaves. */
const STAGE_IN = [SAB, OTROS];
const STAGE_OUT = [OTROS, MAS];
const END_BEAT = beatAt(line("fin").start);
/** The two words lightning strikes on: the first frames, and "¡Halloween!". */
const HALLOWEEN = said("hook", "Halloween!");
const STRIKES = [2, HALLOWEEN - 1];

/** Lightning, 0–1: a double flash (a strike and its flicker) at each of `STRIKES`. */
function lightning(frame: number) {
  let v = 0;
  for (const s of STRIKES) {
    for (const [at, peak] of [
      [s, 1],
      [s + 4, 0.6],
    ] as const) {
      const d = frame - at;
      if (d >= 0 && d < 4) v = Math.max(v, peak * (1 - d / 4));
    }
  }
  return v;
}

// ---------- the events: the weekend's five socials (all Saturday), then the rest of the weekend ----------

/**
 * `stage`: 0 the Halloween socials, 1 the two others ("más sociales": not "sin disfraz", which the data doesn't say); `name`: the title as the flyer reads it (the data's
 * casing or its first part); `land`: the frame of its name (the owner, v2: the socials must still be named).
 */
type Shown = { id: string; stage: 0 | 1; name: string; land: number; side: -1 | 1 };
const SHOWN: Shown[] = [
  { id: "tardeo-de-muertos-24-oct", stage: 0, name: "Tardeo de Muertos", land: said("sab", "Tardeo"), side: 1 },
  {
    id: "halloween-concurso-de-disfraces-fiesta-y-taller-de-24-oct",
    stage: 0,
    name: "Concurso de disfraces",
    land: said("sab", "concurso"),
    side: -1,
  },
  { id: "social-de-halloween-24-oct", stage: 0, name: "Social de Halloween", land: said("sab", "Social"), side: 1 },
  { id: "salsa-en-digital-24-oct", stage: 1, name: "Salsa en Digital", land: said("otros", "Salsa"), side: 1 },
  { id: "latinholic-night-24-oct", stage: 1, name: "Latinholic Night", land: said("otros", "Latinholic"), side: -1 },
];
const byId = new Map(data.events.map((e) => [e.id, e]));
const shown = SHOWN.map((s) => {
  const e = byId.get(s.id);
  if (!e) throw new Error(`${s.id} isn't in data/events.json: re-run tools/events.py finde-halloween --weekend 2026-10-22`);
  return { ...s, e };
});
/** The weekend's other events with a flyer (one per flyer), for the pile; the count is every event of the snapshot. */
const OTHERS = data.events.filter(
  (e, i, all) => !SHOWN.some((s) => s.id === e.id) && e.flyer && all.findIndex((x) => x.flyer === e.flyer) === i,
);
const TOTAL = data.events.length; // "treinta y dos planes": the real count of this snapshot
/** When an event's facts leave: just before the next one on its stage lands, or as its stage leaves. */
const leaving = (i: number) => {
  const next = shown[i + 1];
  return next && next.stage === shown[i].stage ? next.land - 8 : bt(STAGE_OUT[shown[i].stage]) - 6;
};

// ---------- the record in its costume ----------

/**
 * The record dressed as a jack-o'-lantern: the kit's record turning under a pumpkin mask over its label (the mask
 * stays upright, as a face would). `glow` 0–1 lights the carved face from inside.
 */
const Pumpkin: React.FC<{ size: number; angle: number; glow?: number; style?: React.CSSProperties }> = ({
  size,
  angle,
  glow = 0,
  style,
}) => {
  const carve = interpolateColors(glow, [0, 1], [C.wine950, C.marigold400]);
  return (
    <div style={{ position: "relative", width: size, height: size, ...style }}>
      <Record size={size} angle={angle} />
      <svg viewBox="0 0 512 512" width={size} height={size} style={{ position: "absolute", left: 0, top: 0 }}>
        {/* The stem, then the pumpkin over the label (r 105 of 250: the label's 42%), then the face. */}
        <path d="M250 152 q2 -22 18 -30 l6 8 q-12 8 -12 24 z" fill="#5b6b2a" />
        <circle cx="256" cy="256" r="108" fill={C.orange600} />
        <path d="M206 238 l22 -34 l22 34 z M262 238 l22 -34 l22 34 z" fill={carve} />
        <path d="M249 262 l7 -12 l7 12 z" fill={carve} />
        <path
          d="M190 282 q66 52 132 0 l-10 24 l-14 -8 l-12 18 l-14 -12 l-16 14 l-14 -14 l-14 12 l-12 -18 l-14 8 z"
          fill={carve}
        />
      </svg>
    </div>
  );
};

/** A candle's flicker, 0.7–1 (deterministic: two slow waves and a fast one). */
const flicker = (t: number) => 0.85 + 0.08 * Math.sin(t * 7.3) + 0.05 * Math.sin(t * 13.1 + 1) + 0.02 * Math.sin(t * 29);

// ---------- the night's set: the moon, the cobwebs, the bats ----------

const MOON = { x: 850, y: 392, r: 108 };

/** The full moon behind the page head: a flat disc with a few soft maria, drawn. */
const Moon: React.FC<{ style?: React.CSSProperties }> = ({ style }) => (
  <svg
    width={MOON.r * 2}
    height={MOON.r * 2}
    viewBox="0 0 200 200"
    style={{ position: "absolute", left: MOON.x - MOON.r, top: MOON.y - MOON.r, overflow: "visible", ...style }}
  >
    <circle cx="100" cy="100" r="100" fill={NIGHT.moon} />
    <circle cx="70" cy="72" r="20" fill={C.cream300} opacity="0.55" />
    <circle cx="128" cy="118" r="26" fill={C.cream300} opacity="0.45" />
    <circle cx="84" cy="140" r="12" fill={C.cream300} opacity="0.5" />
    <circle cx="136" cy="60" r="9" fill={C.cream300} opacity="0.5" />
  </svg>
);

/** A corner cobweb: threads from the corner and sagging rings between them, drawn in a faint cream. */
const Cobweb: React.FC<{ size: number; style?: React.CSSProperties }> = ({ size, style }) => {
  const angles = [0, 18, 38, 58, 76, 90];
  const ray = (a: number, r: number) => [r * Math.cos((a * Math.PI) / 180), r * Math.sin((a * Math.PI) / 180)];
  const rings = [0.3, 0.52, 0.74, 0.96].map((k) =>
    angles
      .slice(1)
      .map((a, i) => {
        const [x0, y0] = ray(angles[i], size * k);
        const [x1, y1] = ray(a, size * k);
        const [mx, my] = ray((a + angles[i]) / 2, size * k * 0.86); // sags toward the corner
        return `${i === 0 ? `M${x0} ${y0}` : ""} Q${mx} ${my} ${x1} ${y1}`;
      })
      .join(" "),
  );
  return (
    <svg width={size} height={size} style={{ position: "absolute", overflow: "visible", transformOrigin: "0 0", ...style }}>
      <g stroke={C.cream300} strokeOpacity="0.32" strokeWidth="2.2" fill="none">
        {angles.map((a) => {
          const [x, y] = ray(a, size);
          return <path key={a} d={`M0 0 L${x} ${y}`} />;
        })}
        {rings.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
    </svg>
  );
};

/** A bat in flight: the wings beat (squash on the up-stroke). Black: a silhouette against the moon. */
const Bat: React.FC<{ size: number; flap: number; color: string; style?: React.CSSProperties }> = ({ size, flap, color, style }) => (
  <svg viewBox="0 0 100 50" width={size} height={size / 2} style={{ position: "absolute", overflow: "visible", ...style }}>
    <g style={{ transformOrigin: "50px 22px", transform: `scaleY(${0.35 + 0.65 * Math.abs(Math.cos(flap))})` }}>
      <path
        d="M50 20 C45 12 40 12 37 16 C31 6 18 4 2 14 C12 15 16 22 14 30 C21 25 29 27 33 34 C37 29 44 29 50 37 C56 29 63 29 67 34 C71 27 79 25 86 30 C84 22 88 15 98 14 C82 4 69 6 63 16 C60 12 55 12 50 20 Z"
        fill={color}
      />
    </g>
    <path d="M45 18 l2 -8 l3 5 l3 -5 l2 8 z" fill={color} />
  </svg>
);

/** Bats crossing the moon once, right to left, as Saturday's page head comes in. */
const Bats: React.FC<{ frame: number; t: number; start: number }> = ({ frame, t, start }) => (
  <>
    {[0, 1, 2, 3].map((i) => {
      const go = start + i * 4 + jit(`bat${i}`, 2);
      const k = interpolate(frame, [go, go + 30], [0, 1], { ...clamp });
      if (k <= 0 || k >= 1) return null;
      const size = [190, 130, 160, 110][i];
      const y0 = [520, 640, 460, 580][i];
      return (
        <Bat
          key={i}
          size={size}
          flap={t * 2 * Math.PI * 3.4 + i}
          color={NIGHT.shadow}
          style={{
            left: mix(1160, -220, k),
            // Each arcs up through the moon's height (y 284–500), then away.
            top: mix(y0, 300 + 30 * i, k) - 150 * Math.sin(Math.PI * k),
            rotate: `${-12 + 18 * k}deg`,
          }}
        />
      );
    })}
  </>
);

// ---------- the page head ----------

/** "Sábado" over "24 de octubre · Halloween", left of the moon. */
const Head: React.FC<{ frame: number; start: number }> = ({ frame, start }) => (
  <>
    <div
      style={{
        position: "absolute",
        left: 80,
        top: 318,
        ...TYPE.display(132, NIGHT.title, NIGHT.shadow),
        lineHeight: 1,
        ...rise(frame, start, { distance: 50 }),
      }}
    >
      Sábado
    </div>
    {/* Digits: the sans. */}
    <div style={{ position: "absolute", left: 86, top: 468, ...TYPE.sans(42, NIGHT.muted), ...rise(frame, start + 4, { distance: 30 }) }}>
      24 de octubre · Halloween
    </div>
  </>
);

// ---------- Saturday's stage: its pile of flyers and the facts of the one on top ----------

const BOX = { w: 600, h: 736, top: 572 }; // where a flyer may stand: under the head, above the facts
const FACTS_TOP = 1340;

const Facts: React.FC<{ frame: number; e: VideoEvent; name: string; at: number; exitAt: number }> = ({ frame, e, name, at, exitAt }) => {
  const when = [timeLabel(e.day_start), priceLabel(e.prices)].filter(Boolean).join(" · ");
  const where = [e.venue, `@${e.account}`].filter(Boolean).join(" · ");
  return (
    <div style={{ position: "absolute", left: 90, right: 130, top: FACTS_TOP }}>
      {/* Times and prices in the sans: Bodoni's italic 4 reads as a 1. */}
      <div style={{ ...TYPE.sans(40, NIGHT.title), ...rise(frame, at, { distance: 40, exitAt }) }}>{capital(when)}</div>
      <div
        style={{
          ...TYPE.display(70, NIGHT.text, NIGHT.shadow),
          lineHeight: 1.05,
          margin: "8px 0 10px",
          ...rise(frame, at + 2 + jit(`t${e.id}`, 1), { distance: 50, exitAt }),
        }}
      >
        {name}
      </div>
      <div
        style={{
          ...TYPE.sans(32, NIGHT.muted),
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          ...rise(frame, at + 5, { distance: 30, exitAt }),
        }}
      >
        {where}
      </div>
    </div>
  );
};

/** A flyer on the black: a cream edge, a deeper shadow. */
const nightCard = (lift: number): React.CSSProperties => ({
  borderColor: NIGHT.border,
  boxShadow: `0 ${10 + 50 * lift}px ${18 + 70 * lift}px rgba(0,0,0,0.55)`,
});

/** A stage: it whips in from the right; Saturday's whips out to the left, the last drops out for the pile. */
const Stage: React.FC<{ frame: number; abs: number; stage: 0 | 1 }> = ({ frame, abs, stage }) => {
  const items = shown.filter((s) => s.stage === stage);
  let x = 1080 * (1 - whip(abs, bt(STAGE_IN[stage])).p);
  if (stage === 0) {
    const w = whip(abs, bt(STAGE_OUT[0]));
    x += -1080 * w.p - w.dip;
  }
  const drop = stage === 1 ? leave(frame, bt(MAS) - 2, 8) : 0;
  const landings = items.map((s) => s.land - 8); // tossed 8 frames before the name, so it lands on it
  // "Más sociales" while she says it, until its first flyer comes in.
  const askAt = Math.min(said("otros", "más") - 2, bt(OTROS) + 4);
  return (
    <AbsoluteFill style={{ translate: `${x}px ${900 * drop}px`, opacity: 1 - drop }}>
      {stage === 1 ? (
        <div
          style={{
            position: "absolute",
            left: 60,
            right: 60,
            top: 800,
            textAlign: "center",
            ...TYPE.display(150, NIGHT.title, NIGHT.shadow),
            ...rise(frame, askAt, { distance: 70, exitAt: landings[0] }),
          }}
        >
          Más sociales
        </div>
      ) : null}
      {items.map((s, i) => {
        const ratio = s.e.ratio ?? 0.8;
        const width = Math.min(BOX.w, BOX.h * ratio);
        const height = width / ratio;
        const rot = (i % 2 ? 1 : -1) * (2 + i) + wobble(frame, landings.slice(i + 1).map((l) => l + 9), 1.6);
        const t = toss(frame, landings[i], { side: s.side, rot, fromX: 820, fromY: 380, arc: 120 });
        return (
          <Flyer
            key={s.id}
            src={file(s.e.flyer!)}
            width={width}
            ratio={ratio}
            lift={t.lift}
            style={{ left: (1080 - width) / 2, top: BOX.top + (BOX.h - height) / 2, ...nightCard(t.lift), ...t.style }}
          />
        );
      })}
      {items.map((s) => (
        <Facts key={s.id} frame={frame} e={s.e} name={s.name} at={s.land} exitAt={leaving(shown.indexOf(s))} />
      ))}
    </AbsoluteFill>
  );
};

// ---------- the rest of the weekend: a fast pile and the count climbing to the real number ----------

const Pile: React.FC<{ frame: number }> = ({ frame }) => {
  const start = bt(MAS) - 2;
  const out = leave(frame, bt(END_BEAT) - 3, 7);
  const many = OTHERS.slice(0, 20);
  // The count reaches the real total as she says "dos" ("treinta y dos").
  const full = said("mas", "dos");
  const count = Math.round(interpolate(frame, [start + 4, full], [SHOWN.length, TOTAL], clamp));
  return (
    <AbsoluteFill style={{ opacity: 1 - out, translate: `0px ${120 * out}px` }}>
      {many.map((e, i) => {
        const go = start + Math.round(i * 2.2) + jit(`p${i}`, 1);
        const ratio = e.ratio ?? 0.8;
        const width = 360;
        const t = toss(frame, go, { side: i % 2 ? 1 : -1, rot: ((i * 37) % 25) - 12, fromX: 780, fromY: 480, arc: 90, spin: 44 });
        return (
          <Flyer
            key={e.id}
            src={file(e.flyer!)}
            width={width}
            ratio={ratio}
            lift={t.lift}
            style={{
              // Scattered over the stage's middle, inside the frame (x 200–880 for a 360 px flyer).
              left: (1080 - width) / 2 + ((i * 113) % 320) - 160,
              top: 600 + ((i * 71) % 230) - 40,
              ...nightCard(t.lift),
              ...t.style,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: 90,
          right: 130,
          top: FACTS_TOP + 6,
          padding: "20px 30px 24px",
          background: C.wine900,
          border: `4px solid ${NIGHT.title}`,
          borderRadius: 14,
          boxShadow: `8px 8px 0 ${NIGHT.shadow}`,
          ...rise(frame, said("mas", "total,") - 2, { distance: 60, config: SPRING.pop }),
        }}
      >
        {/* The count is digits: the sans. It kicks as it lands on the total. */}
        <div
          style={{
            ...TYPE.sans(92, NIGHT.title),
            lineHeight: 1,
            scale: `${1 + 0.06 * kick(frame / FPS, [full / FPS])}`,
            transformOrigin: "0 50%",
          }}
        >
          {count} planes
        </div>
        <div style={{ ...TYPE.serif(54, NIGHT.text), marginTop: 6 }}>este finde, en Pa' Bailar</div>
      </div>
    </AbsoluteFill>
  );
};

// ---------- the video ----------

/** Fast moves that get motion blur: the whip into Saturday, the pile's tosses and the end's drop. */
const FAST: [number, number][] = [
  whipBlur(bt(SAB)),
  whipBlur(bt(OTROS)),
  [bt(MAS) - 2, bt(MAS) + 50],
  [bt(END_BEAT) - 3, bt(END_BEAT) + 6],
];

/** `blur` is the kit's render convention (render.py --draft turns it off). */
export const FindeHalloween: React.FC<{ cta: Cta; blur?: boolean }> = ({ cta, blur = true }) => {
  const { frame, abs, t } = useScene();
  const cam = camera(t, 0, DURATION_S, { zoom: 0.035, driftX: 8, driftY: -10 });
  const END = bt(END_BEAT);
  const flash = lightning(frame);
  // The hook in two phrases: "¿Ya tienes disfraz?", then "¡Este finde es de Halloween!" in its place.
  const firstOut = said("hook", "Este") - 6;
  const hookOut = bt(SAB) - 4;
  const pumpkinAt = HALLOWEEN - 2;
  const pumpkinOut = leave(frame, bt(SAB) - 4, 8);
  const glow = interpolate(frame, [pumpkinAt + 6, pumpkinAt + 16], [0, 1], clamp) * flicker(t);
  return (
    <VideoShell
      fadeIn={0}
      audio={file("audio/with-music.wav")}
      story={cta === "story"}
      background={interpolateColors(flash, [0, 1], [NIGHT.bg, NIGHT.flash])}
    >
      <Shutter samples={blur && inRanges(frame, FAST) ? 8 : 1}>
        {/* The set: the cobwebs in two corners all through, the moon once the hook is gone (behind the head). */}
        <AbsoluteFill style={cam(0.4)}>
          <Cobweb size={300} style={{ left: 0, top: 266 }} />
          <Cobweb size={240} style={{ left: 1080, top: 1580, rotate: "180deg" }} />
          {frame >= bt(SAB) + 2 && frame < END + 8 ? (
            <Moon
              style={{
                opacity: interpolate(frame, [bt(SAB) + 2, bt(SAB) + 12], [0, 1], clamp) * (1 - leave(frame, END - 2, 8)),
                translate: `0px ${40 * (1 - sp(frame, bt(SAB) + 2, SPRING.sheet))}px`,
              }}
            />
          ) : null}
        </AbsoluteFill>
        {frame >= bt(SAB) - 4 && frame < END + 8 ? (
          <AbsoluteFill style={cam(0.7)}>
            <Bats frame={frame} t={t} start={bt(SAB) - 2} />
          </AbsoluteFill>
        ) : null}
        {/* The hook, at 0 s: the question, no logo (Instagram practices, media/README.md). */}
        {frame < bt(SAB) + 4 ? (
          <AbsoluteFill style={{ ...cam(0.6), opacity: 1 - leave(frame, hookOut, 6) }}>
            <div
              style={{ position: "absolute", left: 60, right: 60, top: 360, textAlign: "center", opacity: 1 - leave(frame, firstOut, 5) }}
            >
              <div style={{ ...TYPE.display(112, NIGHT.text, NIGHT.shadow), lineHeight: 1.1 }}>
                {/* Each word 2 frames before she says it. */}
                <Word frame={frame} start={said("hook", "Ya") - 2}>
                  ¿Ya
                </Word>{" "}
                <Word frame={frame} start={said("hook", "tienes") - 2}>
                  tienes
                </Word>
              </div>
              <div style={{ ...TYPE.display(184, NIGHT.title, NIGHT.shadow), lineHeight: 1.1, marginTop: 10 }}>
                <Word frame={frame} start={said("hook", "disfraz?") - 2} pulse={kick(t, [word("hook", "disfraz?")])}>
                  disfraz?
                </Word>
              </div>
            </div>
            {frame >= firstOut ? (
              <div style={{ position: "absolute", left: 60, right: 60, top: 330, textAlign: "center" }}>
                <div style={{ ...TYPE.display(100, NIGHT.text, NIGHT.shadow), lineHeight: 1.1 }}>
                  <Word frame={frame} start={said("hook", "Este") - 2}>
                    ¡Este
                  </Word>{" "}
                  <Word frame={frame} start={said("hook", "finde") - 2}>
                    finde
                  </Word>{" "}
                  <Word frame={frame} start={said("hook", "es") - 2}>
                    es de
                  </Word>
                </div>
                <div style={{ ...TYPE.display(168, NIGHT.title, NIGHT.shadow), lineHeight: 1.1, marginTop: 10 }}>
                  <Word frame={frame} start={HALLOWEEN - 2} pulse={kick(t, [word("hook", "Halloween!")])}>
                    Halloween!
                  </Word>
                </div>
              </div>
            ) : null}
          </AbsoluteFill>
        ) : null}
        {frame >= pumpkinAt && frame < bt(SAB) + 8 ? (
          <AbsoluteFill style={cam(1)}>
            <Pumpkin
              size={480}
              angle={spinAngle(t, pumpkinAt / FPS, 0.6)}
              glow={glow}
              style={{
                position: "absolute",
                left: 540 - 240,
                top: 800,
                opacity: 1 - pumpkinOut,
                translate: `0px ${700 * pumpkinOut}px`,
                scale: `${0.3 + 0.7 * sp(frame, pumpkinAt, SPRING.pop)}`,
                rotate: `${-10 * (1 - sp(frame, pumpkinAt, SPRING.pop))}deg`,
              }}
            />
          </AbsoluteFill>
        ) : null}
        {/* Saturday: the page head, its stage, then the rest of the weekend. */}
        {frame >= bt(SAB) - 4 && frame < END + 8 ? (
          <AbsoluteFill style={{ ...cam(0.6), opacity: 1 - leave(frame, END - 2, 8) }}>
            <Head frame={frame} start={bt(SAB)} />
          </AbsoluteFill>
        ) : null}
        {([0, 1] as const).map((stage) =>
          frame >= bt(STAGE_IN[stage]) - 8 && frame < bt(STAGE_OUT[stage]) + 12 ? (
            <Stage key={stage} frame={frame} abs={abs} stage={stage} />
          ) : null,
        )}
        {frame >= bt(MAS) - 4 && frame < END + 8 ? <Pile frame={frame} /> : null}
        {frame >= END ? (
          <EndCard
            cta={cta}
            frame={frame}
            cam={cam}
            ink={NIGHT_INK}
            link={said("fin", "Te") - 4}
            bob={kick(t, beats(word("fin", "link") + 0.2, DURATION_S))}
            stripesAt={END + 2}
            name={{ at: said("fin", "Pa'") - 2, size: 150, step: 1.2, seed: "finde-halloween" }}
            spot={{ x: 540, y: 760 }}
            signoff={{ text: "Nos vemos bailando.", at: said("fin", "link") + 10 }}
          >
            <Pumpkin
              size={340}
              angle={spinAngle(t, END / FPS, 0.6)}
              glow={interpolate(frame, [END + 8, END + 18], [0, 1], clamp) * flicker(t)}
              style={{
                position: "absolute",
                left: 540 - 170,
                top: 724 - 170,
                scale: `${(0.3 + 0.7 * sp(frame, END + 2, SPRING.weight)) * (1 + 0.03 * kick(t, downbeats(END / FPS + 0.1, DURATION_S)))}`,
              }}
            />
            <div
              style={{
                position: "absolute",
                left: 80,
                right: 80,
                top: 942,
                textAlign: "center",
                ...TYPE.serif(76, NIGHT.text),
                ...rise(frame, said("fin", "Todo") - 2, { distance: 40 }),
              }}
            >
              Todo en
            </div>
          </EndCard>
        ) : null}
      </Shutter>
    </VideoShell>
  );
};

export const FindeHalloweenVideo: React.FC = () => (
  <Folder name="finde-halloween">
    <Composition
      id="finde-halloween-story"
      component={FindeHalloween}
      {...vertical(settings)}
      defaultProps={{ cta: "story" as const, blur: true }}
    />
  </Folder>
);
