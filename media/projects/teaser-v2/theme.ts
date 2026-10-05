// This video's clock: the voice's timing (data/timing.json, tools/timing.py), its 98 bpm grid, and where the scenes
// cut. Everything else comes from the kit.
import { assets, gridOf, makeTiming } from "../../src/kit";
import timingJson from "./data/timing.json";
import settings from "./video.json";

export const VIDEO = "teaser-v2";
/** Files in public/teaser-v2/ (app screens from capture.mjs, the soundtracks from tools/mix.py). */
export const file = assets(VIDEO);
export const DURATION_S = settings.duration; // video.json: tools/mix.py pads the audio to it too

const timing = makeTiming(timingJson);
export const { line, word } = timing;

export const { BEAT, BAR, beats, downbeats } = gridOf(settings); // video.json's music.bpm (98)

// Scene boundaries (video seconds) on the 98 bpm grid. The list and the detail are one continuous phone scene.
export const SCENES = {
  question: 0,
  cover: 7 * BEAT, // 4.29
  app: 10 * BEAT, // 6.12
  free: 24 * BEAT, // 14.69 (a downbeat)
  end: 28 * BEAT, // 17.14 (a downbeat)
  out: DURATION_S,
};
