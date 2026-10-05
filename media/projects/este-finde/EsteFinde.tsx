// "Este finde": the coming weekend's events as a 12 s Story, built only from data (tools/events.py), no voice: the
// owner adds Instagram's music and the link sticker (at the top, in the band above y 250 that nothing enters). A
// worked example of a format-free video from the kit: the page head (stripes + period title), real flyers and facts
// rising on the beat, then the end card as in the teaser: "Link aquí arriba" with the drawn arrow under the sticker,
// the app icon, the record and the wordmark. Re-run tools/events.py for next weekend and render again: nothing here
// names an event.
import React from "react";
import { AbsoluteFill, Composition, Folder } from "remotion";
import {
  AppIcon,
  assets,
  C,
  camera,
  dateLabel,
  Arrow,
  FadeIn,
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
  spanLabel,
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
import settings from "./video.json";

const file = assets("este-finde");
const DURATION_S = settings.duration;
const { BEAT, beats, downbeats } = grid(98);
const data = snapshot as EventsSnapshot;
const MAX = 4; // cards that fit above the safe zone's bottom; the subtitle gives the total
const events = data.events.slice(0, MAX);

const CARDS_AT = 2 * BEAT; // the first card, then one per beat
const OUT = sec(16 * BEAT); // cards leave on a downbeat (9.8 s)
const CARD_H = 222;
const CARDS_TOP = 610;
// The page head sits low enough that the camera's push-in never lifts it into the sticker's band (y < 250).
const HEAD_TOP = 276;
// The end card (as the teaser's): the call to action right under the band, the icon and the record below it.
const SPOT = { x: 540, y: 820 };

const capital = (s: string) => s[0].toUpperCase() + s.slice(1);

const Card: React.FC<{ e: VideoEvent; i: number; frame: number }> = ({ e, i, frame }) => {
  const start = sec(CARDS_AT + i * BEAT) + jit(`card${i}`, 1);
  const out = leave(frame, OUT + i * 2, 8);
  const ratio = e.ratio ?? 0.8;
  const w = Math.min(176, (CARD_H - 24) * ratio);
  const facts = [timeLabel(e.day_start), priceLabel(e.prices)].filter(Boolean).join(" · ");
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
        <div style={TYPE.sans(34, C.tomato600)}>{capital(dateLabel(e.day))}</div>
        <div
          style={{
            ...TYPE.sans(40, C.wine900),
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
        {/* Times and prices in the sans: Bodoni's italic 4 loses its hairline at video size and reads as a 1. */}
        <div style={{ ...TYPE.sans(30, C.wine500), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {facts}
        </div>
        <div style={{ ...TYPE.sans(28, C.cocoa500), marginTop: 2 }}>@{e.account}</div>
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
  const range = spanLabel(data.from, data.to);
  const link = endAt + 16;
  const bob = kick(t, beats(link / FPS + 0.4, DURATION_S));
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill style={cam(0.6)}>
        {frame < endAt ? (
          <div style={{ opacity: 1 - leave(frame, OUT, 6) }}>
            <Stripes frame={frame} start={2} top={HEAD_TOP} />
          </div>
        ) : null}
        <PeriodTitle frame={frame} start={8} exitAt={OUT} size={124} top={HEAD_TOP + 46} pulse={kick(t, [2 * BEAT * 2])}>
          Este finde
        </PeriodTitle>
        <div
          style={{
            position: "absolute",
            left: 80,
            top: HEAD_TOP + 261,
            // The sans, not the Bodoni: the range and the count are digits, and the italic's digits don't read.
            ...TYPE.sans(44, C.wine500),
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
        <>
          <AbsoluteFill style={cam(0.6)}>
            {/* The call to action, right under the sticker's band: the arrow points up at the link. */}
            <div
              style={{
                position: "absolute",
                left: 80,
                right: 80,
                top: 276,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                ...rise(frame, link, { distance: 40 }),
              }}
            >
              <Arrow size={132} weight={3.2} style={{ translate: `0px ${-14 * bob}px` }} />
              <div style={{ ...TYPE.sans(68), textAlign: "center" }}>Link aquí arriba</div>
            </div>
          </AbsoluteFill>
          <Stripes frame={frame} start={endAt} top={500} />
          <AbsoluteFill style={cam(1)}>
            <AppIcon
              size={420}
              style={{ left: SPOT.x - 210, top: SPOT.y - 210, scale: `${(0.4 + 0.6 * icon) * (1 + 0.03 * pulse)}` }}
            />
            <Record
              size={360}
              angle={spinAngle(t, endAt / FPS, 0.6)}
              style={{ position: "absolute", left: SPOT.x - 180, top: SPOT.y - 180, scale: `${0.3 + 0.7 * rec}` }}
            />
          </AbsoluteFill>
          <AbsoluteFill style={cam(0.6)}>
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: SPOT.y + 300,
                textAlign: "center",
                ...TYPE.display(150, C.tomato600),
                lineHeight: 1,
                whiteSpace: "pre",
              }}
            >
              <Letters frame={frame} start={endAt + 6} text="Pa' Bailar" step={1.2} seed="finde" />
            </div>
            <div
              style={{
                position: "absolute",
                left: 80,
                right: 80,
                top: SPOT.y + 470,
                textAlign: "center",
                ...TYPE.serif(66),
                ...rise(frame, endAt + 22, { distance: 50 }),
              }}
            >
              Nos vemos bailando.
            </div>
          </AbsoluteFill>
        </>
      ) : null}
      {/* A Story fades in, never out (the owner, 5 Oct 2026). */}
      <FadeIn />
      <Grain />
    </AbsoluteFill>
  );
};

export const EsteFindeVideo: React.FC = () => (
  <Folder name="este-finde">
    <Composition
      id="este-finde-story"
      component={EsteFinde}
      durationInFrames={DURATION_S * FPS}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ blur: false }}
    />
  </Folder>
);
