// The teaser: five scenes on the beat (STORYBOARD.md) joined by motivated moves instead of hard cuts (an iris out
// of the record's spot, two whip pans with motion blur, a match cut from the sticker to the record), the grain
// over everything, and one soundtrack.
import React from "react";
import { AbsoluteFill, Composition, Folder, useCurrentFrame } from "remotion";
import {
  Captions,
  samplesFor,
  Scene,
  sec,
  Shutter,
  vertical,
  VideoShell,
  whip,
  WHIP_LEAD,
  whipBlur,
} from "../../src/kit";
import timingJson from "./data/timing.json";
import { App, APP_BLUR } from "./scenes/App";
import { Cover, IRIS_FRAMES } from "./scenes/Cover";
import { type Cta, End } from "./scenes/End";
import { Free, LAUNCH } from "./scenes/Free";
import { Question, QUESTION_BLUR } from "./scenes/Question";
import { file, SCENES } from "./theme";
import settings from "./video.json";

export type TeaserProps = { soundtrack: "voice-only" | "with-music"; cta: Cta; blur?: boolean };

const CUT = {
  cover: sec(SCENES.cover),
  app: sec(SCENES.app),
  free: sec(SCENES.free),
  end: sec(SCENES.end),
  out: sec(SCENES.out),
};

/** Frames (absolute) with fast movement get motion blur; the whips get more samples. */
const WHIPS: [number, number][] = [whipBlur(CUT.app), whipBlur(CUT.free)];
const BLUR: [number, number][] = [
  ...QUESTION_BLUR,
  ...WHIPS,
  ...APP_BLUR.map(([a, b]) => [a + CUT.app, b + CUT.app] as [number, number]),
  [CUT.end + LAUNCH - 1, CUT.end + 9],
];

const Scenes: React.FC<{ cta: Cta }> = ({ cta }) => (
  <AbsoluteFill>
    <Scene name="1 Question" start={0} end={CUT.cover} post={1}>
      <Question />
    </Scene>
    <Scene
      name="2 Cover"
      start={CUT.cover}
      end={CUT.app}
      pre={IRIS_FRAMES}
      post={10}
      move={(abs) => {
        const { p, dip } = whip(abs, CUT.app);
        return { translate: `0px ${dip - 1920 * p}px` };
      }}
    >
      <Cover />
    </Scene>
    <Scene
      name="3 App"
      start={CUT.app}
      end={CUT.free}
      pre={WHIP_LEAD + 1}
      post={10}
      move={(abs) => {
        const into = whip(abs, CUT.app);
        const out = whip(abs, CUT.free);
        return { translate: `${out.dip * -1 - 1080 * out.p}px ${1920 * (1 - into.p) + into.dip}px` };
      }}
    >
      <App />
    </Scene>
    <Scene
      name="4 Free"
      start={CUT.free}
      end={CUT.end}
      pre={WHIP_LEAD + 1}
      move={(abs) => {
        const { p, dip } = whip(abs, CUT.free);
        return { translate: `${1080 * (1 - p) - dip}px 0px` };
      }}
    >
      <Free />
    </Scene>
    <Scene name="5 End" start={CUT.end} end={CUT.out}>
      <End cta={cta} />
    </Scene>
  </AbsoluteFill>
);

export const Teaser: React.FC<TeaserProps> = ({ soundtrack, cta, blur = true }) => {
  const frame = useCurrentFrame();
  // A Story: it fades in from the paper and never out (the owner, 5 Oct 2026).
  return (
    <VideoShell fadeIn={8} audio={file(`audio/${soundtrack}.wav`)}>
      <Shutter samples={blur ? samplesFor(frame, BLUR, WHIPS) : 1}>
        <Scenes cta={cta} />
      </Shutter>
      {/* Off unless video.json has "captions" (src/brand/captions.tsx). */}
      <Captions video={settings} timing={timingJson} format={cta} />
    </VideoShell>
  );
};

/**
 * Three deliverables: the Story without music (Instagram's music goes under it) and with the bed, both ending on
 * "Link aquí arriba" with a drawn arrow, right under the band at the top that the link sticker covers; and the Reel
 * (no link stickers on Reels), with music, ending on "Link en mi perfil".
 */
export const TeaserV2: React.FC = () => {
  const common = { component: Teaser, ...vertical(settings) };
  return (
    <Folder name="teaser-v2">
      <Composition
        id="teaser-v2-voice-only"
        {...common}
        defaultProps={{ soundtrack: "voice-only" as const, cta: "story" as const, blur: true }}
      />
      <Composition
        id="teaser-v2-with-music"
        {...common}
        defaultProps={{ soundtrack: "with-music" as const, cta: "story" as const, blur: true }}
      />
      <Composition
        id="teaser-v2-reel"
        {...common}
        defaultProps={{ soundtrack: "with-music" as const, cta: "reel" as const, blur: true }}
      />
    </Folder>
  );
};
