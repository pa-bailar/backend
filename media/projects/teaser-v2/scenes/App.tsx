// Scene 3 (6.12–14.69): "Miras qué hay hoy, este finde, la otra semana… a qué hora, dónde, cuánto vale y cómo
// llegar." One continuous phone shot of the LIVE site (light theme), driven by a thumb:
//   1. "Ritmo ▾" opens its checklist; Salsa and Bachata get ticked (the multi-select filters).
//   2. The thumb flicks the list to each period as the voice names it: Hoy, Este fin de semana, Próxima semana.
//      Each flick glides and settles a hair past the stop; the sticky bar hides while scrolling down and comes
//      back when it settles, as on the site.
//   3. A tap on the event's "Detalles" opens the site's half-height sheet under its flyer (spring); a frame lands on
//      the time, then the thumb pulls the sheet up to full height and the frame visits Lugar, the prices and
//      "Cómo llegar" as the voice asks.
// Every position comes from data/app.json (capture.mjs), so a re-capture flows through.
import React from "react";
import { AbsoluteFill, Easing, Img, interpolate } from "remotion";
import {
  C,
  camera,
  clamp,
  Crop,
  Highlight,
  kick,
  mid,
  mix,
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
  union,
  useScene,
  Word,
} from "../../../src/kit";
import app from "../data/app.json";
import { BAR, file, SCENES, word } from "../theme";

const f = (s: number) => sec(s) - sec(SCENES.app);
const { css: CSS, sx, sy } = PHONE;

// ---------- the beats of the shot ----------
const TAP_STYLE = f(6.45);
const TAPS = app.styles.map((_, i) => f(6.72 + i * 0.25)); // Salsa, Bachata…
const CLOSE = f(7.16); // the thumb goes down on the list: the menu closes (tap outside)
const periodTop = (key: string) => {
  const p = app.periods.find((x) => x.key === key);
  if (!p) throw new Error(`no period ${key} in app.json`);
  return p.top - 64; // where the site puts a period: right under the bar
};
const FLICKS = [
  { at: f(word("c1", "hoy") - 0.22), key: "hoy", title: "Hoy" },
  { at: f(word("c1", "este") - 0.2), key: "fin-de-semana", title: "Este finde" },
  { at: f(word("c1", "la") - 0.15), key: "proxima-semana", title: "La otra semana" },
].map((c) => ({ ...c, to: periodTop(c.key) }));
const TAP_EVENT = f(10.86); // "Detalles" on the card (or the card itself)
const SHEET = TAP_EVENT + 3; // the details open: the flyer fades in above, the sheet rises to half height
const EXPAND = f(11.58); // the thumb pulls the sheet up to full height

const D = app.detail;
const HALF = D.sheet; // the sheet at half height (CSS px in the viewport)
type Space = "half" | "full"; // which capture a rect is in: detail-sheet.png (half) or detail-rows.png (full)
const half = D.half as Record<string, Rect | null>;
const rows = D.rows as unknown as Record<string, Rect | null>;
const prices = rows.precios ? (rows.preciosHeading ? union(rows.preciosHeading, rows.precios) : rows.precios) : rows.precio;
const BOXES: { at: number; title: string; box: Rect | null; space: Space }[] = [
  // "a qué hora": the when line at the top of the half sheet, right as it opens
  { at: f(word("c2", "hora") - 0.25), title: "¿A qué hora?", box: half.when ? pad(half.when, 8, 6) : null, space: "half" },
  { at: f(word("c2", "dónde") - 0.12), title: "¿Dónde?", box: rows.lugar && pad(rows.lugar, 8, 6), space: "full" },
  { at: f(word("c2", "cuánto") - 0.12), title: "¿Cuánto vale?", box: prices && pad(prices, 8, 6), space: "full" },
  { at: f(word("c2", "cómo") - 0.12), title: "¿Cómo llegar?", box: rows.comoLlegar && pad(rows.comoLlegar, 8, 5), space: "full" },
];

/** Top of the sheet (CSS px) at a frame: rises from the bottom to half height, then is pulled up to the top. */
function sheetTop(frame: number): number {
  const rise = sp(frame, SHEET, SPRING.sheet);
  const pull = sp(frame, EXPAND, SPRING.sheet);
  return 640 + (HALF.y - 640) * rise - HALF.y * pull;
}

/** The list's scroll (CSS px) at a frame: each flick a spring from where the last one left it. */
function scrollAt(frame: number): number {
  let y = 0;
  let from = 0;
  for (const c of FLICKS) {
    y += (c.to - from) * sp(frame, c.at, SPRING.thumb);
    from = c.to;
  }
  return y;
}

/** The thumb's path: tap the button, tick each style, then flick, flick, flick, and tap the event. */
function thumbKeys(): ThumbKey[] {
  const button = mid(app.top.styleButton);
  const keys: ThumbKey[] = [{ f: TAP_STYLE - 7, x: sx(button.x + 30), y: sy(button.y + 240) }];
  keys.push({ f: TAP_STYLE, x: sx(button.x), y: sy(button.y), tap: true });
  app.styles.forEach((s, i) => {
    const box = (app.menu.items as Record<string, Rect>)[s];
    keys.push({ f: TAPS[i], x: sx(box.x + 22), y: sy(mid(box).y), tap: true }); // on the checkbox: the label stays readable
  });
  FLICKS.forEach((c, i) => {
    const down = i === 0 ? CLOSE : c.at - 4;
    keys.push({ f: down, x: sx(190), y: sy(560), down: true });
    keys.push({ f: c.at + 4, x: sx(205), y: sy(300) });
  });
  const tap = mid(D.tap);
  keys.push({ f: TAP_EVENT, x: sx(tap.x), y: sy(tap.y - D.scrollTop), tap: true });
  keys.push({ f: EXPAND - 3, x: sx(200), y: sy(HALF.y + 18), down: true }); // on the sheet's bar
  keys.push({ f: EXPAND + 7, x: sx(205), y: sy(24) });
  return keys;
}
const KEYS = thumbKeys();

const Screen: React.FC<{ frame: number }> = ({ frame }) => {
  const scroll = scrollAt(frame);
  const menu = app.menu.rect;
  const buttonX = mid(app.top.styleButton).x;
  const origin = `${(buttonX - menu.x + 14) * CSS}px 0px`;
  const open = sp(frame, TAP_STYLE + 1, SPRING.sheet);
  const closing = interpolate(frame, [CLOSE, CLOSE + 5], [0, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const ticked = TAPS.filter((t) => frame >= t + 1).length;
  const opening = frame > TAP_STYLE && frame < TAP_STYLE + 9;

  // The sticky bar: hidden while the list moves down, back once it settles (the site's Instagram-like bar).
  let hide = 0;
  for (let k = 0; k <= 6; k++) {
    const v = scrollAt(frame - k) - scrollAt(frame - k - 1);
    if (v > 1.5) hide = Math.max(hide, 1 - k / 7);
  }
  const bars = app.bars as Record<string, { file: string; h: number }>;
  const current = [...FLICKS].reverse().find((c) => scroll >= c.to - 40) ?? FLICKS[0];
  const bar = bars[current.key];
  const showBar = frame >= CLOSE && scroll > app.top.bar.y && bar;

  const top = sheetTop(frame);
  const opened = interpolate(frame, [SHEET, SHEET + 2], [0, 1], clamp);
  const pulled = interpolate(frame, [EXPAND + 1, EXPAND + 6], [0, 1], clamp);

  let base: React.ReactNode;
  if (frame < CLOSE) {
    const shot = frame <= TAP_STYLE || opening ? "top.png" : `menu-${ticked}.png`;
    base = <Img src={file(`app/${shot}`)} style={{ position: "absolute", left: 0, top: 0, width: PHONE.width }} />;
  } else {
    // Motion blur for the flick, done here (cheap and exact): the list drawn at several moments of a 180° shutter.
    const speed = Math.abs(scrollAt(frame + 0.5) - scrollAt(frame - 0.5)) * CSS;
    base = smear(frame, speed, (at, i, opacity) => (
      <Img
        key={i}
        src={file(`app/${app.list.file}`)}
        style={{
          position: "absolute",
          left: 0,
          top: -scrollAt(at) * CSS,
          width: PHONE.width,
          height: app.list.cssHeight * CSS,
          opacity,
        }}
      />
    ));
  }
  // The frame on what the voice asks: rects from the half sheet ride with it, rects from the pulled-up sheet sit
  // under its top. While the sheet is being pulled up it steps aside, and comes back on the next row.
  const cues = BOXES.filter((b) => b.box).map((b) => ({
    at: b.at,
    box: { ...b.box!, y: b.box!.y + (b.space === "half" ? top - HALF.y : top) },
  }));
  const next = cues[1]?.at ?? EXPAND + 10;
  const pulling = interpolate(frame, [EXPAND, EXPAND + 3, next, next + 3], [1, 0, 0, 1], clamp);
  return (
    <>
      {base}
      {opening ? (
        <Crop
          src={file("app/menu-0.png")}
          r={menu}
          origin={origin}
          style={{ opacity: interpolate(frame, [TAP_STYLE + 1, TAP_STYLE + 4], [0, 1], clamp), scale: `${mix(0.9, 1, open)}` }}
        />
      ) : null}
      {frame >= CLOSE && closing < 1 ? (
        <Crop
          src={file(`app/menu-${app.styles.length}.png`)}
          r={menu}
          origin={origin}
          style={{ opacity: 1 - closing, scale: `${1 - 0.06 * closing}` }}
        />
      ) : null}
      {showBar ? (
        <Img
          src={file(`app/${bar.file}`)}
          style={{
            position: "absolute",
            left: 0,
            top: -bar.h * CSS * hide,
            width: PHONE.width,
            boxShadow: "0 2px 10px rgba(42,15,20,0.12)",
          }}
        />
      ) : null}
      {frame >= SHEET ? (
        <>
          {/* the event's flyer above the sheet: it comes up with the sheet, then stays put (sticky) while the
              sheet is pulled up over it, as on the site */}
          <div
            style={{
              position: "absolute",
              left: 0,
              top: Math.max(0, top - HALF.y) * CSS,
              width: PHONE.width,
              height: HALF.y * CSS + 4,
              overflow: "hidden",
              opacity: opened,
            }}
          >
            <Img src={file("app/detail-open.png")} style={{ position: "absolute", left: 0, top: 0, width: PHONE.width }} />
          </div>
          <Img
            src={file(`app/${HALF.file}`)}
            style={{ position: "absolute", left: HALF.x * CSS, top: top * CSS, width: HALF.w * CSS, opacity: 1 - pulled }}
          />
          {frame >= EXPAND ? (
            <Img
              src={file("app/detail-rows.png")}
              style={{ position: "absolute", left: 0, top: top * CSS, width: PHONE.width, opacity: pulled }}
            />
          ) : null}
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
          {app.styles[0]}
          {app.styles.slice(1).map((s, i) => (
            <Word key={s} frame={frame} start={TAPS[i + 1]} distance={50}>
              {" "}+ {s}
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

/** Fast moves inside the shot (scene frames) that get motion blur: the sheet opening and being pulled up. */
export const APP_BLUR: [number, number][] = [
  [SHEET, SHEET + 6],
  [EXPAND, EXPAND + 7],
];
