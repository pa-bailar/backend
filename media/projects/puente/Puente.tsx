// Puente festivo (9–12 Oct 2026): the long weekend as a bridge. The site's three stripes draw an arch over
// VIE · SÁB · DOM · LUN (festivo); it rises to become the header while a small record crosses it day by day, and under
// it the flyers of the six events the owner chose land on a pile, with their facts below; between days the stage
// whips sideways, as if crossing to the next pier. Then the rest of the weekend's flyers riffle in ("+25 planes más")
// and the bridge comes down into the end card: "Todo en / Pa' Bailar". The voice (Despina, the owner's pick, 8 Oct
// 2026) leads: the hook's words as she says them, each day's stage at its line, each flyer as its name is said; every
// line starts on a beat of the owner's salsa (video.json "music", from 0:09.85, where the full band comes in, 90.51
// bpm), so cuts land on the grid and the bed ducks under her.
import React from "react";
import { AbsoluteFill, Composition, Folder, interpolate, OffthreadVideo, Sequence } from "remotion";
import {
  assets,
  C,
  camera,
  clamp,
  type Cta,
  dateLabel,
  EndCard,
  FPS,
  Flyer,
  gridOf,
  inRanges,
  jit,
  makeTiming,
  kick,
  leave,
  mix,
  Record,
  rise,
  sec,
  Shutter,
  sp,
  spinAngle,
  SPRING,
  STRIPES,
  timeLabel,
  toss,
  TYPE,
  useScene,
  type EventsSnapshot,
  type VideoEvent,
  vertical,
  VideoShell,
  whip,
  whipBlur,
  wobble,
  Word,
} from "../../src/kit";
import snapshot from "./data/events.json";
import timingJson from "./data/timing.json";
import settings from "./video.json";

/** Files in the media home's public/puente/ (flyers from tools/events.py, the two clips, the mixed soundtrack). */
export const file = assets("puente");
const DURATION_S = settings.duration;
const { BEAT, beats, downbeats } = gridOf(settings);
/** The frame of beat `n` (the song's grid from its first hit). */
const bt = (n: number) => sec(n * BEAT);
const data = snapshot as EventsSnapshot;
const { line, word } = makeTiming(timingJson);
/** The frame a word is said on. */
const said = (id: string, w: string) => sec(word(id, w));

// ---------- the events: the owner's six, in the order shown ----------

/** The beat at or before `s` seconds. */
const beatAt = (s: number) => Math.floor(s / BEAT + 1e-6);
/**
 * The sections, in beats, each on the beat at or just before its voice line (one take: her pauses fall where she made
 * them, so the grid follows her): a day's stage whips in just before she names the day. Then the rest of the
 * weekend, then the end card.
 */
const STAGE_IN = [beatAt(line("vie").start), beatAt(line("sab").start), beatAt(line("dom").start)];
const RIFFLE = beatAt(line("mas").start);
const STAGE_OUT = [STAGE_IN[1], STAGE_IN[2], RIFFLE];
/** Each day's line and the word that names the day. */
const DAY_WORDS: [string, string][] = [
  ["vie", "viernes"],
  ["sab", "sábado"],
  ["dom", "domingo"],
];
const END_BEAT = beatAt(line("fin").start);

/** Each event lands as its name is said (`land`: the frame of that word in its day's line). */
type Shown = { id: string; day: 0 | 1 | 2; land: number; clip?: string; side: -1 | 1 };
const SHOWN: Shown[] = [
  { id: "parchese-la-salsa-salsa-pa-entucar-9-oct", day: 0, land: said("vie", "Párchese"), side: 1 },
  {
    id: "tardeo-latino-edicion-angeles-10-oct",
    day: 1,
    land: said("sab", "Tardeo"),
    clip: "clips/18118799581975237-0.mp4",
    side: -1,
  },
  { id: "primer-aniversario-ludance-fiesta-crossover-10-oct", day: 1, land: said("sab", "aniversario"), side: 1 },
  { id: "social-pal-parche-10-oct", day: 1, land: said("sab", "Social"), side: -1 },
  { id: "tardeo-viva-salsa-social-11-oct", day: 2, land: said("dom", "Viva"), side: 1 },
  { id: "el-golazo-de-bulevar-11-oct", day: 2, land: said("dom", "Golazo"), clip: "clips/18130057825689666-0.mp4", side: -1 },
];
const byId = new Map(data.events.map((e) => [e.id, e]));
const shown = SHOWN.map((s) => {
  const e = byId.get(s.id);
  if (!e) throw new Error(`${s.id} isn't in data/events.json: re-run tools/events.py puente --from 2026-10-09 --to 2026-10-11`);
  return { ...s, e };
});
/** When an event's facts leave: just before the next one lands, or its day's stage whips out. */
const leaving = (i: number) => {
  const next = shown[i + 1];
  return next && next.day === shown[i].day ? next.land - 8 : bt(STAGE_OUT[shown[i].day]) - 6;
};
const OTHERS = data.events.filter((e) => !SHOWN.some((s) => s.id === e.id) && e.flyer);
const MORE = OTHERS.length; // "+25 planes más": the real count of this snapshot

const capital = (s: string) => s[0].toUpperCase() + s.slice(1);
/** The title as it reads on a flyer: the part before " - " ("Tardeo Latino - Edición: Ángeles" → "Tardeo Latino"). */
const shortTitle = (t: string) => t.split(" - ")[0].trim();

// ---------- the bridge ----------

/** The bridge's own drawing box (px at scale 1): the arch over the deck, the days under it. */
const BR = { w: 920, deck: 250, cx: 460, rx: 400, ry: 205, band: 22, gap: 6 };
const DAYS = [
  { x: 145, name: "VIE", n: "9" },
  { x: 360, name: "SÁB", n: "10" },
  { x: 575, name: "DOM", n: "11" },
  { x: 790, name: "LUN", n: "12" },
];
/** The day under way: Friday until Saturday's whip, then Saturday, Sunday, and Monday from the end card. */
const dayAt = (frame: number) =>
  frame < bt(STAGE_IN[1]) - 4 ? 0 : frame < bt(STAGE_IN[2]) - 4 ? 1 : frame < bt(END_BEAT) ? 2 : 3;

/** Where the outer arch passes over x (the record rides on it). */
const archY = (x: number) => BR.deck - BR.ry * Math.sqrt(Math.max(0, 1 - ((x - BR.cx) / BR.rx) ** 2));

const Bridge: React.FC<{ frame: number; start: number; at: number; t: number }> = ({ frame, start, at, t }) => {
  // The three stripes draw in from the left, one after the other (irregular, as the site's stripes wipe in).
  const draw = (k: number) => sp(frame, start + k * 3 + jit(`arch${k}`, 1), SPRING.snap);
  const deck = sp(frame, start + 4, SPRING.snap);
  const x = at;
  const recY = archY(x);
  // With the word "festivo…" (the owner, v1: at 1.9 s it came too late, gone up with the bridge right away).
  const festivoAt = said("hook", "festivo") - 1;
  const festivo = sp(frame, festivoAt, SPRING.pop);
  return (
    <div style={{ position: "absolute", width: BR.w, height: 420 }}>
      <svg width={BR.w} height={BR.deck + 12} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {STRIPES.map((color, k) => {
          const inset = k * (BR.band + BR.gap);
          const rx = BR.rx - inset;
          const ry = BR.ry - inset;
          return (
            <path
              key={k}
              d={`M ${BR.cx - rx} ${BR.deck} A ${rx} ${ry} 0 0 1 ${BR.cx + rx} ${BR.deck}`}
              fill="none"
              stroke={color}
              strokeWidth={BR.band}
              pathLength={1}
              strokeDasharray="1 1"
              strokeDashoffset={1 - draw(k)}
            />
          );
        })}
        <rect x={0} y={BR.deck - 2} width={BR.w * deck} height={12} rx={3} fill={C.wine900} />
      </svg>
      {DAYS.map((d, i) => {
        // The day under way turns tomato once the bridge is the header (the record alone is small up there).
        const on = frame >= bt(STAGE_IN[0]) && i === dayAt(frame) ? 1 : 0;
        return (
          <div
            key={d.name}
            style={{
              position: "absolute",
              left: d.x - 70,
              width: 140,
              top: BR.deck + 22,
              textAlign: "center",
              ...rise(frame, start + 6 + i * 3 + jit(`day${i}`, 1), { distance: 30 }),
            }}
          >
            <div style={{ ...TYPE.sans(46, on ? C.tomato600 : C.wine900), letterSpacing: 2, lineHeight: 1 }}>{d.name}</div>
            <div style={{ ...TYPE.sans(38, on ? C.tomato600 : C.cocoa500), lineHeight: 1.2 }}>{d.n}</div>
          </div>
        );
      })}
      {/* Monday's holiday: the round tomato tag, the reason it's a "puente". */}
      <div
        style={{
          position: "absolute",
          left: DAYS[3].x - 86,
          top: BR.deck + 128,
          width: 172,
          height: 54,
          borderRadius: 27,
          background: C.tomato600,
          border: `3px solid ${C.wine900}`,
          boxShadow: `4px 4px 0 ${C.wine900}`,
          display: "grid",
          placeItems: "center",
          ...TYPE.sans(32, C.cream50),
          opacity: frame < festivoAt ? 0 : 1,
          scale: `${festivo}`,
          rotate: `${-6 * festivo}deg`,
        }}
      >
        festivo
      </div>
      {/* The record crossing the bridge: it rides the outer arch to the day under way. */}
      <Record
        size={84}
        angle={spinAngle(t, start / FPS, 0.6)}
        style={{
          position: "absolute",
          left: x - 42,
          top: recY - 84 - BR.band / 2 + 4,
          opacity: interpolate(frame, [bt(STAGE_IN[0]), bt(STAGE_IN[0]) + 6], [0, 1], clamp),
          scale: `${sp(frame, bt(STAGE_IN[0]), SPRING.pop)}`,
        }}
      />
    </div>
  );
};

/** The bridge's place on screen: big under the hook, then the header, then the end card's centerpiece. */
function bridgeAt(frame: number) {
  const up = sp(frame, bt(STAGE_IN[0]) - 2, SPRING.sheet);
  const down = sp(frame, bt(END_BEAT), SPRING.sheet);
  const hook = { x: 80, y: 980, s: 1 };
  const head = { x: (1080 - BR.w * 0.6) / 2, y: 296, s: 0.6 };
  const end = { x: (1080 - BR.w * 0.74) / 2, y: 580, s: 0.74 };
  const a = { x: mix(hook.x, head.x, up), y: mix(hook.y, head.y, up), s: mix(hook.s, head.s, up) };
  return { x: mix(a.x, end.x, down), y: mix(a.y, end.y, down), s: mix(a.s, end.s, down) };
}

/** Where the record is on the arch: over each day as its stage comes in, over Monday at the end. */
function recordX(frame: number) {
  const stops: [number, number][] = [
    [bt(STAGE_IN[0]), DAYS[0].x],
    [bt(STAGE_IN[1]) - 4, DAYS[1].x],
    [bt(STAGE_IN[2]) - 4, DAYS[2].x],
    [bt(END_BEAT), DAYS[3].x],
  ];
  let x = DAYS[0].x;
  for (let i = 1; i < stops.length; i++) x = mix(x, stops[i][1], sp(frame, stops[i][0], SPRING.sheet));
  return x;
}

// ---------- a flyer (or a clip) on the pile, and its facts ----------

const BOX = { w: 600, h: 736, top: 592 }; // where a flyer may stand: centered, under the header's "festivo", above the facts
const FACTS_TOP = 1352;

const ClipCard: React.FC<{ src: string; width: number; ratio: number; lift: number; style: React.CSSProperties; from: number }> = ({
  src,
  width,
  ratio,
  lift,
  style,
  from,
}) => (
  <div
    style={{
      position: "absolute",
      width,
      height: width / ratio,
      borderRadius: 8,
      overflow: "hidden",
      border: `4.5px solid ${C.wine900}`,
      boxShadow: `0 ${10 + 50 * lift}px ${18 + 70 * lift}px rgba(42,15,20,${0.3 - 0.12 * lift})`,
      background: C.sunken,
      ...style,
    }}
  >
    <Sequence from={from} layout="none">
      <OffthreadVideo src={src} muted style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
    </Sequence>
  </div>
);

const Pile: React.FC<{ frame: number; items: typeof shown }> = ({ frame, items }) => {
  const landings = items.map((s) => s.land - 8); // tossed 8 frames before the name, so it lands on it
  return (
    <>
      {items.map((s, i) => {
        const go = landings[i];
        const ratio = s.clip ? 480 / 854 : (s.e.ratio ?? 0.8);
        const width = Math.min(BOX.w, BOX.h * ratio) * (s.clip ? 0.94 : 1);
        const height = width / ratio;
        const rot = (i % 2 ? 1 : -1) * (2 + (i % 3)) + wobble(frame, landings.slice(i + 1).map((l) => l + 9), 1.4);
        const t = toss(frame, go, { side: s.side, rot, fromX: 820, fromY: 380, arc: 110 });
        const style: React.CSSProperties = { left: (1080 - width) / 2, top: BOX.top + (BOX.h - height) / 2, ...t.style };
        return s.clip ? (
          <ClipCard key={s.id} src={file(s.clip)} width={width} ratio={ratio} lift={t.lift} style={style} from={go} />
        ) : (
          <Flyer key={s.id} src={file(s.e.flyer!)} width={width} ratio={ratio} lift={t.lift} style={style} />
        );
      })}
    </>
  );
};

const Facts: React.FC<{ frame: number; e: VideoEvent; at: number; exitAt: number }> = ({ frame, e, at, exitAt }) => {
  const when = [capital(dateLabel(e.day)), timeLabel(e.day_start)].filter(Boolean).join(" · ");
  const where = [e.venue, `@${e.account}`].filter(Boolean).join(" · ");
  return (
    <div style={{ position: "absolute", left: 90, right: 130, top: FACTS_TOP }}>
      {/* Dates and times in the sans: Bodoni's italic 4 reads as a 1. */}
      <div style={{ ...TYPE.sans(40, C.tomato600), ...rise(frame, at, { distance: 40, exitAt }) }}>{when}</div>
      <div
        style={{
          ...TYPE.display(66, C.wine900),
          lineHeight: 1.05,
          margin: "8px 0 10px",
          ...rise(frame, at + 2 + jit(`t${e.id}`, 1), { distance: 50, exitAt }),
        }}
      >
        {shortTitle(e.title)}
      </div>
      <div
        style={{
          ...TYPE.sans(32, C.cocoa500),
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

/** One day's stage: its pile and the facts of the event on top; it whips in from the right and out to the left. */
const Stage: React.FC<{ frame: number; abs: number; day: number }> = ({ frame, abs, day }) => {
  const items = shown.filter((s) => s.day === day);
  const inCut = day > 0 ? bt(STAGE_IN[day]) : null;
  const outCut = day < 2 ? bt(STAGE_OUT[day]) : null;
  let x = 0;
  if (inCut !== null) {
    const w = whip(abs, inCut);
    x += 1080 * (1 - w.p);
  }
  if (outCut !== null) {
    const w = whip(abs, outCut);
    x += -1080 * w.p - w.dip;
  }
  // Sunday's pile drops out of the way for the rest of the weekend's flyers.
  const drop = day === 2 ? leave(frame, bt(RIFFLE) - 2, 8) : 0;
  // The day's name while she says it ("El sábado,…"), until its first flyer comes in: the stage was empty then (v2).
  const [lineId, dayWord] = DAY_WORDS[day];
  // As she names the day, or as its stage comes in if that's sooner (v3: Friday's stood empty 0.8 s before "viernes").
  const named = Math.min(said(lineId, dayWord) - 2, bt(STAGE_IN[day]) + 4);
  const firstToss = items[0].land - 8;
  return (
    <AbsoluteFill style={{ translate: `${x}px ${900 * drop}px`, opacity: 1 - drop }}>
      <div
        style={{
          position: "absolute",
          left: 60,
          right: 60,
          top: 820,
          textAlign: "center",
          ...TYPE.display(150, C.tomato600),
          ...rise(frame, named, { distance: 70, exitAt: firstToss }),
        }}
      >
        {capital(dayWord)}
      </div>
      <Pile frame={frame} items={items} />
      {items.map((s) => (
        <Facts key={s.id} frame={frame} e={s.e} at={s.land} exitAt={leaving(shown.indexOf(s))} />
      ))}
    </AbsoluteFill>
  );
};

// ---------- the rest of the weekend: a riffle of flyers and the count ----------

const Riffle: React.FC<{ frame: number }> = ({ frame }) => {
  const start = bt(RIFFLE) - 4;
  const out = leave(frame, bt(END_BEAT) - 3, 7);
  const many = OTHERS.slice(0, 12);
  return (
    <AbsoluteFill style={{ opacity: 1 - out, translate: `0px ${120 * out}px` }}>
      {many.map((e, i) => {
        const go = start + i * 3 + jit(`r${i}`, 1);
        const ratio = e.ratio ?? 0.8;
        const width = 380;
        const t = toss(frame, go, {
          side: i % 2 ? 1 : -1,
          rot: ((i * 37) % 21) - 10,
          fromX: 760,
          fromY: 460,
          arc: 80,
          spin: 40,
        });
        return (
          <Flyer
            key={e.id}
            src={file(e.flyer!)}
            width={width}
            ratio={ratio}
            lift={t.lift}
            style={{
              // Scattered around the stage's middle, inside the frame (x 120–580 for a 380 px flyer).
              left: (1080 - width) / 2 + ((i * 113) % 300) - 150,
              top: 640 + ((i * 71) % 200) - 60,
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
          background: C.card,
          border: `4px solid ${C.wine900}`,
          borderRadius: 14,
          boxShadow: `8px 8px 0 ${C.wine900}`,
          ...rise(frame, said("mas", "muchos") - 2, { distance: 60, config: SPRING.pop }),
        }}
      >
        {/* The count is digits: the sans. */}
        <div style={{ ...TYPE.sans(84, C.tomato600), lineHeight: 1 }}>+{MORE} planes más</div>
        <div style={{ ...TYPE.serif(54), marginTop: 6 }}>este puente, en Pa' Bailar</div>
      </div>
    </AbsoluteFill>
  );
};

// ---------- the video ----------

/** Fast moves that get motion blur: the two whips, the riffle's tosses and the end's drop. */
const FAST: [number, number][] = [
  whipBlur(bt(STAGE_IN[1])),
  whipBlur(bt(STAGE_IN[2])),
  [bt(RIFFLE) - 4, bt(RIFFLE) + 40],
  [bt(END_BEAT) - 3, bt(END_BEAT) + 6],
];

/** `blur` is the kit's render convention (render.py --draft turns it off). */
export const Puente: React.FC<{ cta: Cta; blur?: boolean }> = ({ cta, blur = true }) => {
  const { frame, abs, t } = useScene();
  const cam = camera(t, 0, DURATION_S, { zoom: 0.03, driftX: 8, driftY: -10 });
  const END = bt(END_BEAT);
  const br = bridgeAt(frame);
  const hookOut = sec(line("hook").end) - 2; // when she's said it, before the bridge goes up
  const lunPulse = kick(t, downbeats(END / FPS + 0.1, DURATION_S));
  return (
    <VideoShell fadeIn={6} audio={file("audio/with-music.wav")} story={cta === "story"}>
      <Shutter samples={blur && inRanges(frame, FAST) ? 8 : 1}>
        {/* The hook, at 0 s: the question, no logo (Instagram practices, media/README.md). */}
        {frame < bt(STAGE_IN[0]) + 4 ? (
          <AbsoluteFill style={cam(0.6)}>
            <div style={{ position: "absolute", left: 60, right: 60, top: 330, textAlign: "center", opacity: 1 - leave(frame, hookOut, 6) }}>
              <div style={{ ...TYPE.display(132, C.tomato600), lineHeight: 1.04 }}>
                {/* Each word 2 frames before she says it. */}
                <Word frame={frame} start={said("hook", "Puente") - 2}>Puente</Word>{" "}
                <Word frame={frame} start={said("hook", "festivo") - 2}>festivo…</Word>
              </div>
              <div style={{ ...TYPE.display(104, C.wine900), lineHeight: 1.08, marginTop: 34 }}>
                <Word frame={frame} start={said("hook", "y") - 2}>¿y tú</Word>{" "}
                <Word frame={frame} start={said("hook", "en") - 2}>en la</Word>{" "}
                <Word frame={frame} start={said("hook", "casa") - 2} pulse={kick(t, [word("hook", "casa")])}>
                  casa?
                </Word>
              </div>
            </div>
          </AbsoluteFill>
        ) : null}
        {/* The bridge, moving between its three places. Under the stages (the owner, v1: its "festivo" tag sat on
            top of the first flyer as it landed): a flyer passes over it, like a thing tossed onto the table. */}
        <AbsoluteFill style={cam(0.8)}>
          <div
            style={{
              position: "absolute",
              left: br.x,
              top: br.y,
              width: BR.w,
              transformOrigin: "0 0",
              scale: `${br.s * (1 + 0.025 * lunPulse)}`,
            }}
          >
            <Bridge frame={frame} start={2} at={recordX(frame)} t={t} />
          </div>
        </AbsoluteFill>
        {/* The days' stages, over the bridge. */}
        {[0, 1, 2].map((day) =>
          frame >= bt(STAGE_IN[day]) - 8 && frame < bt(STAGE_OUT[day]) + 12 ? (
            <Stage key={day} frame={frame} abs={abs} day={day} />
          ) : null,
        )}
        {frame >= bt(RIFFLE) - 6 && frame < END + 6 ? <Riffle frame={frame} /> : null}
        {frame >= END ? (
          <EndCard
            cta={cta}
            frame={frame}
            cam={cam}
            link={said("fin", "Te") - 4}
            bob={kick(t, beats(word("fin", "link") + 0.2, DURATION_S))}
            stripesAt={END + 2}
            name={{ at: said("fin", "en") - 2, size: 150, step: 1.2, seed: "puente" }}
            spot={{ x: 540, y: 760 }}
            signoff={{ text: "Nos vemos bailando.", at: said("fin", "link") + 10 }}
          >
            <div
              style={{
                position: "absolute",
                left: 80,
                right: 80,
                top: 942,
                textAlign: "center",
                ...TYPE.serif(76),
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

export const PuenteVideo: React.FC = () => (
  <Folder name="puente">
    <Composition id="puente-story" component={Puente} {...vertical(settings)} defaultProps={{ cta: "story" as const, blur: true }} />
    <Composition id="puente-reel" component={Puente} {...vertical(settings)} defaultProps={{ cta: "reel" as const, blur: true }} />
  </Folder>
);
