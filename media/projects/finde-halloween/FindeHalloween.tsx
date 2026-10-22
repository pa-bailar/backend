// Este finde, Halloween (Saturday 24 Oct 2026): the weekend's socials, all on Saturday, from the afternoon into the
// night. The hook asks "¿Y ya tienes disfraz pa'l sábado?" while the record pops in dressed as a jack-o'-lantern (it
// has its costume). Then the page head "Sábado de tarde" and the afternoon's social (Tardeo de Muertos); on "En la
// noche" the night falls (the paper darkens, three bats cross the head once, "de tarde" becomes "de noche") and the
// night's two Halloween socials land; then "¿Sin disfraz?" and the two without a costume; the end card stays at night.
// The voice (Despina, one take) leads: each section on the beat at or just before its line, each flyer as its name is
// said, the facts under it. Music: puente's salsa (Tunetank, from 0:09.85, 90.51 bpm) until the owner picks one.
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
  Stripes,
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

/** Night colors: the record's warm black, the stripes' pumpkin orange, cream type. */
const NIGHT = {
  bg: C.wine950,
  text: C.cream50,
  muted: C.cream300,
  title: C.orange600,
  shadow: "#0c0406", // the period shadow, darker than the night (the dark theme's way)
  border: C.cream300, // a flyer's frame: the black flyers need an edge on the black
};
const NIGHT_INK: EndInk = { text: NIGHT.text, arrow: NIGHT.title, name: NIGHT.title, shadow: NIGHT.shadow, signoff: NIGHT.muted };

// ---------- the sections, each on the beat at or just before its line ----------

const TARDE = beatAt(line("tarde").start);
const NOCHE = beatAt(line("noche").start);
const SIN = beatAt(line("sin").start);
const END_BEAT = beatAt(line("fin").start);
/** When each stage whips in (the first one rises with the page head) and out. */
const STAGE_IN = [TARDE, NOCHE, SIN];
const STAGE_OUT = [NOCHE, SIN, END_BEAT];
/** Night falls over the whip into the night's stage: 0 (paper) → 1 (night). */
const nightAt = (frame: number) => interpolate(frame, [bt(NOCHE) - 6, bt(NOCHE) + 14], [0, 1], { ...clamp });

// ---------- the events: the weekend's five socials (all Saturday), in the order she names them ----------

/** `name`: the title as the flyer reads it (the data's casing or its first part); `land`: the frame of its name. */
type Shown = { id: string; stage: 0 | 1 | 2; name: string; land: number; side: -1 | 1 };
const SHOWN: Shown[] = [
  { id: "tardeo-de-muertos-24-oct", stage: 0, name: "Tardeo de Muertos", land: said("tarde", "Tardeo"), side: 1 },
  {
    id: "halloween-concurso-de-disfraces-fiesta-y-taller-de-24-oct",
    stage: 1,
    name: "Concurso de disfraces",
    land: said("noche", "concurso"),
    side: 1,
  },
  { id: "social-de-halloween-24-oct", stage: 1, name: "Social de Halloween", land: said("noche", "Social"), side: -1 },
  { id: "salsa-en-digital-24-oct", stage: 2, name: "Salsa en Digital", land: said("sin", "Salsa"), side: 1 },
  { id: "latinholic-night-24-oct", stage: 2, name: "Latinholic Night", land: said("sin", "Latinholic"), side: -1 },
];
const byId = new Map(data.events.map((e) => [e.id, e]));
const shown = SHOWN.map((s) => {
  const e = byId.get(s.id);
  if (!e) throw new Error(`${s.id} isn't in data/events.json: re-run tools/events.py finde-halloween --weekend 2026-10-24`);
  return { ...s, e };
});
const SOCIALS = data.events.filter((e) => e.event_type === "social").length;
/** When an event's facts leave: just before the next one lands, or as its stage whips out. */
const leaving = (i: number) => {
  const next = shown[i + 1];
  return next && next.stage === shown[i].stage ? next.land - 8 : bt(STAGE_OUT[shown[i].stage]) - 6;
};

// ---------- the record in its costume ----------

/**
 * The record dressed as a jack-o'-lantern: the kit's record turning under a pumpkin mask over its label (the mask
 * stays upright, as a face would). `glow` 0–1 lights the carved face from inside (at night).
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

// ---------- bats: night arrives ----------

/** A bat in flight: the wings beat (squash on the up-stroke); drawn, in the night's orange like Bembé's flyer. */
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

/** Three bats crossing the page head once, right to left on rising arcs, as the night falls. */
const Bats: React.FC<{ frame: number; t: number; start: number }> = ({ frame, t, start }) => (
  <>
    {[0, 1, 2].map((i) => {
      const go = start + i * 5 + jit(`bat${i}`, 2);
      const k = interpolate(frame, [go, go + 34], [0, 1], { ...clamp });
      if (k <= 0 || k >= 1) return null;
      const size = [210, 150, 176][i];
      const y0 = [700, 820, 620][i];
      return (
        <Bat
          key={i}
          size={size}
          flap={t * 2 * Math.PI * 3.2 + i}
          color={NIGHT.title}
          style={{
            left: mix(1140, -160, k),
            top: mix(y0, 330 + 40 * i, k) - 90 * Math.sin(Math.PI * k),
            rotate: `${-10 + 14 * k}deg`,
          }}
        />
      );
    })}
  </>
);

// ---------- the page head ----------

/** "Sábado de tarde" → "de noche", over "24 de octubre · 5 sociales"; the stripes above, wiping in. */
const Head: React.FC<{ frame: number; start: number; night: number }> = ({ frame, start, night }) => {
  const title = interpolateColors(night, [0, 1], [C.tomato700, NIGHT.title]);
  const shadow = interpolateColors(night, [0, 1], [C.cream300, NIGHT.shadow]);
  const italic = interpolateColors(night, [0, 1], [C.wine500, NIGHT.text]);
  const muted = interpolateColors(night, [0, 1], [C.cocoa500, NIGHT.muted]);
  const swap = bt(NOCHE) + 2;
  return (
    <>
      <Stripes frame={frame} start={start} top={290} />
      <div style={{ position: "absolute", left: 80, right: 80, top: 344, display: "flex", alignItems: "baseline", gap: 26 }}>
        <div style={{ ...TYPE.display(112, title, shadow), lineHeight: 1, ...rise(frame, start + 3, { distance: 50 }) }}>
          Sábado
        </div>
        <div style={{ position: "relative", ...TYPE.serif(76, italic) }}>
          <span style={{ display: "inline-block", ...rise(frame, start + 6 + jit("tarde", 1), { distance: 40, exitAt: swap - 6 }) }}>
            de tarde
          </span>
          <span style={{ position: "absolute", left: 0, top: 0, whiteSpace: "nowrap", display: "inline-block", ...rise(frame, swap, { distance: 40 }) }}>
            de noche
          </span>
        </div>
      </div>
      {/* Digits: the sans. */}
      <div style={{ position: "absolute", left: 84, top: 474, ...TYPE.sans(40, muted), ...rise(frame, start + 9, { distance: 30 }) }}>
        24 de octubre · {SOCIALS} sociales
      </div>
    </>
  );
};

// ---------- a stage: its pile of flyers and the facts of the one on top ----------

const BOX = { w: 600, h: 736, top: 572 }; // where a flyer may stand: under the head, above the facts
const FACTS_TOP = 1340;

const Facts: React.FC<{ frame: number; e: VideoEvent; name: string; at: number; exitAt: number; night: number }> = ({
  frame,
  e,
  name,
  at,
  exitAt,
  night,
}) => {
  const when = [timeLabel(e.day_start), priceLabel(e.prices)].filter(Boolean).join(" · ");
  const where = [e.venue, `@${e.account}`].filter(Boolean).join(" · ");
  return (
    <div style={{ position: "absolute", left: 90, right: 130, top: FACTS_TOP }}>
      {/* Times and prices in the sans: Bodoni's italic 4 reads as a 1. */}
      <div style={{ ...TYPE.sans(40, night ? NIGHT.title : C.tomato600), ...rise(frame, at, { distance: 40, exitAt }) }}>
        {capital(when)}
      </div>
      <div
        style={{
          ...TYPE.display(68, night ? NIGHT.text : C.wine900, night ? NIGHT.shadow : C.cream300),
          lineHeight: 1.05,
          margin: "8px 0 10px",
          ...rise(frame, at + 2 + jit(`t${e.id}`, 1), { distance: 50, exitAt }),
        }}
      >
        {name}
      </div>
      <div
        style={{
          ...TYPE.sans(32, night ? NIGHT.muted : C.cocoa500),
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

const Stage: React.FC<{ frame: number; abs: number; stage: 0 | 1 | 2 }> = ({ frame, abs, stage }) => {
  const items = shown.filter((s) => s.stage === stage);
  const night = stage > 0 ? 1 : 0;
  let x = 0;
  if (stage > 0) x += 1080 * (1 - whip(abs, bt(STAGE_IN[stage])).p);
  if (stage < 2) {
    const w = whip(abs, bt(STAGE_OUT[stage]));
    x += -1080 * w.p - w.dip;
  }
  // The last stage drops out of the way for the end card.
  const drop = stage === 2 ? leave(frame, bt(END_BEAT) - 3, 7) : 0;
  const landings = items.map((s) => s.land - 8); // tossed 8 frames before the name, so it lands on it
  // "¿Sin disfraz?" while she asks it, until its first flyer comes in.
  const askAt = Math.min(said("sin", "Sin") - 2, bt(SIN) + 4);
  return (
    <AbsoluteFill style={{ translate: `${x}px ${900 * drop}px`, opacity: 1 - drop }}>
      {stage === 2 ? (
        <div
          style={{
            position: "absolute",
            left: 60,
            right: 60,
            top: 800,
            textAlign: "center",
            ...TYPE.display(140, NIGHT.title, NIGHT.shadow),
            ...rise(frame, askAt, { distance: 70, exitAt: landings[0] }),
          }}
        >
          ¿Sin disfraz?
        </div>
      ) : null}
      {items.map((s, i) => {
        const ratio = s.e.ratio ?? 0.8;
        const width = Math.min(BOX.w, BOX.h * ratio);
        const height = width / ratio;
        const rot = (i % 2 ? 1 : -1) * (2 + i) + wobble(frame, landings.slice(i + 1).map((l) => l + 9), 1.4);
        const t = toss(frame, landings[i], { side: s.side, rot, fromX: 820, fromY: 380, arc: 110 });
        return (
          <Flyer
            key={s.id}
            src={file(s.e.flyer!)}
            width={width}
            ratio={ratio}
            lift={t.lift}
            style={{
              left: (1080 - width) / 2,
              top: BOX.top + (BOX.h - height) / 2,
              ...(night ? { borderColor: NIGHT.border, boxShadow: `0 ${10 + 50 * t.lift}px ${18 + 70 * t.lift}px rgba(0,0,0,0.5)` } : {}),
              ...t.style,
            }}
          />
        );
      })}
      {items.map((s) => (
        <Facts key={s.id} frame={frame} e={s.e} name={s.name} at={s.land} exitAt={leaving(shown.indexOf(s))} night={night} />
      ))}
    </AbsoluteFill>
  );
};

// ---------- the video ----------

/** Fast moves that get motion blur: the two whips and the last stage's drop. */
const FAST: [number, number][] = [whipBlur(bt(NOCHE)), whipBlur(bt(SIN)), [bt(END_BEAT) - 3, bt(END_BEAT) + 6]];

/** `blur` is the kit's render convention (render.py --draft turns it off). */
export const FindeHalloween: React.FC<{ cta: Cta; blur?: boolean }> = ({ cta, blur = true }) => {
  const { frame, abs, t } = useScene();
  const cam = camera(t, 0, DURATION_S, { zoom: 0.03, driftX: 8, driftY: -10 });
  const END = bt(END_BEAT);
  const night = nightAt(frame);
  const hookOut = sec(line("hook").end) - 2;
  // The record in its costume pops in as she says "disfraz", and drops out as the afternoon comes in.
  const pumpkinAt = said("hook", "disfraz") - 2;
  const pumpkinOut = leave(frame, bt(TARDE) - 2, 8);
  return (
    <VideoShell fadeIn={6} audio={file("audio/with-music.wav")} story={cta === "story"} background={interpolateColors(night, [0, 1], [C.paper, NIGHT.bg])}>
      <Shutter samples={blur && inRanges(frame, FAST) ? 8 : 1}>
        {/* The hook, at 0 s: the question, no logo (Instagram practices, media/README.md). */}
        {frame < bt(TARDE) + 8 ? (
          <AbsoluteFill style={cam(0.6)}>
            <div style={{ position: "absolute", left: 60, right: 60, top: 330, textAlign: "center", opacity: 1 - leave(frame, hookOut, 6) }}>
              <div style={{ ...TYPE.display(104, C.wine900), lineHeight: 1.1 }}>
                {/* Each word 2 frames before she says it. */}
                <Word frame={frame} start={said("hook", "Y") - 2}>¿Y ya</Word>{" "}
                <Word frame={frame} start={said("hook", "tienes") - 2}>tienes</Word>
              </div>
              <div style={{ ...TYPE.display(168, C.tomato600), lineHeight: 1.1, margin: "6px 0" }}>
                <Word frame={frame} start={said("hook", "disfraz") - 2} pulse={kick(t, [word("hook", "disfraz")])}>
                  disfraz
                </Word>
              </div>
              <div style={{ ...TYPE.display(104, C.wine900), lineHeight: 1.1 }}>
                <Word frame={frame} start={said("hook", "pa") - 2}>pa'l</Word>{" "}
                <Word frame={frame} start={said("hook", "sábado?") - 2}>sábado?</Word>
              </div>
            </div>
          </AbsoluteFill>
        ) : null}
        {frame < bt(TARDE) + 8 ? (
          <AbsoluteFill style={cam(1)}>
            <Pumpkin
              size={440}
              angle={spinAngle(t, pumpkinAt / FPS, 0.6)}
              style={{
                position: "absolute",
                left: 540 - 220,
                top: 960,
                opacity: (frame < pumpkinAt ? 0 : 1) * (1 - pumpkinOut),
                translate: `0px ${700 * pumpkinOut}px`,
                scale: `${0.3 + 0.7 * sp(frame, pumpkinAt, SPRING.pop)}`,
                rotate: `${-8 * (1 - sp(frame, pumpkinAt, SPRING.pop))}deg`,
              }}
            />
          </AbsoluteFill>
        ) : null}
        {/* The page head, from the afternoon to the end card. */}
        {frame >= bt(TARDE) - 4 && frame < END + 8 ? (
          <AbsoluteFill style={{ ...cam(0.6), opacity: 1 - leave(frame, END - 2, 8) }}>
            <Head frame={frame} start={bt(TARDE) - 2} night={night} />
          </AbsoluteFill>
        ) : null}
        {([0, 1, 2] as const).map((stage) =>
          frame >= bt(STAGE_IN[stage]) - 8 && frame < bt(STAGE_OUT[stage]) + 12 ? (
            <Stage key={stage} frame={frame} abs={abs} stage={stage} />
          ) : null,
        )}
        {/* Night arrives: the bats cross the head once. */}
        <AbsoluteFill style={cam(0.8)}>
          <Bats frame={frame} t={t} start={bt(NOCHE) - 2} />
        </AbsoluteFill>
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
              glow={interpolate(frame, [END + 10, END + 24], [0, 1], clamp)}
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
