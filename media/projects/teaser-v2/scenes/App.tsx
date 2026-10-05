// Scene 3 (6.12–14.69): "Miras qué hay hoy, este finde, la otra semana… a qué hora, dónde, cuánto vale y cómo
// llegar." One continuous phone shot of the LIVE site (light theme), driven by a thumb (v2.3: the site of 4 Oct 2026):
//   1. The thumb taps the "Salsa" and "Bachata" chips in the bar; each turns dark and the list filters to them.
//   2. It flicks the list to each period as the voice names it: Hoy, Este fin de semana, Próxima semana. Each flick
//      glides and settles a hair past the stop; the bar stays pinned at the top with its "N eventos · Salsa, Bachata".
//   3. A tap on the event's "Detalles" raises the site's details drawer to half height over the list (spring); a
//      frame lands on the time, then the thumb pulls the drawer up to full height and the frame visits Lugar, the
//      price and "Cómo llegar" as the voice asks.
// Every position comes from data/app.json (capture.mjs), so a re-capture flows through.
import React from "react";
import { AbsoluteFill, Img, interpolate } from "remotion";
import {
  C,
  camera,
  clamp,
  Highlight,
  kick,
  mid,
  pad,
  PeriodTitle,
  Phone,
  PHONE,
  type Rect,
  sec,
  smear,
  sp,
  SPRING,
  Thumb,
  type ThumbKey,
  useScene,
  Word,
} from "../../../src/kit";
import app from "../data/app.json";
import { BAR, file, SCENES, word } from "../theme";

const f = (s: number) => sec(s) - sec(SCENES.app);
const { css: CSS, sx, sy, height: SCREEN_H } = PHONE;
const VIEW_H = 640; // the capture's viewport height (CSS px)

// ---------- the beats of the shot ----------
const CHIPS = app.chips; // each chip tapped, in order, with where it was when tapped
const TAPS = CHIPS.map((_, i) => f(6.5 + i * 0.32)); // Salsa, Bachata…
const periodTop = (key: string) => {
  const p = app.periods.find((x) => x.key === key);
  if (!p) throw new Error(`no period ${key} in app.json`);
  return p.top - app.bar.h; // where the site puts a period: right under the pinned bar
};
const FLICKS = [
  { at: f(word("c1", "hoy") - 0.22), key: "hoy", title: "Hoy" },
  { at: f(word("c1", "este") - 0.2), key: "fin-de-semana", title: "Este finde" },
  { at: f(word("c1", "la") - 0.15), key: "proxima-semana", title: "La otra semana" },
].map((c) => ({ ...c, to: periodTop(c.key) }));
const TAP_EVENT = f(10.86); // "Detalles" on the card
const OPEN = TAP_EVENT + 3; // the drawer rises to half height
const EXPAND = f(11.58); // the thumb pulls it up to full height

const D = app.detail;
const HALF = D.half.panel.y; // the drawer's top at half height (CSS px in the viewport)
const FULL = D.full.panel.y; // …and at full height
type Space = "half" | "full"; // which capture a rect is in: detail-half.png or detail-full.png
const BOXES: { at: number; title: string; box: Rect | null; space: Space }[] = [
  // "a qué hora": the when line at the top of the drawer, right as it opens
  { at: f(word("c2", "hora") - 0.25), title: "¿A qué hora?", box: D.half.when && pad(D.half.when, 8, 6), space: "half" },
  { at: f(word("c2", "dónde") - 0.12), title: "¿Dónde?", box: D.full.lugar && pad(D.full.lugar, 8, 6), space: "full" },
  { at: f(word("c2", "cuánto") - 0.12), title: "¿Cuánto vale?", box: D.full.precio && pad(D.full.precio, 8, 6), space: "full" },
  {
    at: f(word("c2", "cómo") - 0.12),
    title: "¿Cómo llegar?",
    box: D.full.comoLlegar && pad(D.full.comoLlegar, 8, 5),
    space: "full",
  },
];

/** The drawer's top (CSS px) at a frame: rises from the bottom to half height, then is pulled up to full height. */
function drawerTop(frame: number): number {
  const rise = sp(frame, OPEN, SPRING.sheet);
  const pull = sp(frame, EXPAND, SPRING.sheet);
  return VIEW_H + (HALF - VIEW_H) * rise - (HALF - FULL) * pull;
}

/**
 * The list's scroll (CSS px) at a frame: each flick a spring from where the last one left it, then, as the drawer
 * rises, the site's own nudge that keeps the tapped card in view under the bar (to where detail-half.png was taken).
 */
function scrollAt(frame: number): number {
  let y = 0;
  let from = 0;
  for (const c of FLICKS) {
    y += (c.to - from) * sp(frame, c.at, SPRING.thumb);
    from = c.to;
  }
  return y + (D.scrollHalf - from) * sp(frame, OPEN, SPRING.sheet);
}

/** The thumb's path: tap each chip, then flick, flick, flick, tap "Detalles", and pull the drawer up by its grip. */
function thumbKeys(): ThumbKey[] {
  // A chip near the screen's edge is tapped on its visible part.
  const tapX = (r: Rect) => Math.min(mid(r).x, 360 - 24);
  const first = CHIPS[0].tap;
  const keys: ThumbKey[] = [{ f: TAPS[0] - 8, x: sx(tapX(first) + 30), y: sy(mid(first).y + 260) }];
  CHIPS.forEach((c, i) => keys.push({ f: TAPS[i], x: sx(tapX(c.tap)), y: sy(mid(c.tap).y), tap: true }));
  FLICKS.forEach((c) => {
    keys.push({ f: c.at - 4, x: sx(190), y: sy(560), down: true });
    keys.push({ f: c.at + 4, x: sx(205), y: sy(300) });
  });
  const tap = mid(D.tap);
  keys.push({ f: TAP_EVENT, x: sx(tap.x), y: sy(tap.y), tap: true });
  keys.push({ f: EXPAND - 3, x: sx(200), y: sy(mid(D.half.grip).y), down: true });
  keys.push({ f: EXPAND + 7, x: sx(205), y: sy(mid(D.full.grip).y) });
  return keys;
}
const KEYS = thumbKeys();

/** Part of a capture from `fromY` down (CSS px), drawn with its top at `top` (CSS px), cut to the screen. */
const Slice: React.FC<{ src: string; fromY: number; top: number; opacity?: number }> = ({ src, fromY, top, opacity = 1 }) => (
  <div style={{ position: "absolute", left: 0, top: top * CSS, width: PHONE.width, height: SCREEN_H - top * CSS, overflow: "hidden", opacity }}>
    <Img src={file(`app/${src}`)} style={{ position: "absolute", left: 0, top: -fromY * CSS, width: PHONE.width }} />
  </div>
);

const Screen: React.FC<{ frame: number }> = ({ frame }) => {
  const tapped = TAPS.filter((t) => frame >= t + 1).length;
  const top = drawerTop(frame);
  const opened = interpolate(frame, [OPEN, OPEN + 4], [0, 1], clamp);
  const pulled = interpolate(frame, [EXPAND + 1, EXPAND + 6], [0, 1], clamp);

  let base: React.ReactNode;
  if (tapped < CHIPS.length) {
    // The page as it opens, then each chip pressed in turn (the list under them filtering too).
    const shot = tapped === 0 ? "top.png" : CHIPS[tapped - 1].file;
    base = <Img src={file(`app/${shot}`)} style={{ position: "absolute", left: 0, top: 0, width: PHONE.width }} />;
  } else {
    // The filtered list, whole, scrolled by the flicks; motion blur done here (cheap and exact).
    const speed = Math.abs(scrollAt(frame + 0.5) - scrollAt(frame - 0.5)) * CSS;
    base = smear(frame, speed, (at, i, opacity) => (
      <Img
        key={i}
        src={file(`app/${app.list.file}`)}
        style={{ position: "absolute", left: 0, top: -scrollAt(at) * CSS, width: PHONE.width, height: app.list.cssHeight * CSS, opacity }}
      />
    ));
  }
  // The bar, pinned once the page is past its place (it no longer hides while scrolling: the site of 4 Oct).
  const pinned = tapped >= CHIPS.length && scrollAt(frame) > app.top.bar.y;

  // The frame on what the voice asks: rects from the half drawer ride with it, rects from the full one sit under its top.
  const cues = BOXES.filter((b) => b.box).map((b) => ({
    at: b.at,
    box: { ...b.box!, y: b.box!.y + top - (b.space === "half" ? HALF : FULL) },
  }));
  const next = cues[1]?.at ?? EXPAND + 10;
  const pulling = interpolate(frame, [EXPAND, EXPAND + 3, next, next + 3], [1, 0, 0, 1], clamp);
  return (
    <>
      {base}
      {pinned ? (
        <Img
          src={file(`app/${app.bar.file}`)}
          style={{ position: "absolute", left: 0, top: 0, width: PHONE.width, boxShadow: "0 2px 10px rgba(42,15,20,0.12)" }}
        />
      ) : null}
      {frame >= OPEN ? (
        <>
          {/* what's above the drawer at half height (the list, as the site dims it), fading in as it opens */}
          <div style={{ position: "absolute", left: 0, top: 0, width: PHONE.width, height: HALF * CSS, overflow: "hidden", opacity: opened }}>
            <Img src={file("app/detail-half.png")} style={{ position: "absolute", left: 0, top: 0, width: PHONE.width }} />
          </div>
          <Slice src="detail-half.png" fromY={HALF} top={top} opacity={1 - pulled} />
          {frame >= EXPAND ? <Slice src="detail-full.png" fromY={FULL} top={top} opacity={pulled} /> : null}
          <Highlight frame={frame} cues={cues} opacity={pulling} />
        </>
      ) : null}
    </>
  );
};

export const App: React.FC = () => {
  const { frame, t } = useScene();
  const cam = camera(t, SCENES.app, SCENES.free, { zoom: 0.035, driftX: 10, driftY: -12 });
  const accent = kick(t, [3 * BAR, 4 * BAR, 5 * BAR]);
  const phoneIn = sp(frame, -4, SPRING.snap);
  const titles = [
    {
      at: TAPS[0],
      node: (
        <>
          {CHIPS[0].label}
          {CHIPS.slice(1).map((c, i) => (
            <Word key={c.style} frame={frame} start={TAPS[i + 1]} distance={50}>
              {" + "}
              {c.label}
            </Word>
          ))}
        </>
      ),
      size: 88,
    },
    ...FLICKS.map((c) => ({ at: c.at, node: <>{c.title}</>, size: 100 })),
    ...BOXES.map((b) => ({ at: b.at, node: <>{b.title}</>, size: 100 })),
  ];
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <AbsoluteFill style={cam(0.5)}>
        {titles.map((x, i) => (
          <PeriodTitle key={i} frame={frame} start={x.at} exitAt={titles[i + 1]?.at} size={x.size} pulse={accent}>
            {x.node}
          </PeriodTitle>
        ))}
      </AbsoluteFill>
      <AbsoluteFill style={cam(1)}>
        <AbsoluteFill style={{ translate: `0px ${180 * (1 - phoneIn)}px` }}>
          <Phone>
            <Screen frame={frame} />
          </Phone>
          <Thumb frame={frame} keys={KEYS} />
        </AbsoluteFill>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Fast moves inside the shot (scene frames) that get motion blur: the drawer opening and being pulled up. */
export const APP_BLUR: [number, number][] = [
  [OPEN, OPEN + 6],
  [EXPAND, EXPAND + 7],
];
