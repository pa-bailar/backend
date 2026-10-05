// "Este finde": the coming weekend's events as a 12 s Story, built only from data (tools/events.py), no voice: the
// owner adds Instagram's music and link stickers. A worked example of a format-free video from the kit: the page
// head (stripes + period title), real flyers and facts rising on the beat, the record and the call to action.
// Re-run tools/events.py for next weekend and render again: nothing here names an event.
import React from "react";
import { AbsoluteFill, Composition, Folder } from "remotion";
import {
  AppIcon,
  assets,
  C,
  camera,
  dateLabel,
  daysOf,
  FONT,
  FPS,
  Flyer,
  Grain,
  grid,
  HEIGHT,
  jit,
  kick,
  leave,
  Letters,
  PeriodTitle,
  priceLabel,
  Record,
  rise,
  sec,
  sp,
  spinAngle,
  SPRING,
  Stripes,
  timeLabel,
  TYPE,
  useScene,
  type EventsSnapshot,
  type VideoEvent,
  WIDTH,
} from "../../src/kit";
import snapshot from "./data/events.json";

const file = assets("este-finde");
const DURATION_S = 12;
const { BEAT, beats, downbeats } = grid(98);
const data = snapshot as EventsSnapshot;
const MAX = 4; // cards that fit above the safe zone's bottom; the subtitle gives the total
const events = data.events.slice(0, MAX);

const CARDS_AT = 2 * BEAT; // the first card, then one per beat
const OUT = sec(16 * BEAT); // cards leave on a downbeat (9.8 s)
const CARD_H = 222;
const CARDS_TOP = 600;

const capital = (s: string) => s[0].toUpperCase() + s.slice(1);

/** The weekend day the event is on (a run of days or a series can start before it). */
const dayIn = (e: VideoEvent) => daysOf(e).find((d) => d >= data.from && d <= data.to) ?? e.date;

const Card: React.FC<{ e: VideoEvent; i: number; frame: number }> = ({ e, i, frame }) => {
  const start = sec(CARDS_AT + i * BEAT) + jit(`card${i}`, 1);
  const out = leave(frame, OUT + i * 2, 8);
  const ratio = e.ratio ?? 0.8;
  const w = Math.min(176, (CARD_H - 24) * ratio);
  const facts = [timeLabel(e.start_time), priceLabel(e.prices)].filter(Boolean).join(" · ");
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        top: CARDS_TOP + i * (CARD_H + 18),
        height: CARD_H,
        display: "flex",
        gap: 32,
        alignItems: "center",
        ...rise(frame, start, { distance: 90, config: SPRING.weight }),
        ...(out > 0 ? { opacity: 1 - out, translate: `${-140 * out}px 0px` } : {}),
      }}
    >
      <div style={{ position: "relative", width: 176, height: CARD_H - 24, flex: "none" }}>
        {e.flyer ? (
          <Flyer
            src={file(e.flyer)}
            width={w}
            ratio={ratio}
            style={{ left: (176 - w) / 2, top: (CARD_H - 24 - w / ratio) / 2, rotate: `${(i % 2 ? 1 : -1) * 2.5}deg` }}
          />
        ) : null}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={TYPE.sans(34, C.tomato600)}>{capital(dateLabel(dayIn(e)))}</div>
        <div
          style={{
            ...TYPE.sans(44, C.wine900),
            lineHeight: 1.1,
            margin: "6px 0 8px",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {e.title}
        </div>
        <div style={{ ...TYPE.serif(34), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {[facts, e.area ?? e.venue, `@${e.account}`].filter(Boolean).join(" · ")}
        </div>
      </div>
    </div>
  );
};

/** `blur` is the kit's render convention (tools/render.py turns it off for drafts); nothing here moves fast enough. */
export const EsteFinde: React.FC<{ blur?: boolean }> = () => {
  const { frame, t } = useScene();
  const cam = camera(t, 0, DURATION_S, { zoom: 0.03, driftX: 8, driftY: -10 });
  const pulse = kick(t, downbeats(0.5, DURATION_S));
  const endAt = OUT + 6;
  const icon = sp(frame, endAt, SPRING.pop);
  const rec = sp(frame, endAt + 2, SPRING.weight);
  const range = `${dateLabel(data.from, false).split(" ")[0]}–${dateLabel(data.to, false)}`;
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill style={cam(0.6)}>
        <Stripes frame={frame} start={2} top={250} />
        <PeriodTitle frame={frame} start={8} exitAt={OUT} size={124} top={300} pulse={kick(t, [2 * BEAT * 2])}>
          Este finde
        </PeriodTitle>
        <div
          style={{
            position: "absolute",
            left: 80,
            top: 515,
            ...TYPE.serif(48),
            ...rise(frame, 14, { distance: 40, exitAt: OUT }),
          }}
        >
          {range} · {data.events.length} {data.events.length === 1 ? "evento" : "eventos"} en Bogotá
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={cam(1)}>
        {events.map((e, i) => (
          <Card key={e.id} e={e} i={i} frame={frame} />
        ))}
      </AbsoluteFill>
      {frame >= endAt ? (
        <AbsoluteFill style={cam(1)}>
          <AppIcon
            size={420}
            style={{ left: 330, top: 520, scale: `${(0.4 + 0.6 * icon) * (1 + 0.03 * pulse)}` }}
          />
          <Record
            size={360}
            angle={spinAngle(t, endAt / FPS, 0.6)}
            style={{ position: "absolute", left: 360, top: 550, scale: `${0.3 + 0.7 * rec}` }}
          />
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 1010,
              textAlign: "center",
              ...TYPE.display(150, C.tomato600),
              lineHeight: 1,
              whiteSpace: "pre",
            }}
          >
            <Letters frame={frame} start={endAt + 6} text="Pa' Bailar" step={1.2} seed="finde" />
          </div>
          <div style={{ position: "absolute", left: 80, right: 80, top: 1200, textAlign: "center", ...TYPE.sans(60), ...rise(frame, endAt + 22) }}>
            Link aquí abajo{" "}
            <span
              style={{
                display: "inline-block",
                fontFamily: FONT.emoji,
                translate: `0px ${16 * kick(t, beats(endAt / FPS + 1, DURATION_S))}px`,
              }}
            >
              👇
            </span>
          </div>
        </AbsoluteFill>
      ) : null}
      <Grain />
    </AbsoluteFill>
  );
};

export const EsteFindeVideo: React.FC = () => (
  <Folder name="este-finde">
    <Composition
      id="este-finde"
      component={EsteFinde}
      durationInFrames={DURATION_S * FPS}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ blur: false }}
    />
  </Folder>
);
