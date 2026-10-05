# Media: Pa' Bailar's video toolkit

Short vertical videos about the site (Instagram Stories and Reels), made by Claude and directed by the owner, at $0.
This page is the **catalog**: what exists, what each piece is for, and how a video gets made. Read it instead of
the code. The motion rules are in [MOTION.md](MOTION.md) and the video design system is in [DESIGN.md](DESIGN.md).

It's a toolkit, not a template. Every video is its own composition, free in format, length and structure. It
builds from shared pieces: tools that make voice, music, screens and data, and a Remotion library of motion and
brand building blocks.

```
media/
├── README.md, MOTION.md, DESIGN.md   this catalog, the motion rules, the design tokens for video
├── tools/            the utilities (Python + one Node script), each takes a video's name
├── src/
│   ├── kit.ts        the library in one import
│   ├── lib/          tokens, motion, scene clock, motion blur, transitions, voice timing, fonts
│   ├── brand/        the record, stripes, period titles, kinetic type, phone + thumb, flyers, stickers
│   ├── data/         helpers over a snapshot of the site's events
│   └── Root.tsx      registers every video's compositions
├── projects/<video>/ one folder per video: video.json (settings for the tools), its compositions, its notes,
│                     data/ (small JSON the composition imports: timing, captures, events; committed)
├── public/fonts/     the site's three faces (committed); public/<video>/ = screens, flyers, audio (generated)
├── cache/            TTS lines and music beds, by content hash (generated, never committed)
└── out/<video>/      renders, drafts, frames, sheets (never committed)
```

## Setup (once per machine)

| What | How |
|---|---|
| Node packages (Remotion 4.0.532, playwright-core) | `cd media && npm install` |
| ffmpeg 9 | `winget install Gyan.FFmpeg` (the tools also find the winget path off PATH) |
| Python for TTS, mix, events, render, review | the backend's `.venv` (google-genai is already there; the rest is the standard library) |
| Whisper (timing) and librosa (music analysis) | `D:\AI\whisper\.venv` (faster-whisper, medium model, CPU) |
| ACE-Step 1.5 (music) | `D:\AI\ace-step\.venv`, on the GPU; see `D:\AI\README.md` |
| Chrome (captures) | the installed Chrome, driven headless |
| Gemini TTS key | `MEDIA_GEMINI_API_KEY` in the backend's `.env` (a separate free-tier project; images and Veo aren't free) |

The Remotion agent skills load when working in `media/`. They aren't committed: install them once with
`cd media && npx skills add remotion-dev/skills` (the versions used are pinned in `skills-lock.json`).

## Making a video

Each stage leaves a file the next stage reads. Never put the whole video in one prompt.

1. **Brief**: `projects/<video>/` with a short README: the goal, the audience, where it's posted, its length, and its
   deliverables. Specs: 1080×1920, 30 fps, H.264 + AAC; text inside the safe zones (`SAFE`).
2. **Script → voice** (when it has one): the lines go in `video.json` → `tools/tts.py` (cached per line) → listen.
   To choose a voice: `tts.py --audition "<line>" --voices A,B,C`.
3. **Timing**: `tools/timing.py` joins the lines and times every word. The animation follows the voice.
4. **Music** (optional; Stories often use Instagram's): `tools/music.py` generates candidates, then
   `tools/analyze.py` compares them, then set `bed` + `first_hit` → `tools/mix.py`.
5. **Material**: real screens (`tools/capture.mjs`, or a scripted walk like the teaser's), real events and flyers
   (`tools/events.py`). Generate nothing that exists.
6. **Storyboard**: scene by scene, on the beat grid, with one deliberate movement per beat and a motivated
   transition into the next scene.
7. **Composition**: `projects/<video>/*.tsx` built from the kit, plus one line in `src/Root.tsx`.
8. **Look before watching**: `render.py --frames`, then `--draft`, then `review.py sheet`. The owner sees a full
   render (and `review.py compare` against the last version), then targeted fixes.

## Tools

Run from the backend root. `.venv` = `.venv/Scripts/python`, whisper = `D:/AI/whisper/.venv/Scripts/python`,
ace = `D:/AI/ace-step/.venv/Scripts/python`. Each tool's docstring has the details (`--help`).

| Tool | Python | Does | Writes |
|---|---|---|---|
| `tts.py <video> [ids]` | .venv | Gemini TTS per line (voice, direction, `take` per line), retries, model fallback | `cache/tts/<hash>.wav` |
| `tts.py --audition "<text>" --voices …` | .venv | one sample per voice | `out/auditions/` |
| `timing.py <video>` | whisper | trims and joins the lines (`lead`, `gap`, `max_pause`), Whisper word times | `out/<video>/voice-track.wav`, `data/timing.json` |
| `timing.py --transcribe <wav>` | whisper | what Whisper hears in a take (QA) | (prints) |
| `music.py <video>` | ace | ACE-Step beds for every prompt × seed (cached) | `cache/music/<prompt>-s<seed>-<hash>.wav` |
| `analyze.py <wavs>` | whisper | bpm, beats, first hit, loudness, a spectrogram strip | `out/music/music-analysis.{png,json}` |
| `mix.py <video>` | .venv | voice-only (−15 LUFS) and with-music (−14, bed ducked by the voice), fades, exact length; a video with no voice: music-only (−16) | `public/<video>/audio/` |
| `events.py <video> --from --to \| --weekend [date] [--styles] [--limit n] [--live] [--allow-empty]` | .venv | the events on those days (sorted by the day the video shows, with that day's times: `day`, `day_start`, `day_end`) + their cover flyers; an empty result writes nothing | `data/events.json`, `public/<video>/flyers/` |
| `node media/tools/capture.mjs <video> <name> [--path --now --theme --full --scroll --click --wait]` | Node | one screen of the live site on a phone, clock frozen (also a library for scripted walks) | `public/<video>/screens/`, `data/screens.json` |
| `render.py <video> [--draft] [--frames 90,240]` | .venv | Remotion renders of `video.json`'s `renders` | `out/<video>/*.mp4`, `frames/` |
| `review.py sheet <mp4> [--at …]` | .venv | a keyframe strip with the safe zones | `<mp4>-sheet.png` |
| `review.py compare <a> <b>` | .venv | side by side, labeled, for the owner | `<a>-vs-<b>.mp4` |
| `review.py diff <a> <b>` | .venv | PSNR per frame (∞ = identical): a refactor must not change a render | (prints) |

## `video.json`

```jsonc
{
  "title": "…", "fps": 30, "duration": 21.0,
  "voice": { "name": "Achird", "direction": "(optional; tts.py has the owner's chosen one)", "lead": 0.55,
             "max_pause": 0.32, "lines": [{ "id": "a1", "text": "…", "gap": 0.3, "take": 0 }] },
  "music": { "bpm": 98, "duration": 30, "seeds": [7], "prompts": { "name": "…" },
             "bed": "cache/music/….wav", "first_hit": 0.07 },
  "mix": { "fade": 0.3, "voice_only_lufs": -15, "with_music_lufs": -14, "bed_db": -8 },
  "renders": { "voice-only": "<composition id>", "reel": "…" }   // file name → composition id
}
```

Only `duration` and `renders` are required; compositions import `video.json` for their length, so `mix.py` and the
picture agree. The frame rate is the kit's (30 fps, `FPS`). Composition ids are `<video>-<deliverable>`, inside a
`<Folder>` named after the video. Every composition takes a `blur` prop (motion blur on or off; `render.py --draft` turns it off).

## The library (`src/kit.ts`)

**`lib/tokens`**: `FPS` 30, `WIDTH`×`HEIGHT` 1080×1920, `SAFE` {top 250, bottom 1580, side 80}, `sec(s)`, colors
`C` (light theme "Fania de día"), `STRIPES`, `FONT` (Shrikhand, Bodoni Moda, Instrument Sans, emoji), and type
presets `TYPE.display(size, color?, shadow?)`, `TYPE.serif(size, color?)` (small optical size: hairlines survive
H.264), `TYPE.sans(size, color?)`.

**`lib/motion`** (the rules in code):
- `SPRING`: `snap` (default entrance), `sheet`, `weight` (things that land), `pop` (stickers), `thumb` (scrolls),
  `whip`.
- `sp(frame, start, spring)` gives progress 0→1 with overshoot; `spv` is its speed (for squash and stretch).
- `rise(frame, start, {distance, exitAt})` is THE entrance (and exit) as a style. `leave(frame, at)` is an exit
  progress.
- `jit(seed)` gives irregular staggers of ±1–2 frames. `mix(a, b, k)` and `clamp` are helpers.
- `grid(bpm)` gives `BEAT`, `BAR`, `beats(from, to)` and `downbeats(from, to)`.
- `kick(t, times)` is a beat accent 0→1→0. `wobble(frame, times)` is a damped nudge (secondary action).
- `camera(t, from, to, {zoom, driftX, driftY})(depth)` is the slow push-in and drift with parallax by depth.

**`lib/scene`**:
- `<Scene start end pre post move name>` is a scene that overlaps its neighbors for transitions.
- `useScene()` gives `{frame, abs, t}`.
- `<FadeIn frames>` eases in from the paper; `<FadeOut frames>` fades out to it at the end (the owner's rule: fade in
  and out).

**`lib/blur`**:
- `<Shutter samples>` is exact-color motion blur over everything; `samplesFor(frame, ranges, fastRanges)` picks
  the samples per frame; `inRanges(frame, ranges)` tests one.
- `smear(frame, speed, render)` is cheap blur inside one layer (a scrolling screenshot).

**`lib/transitions`**:
- `whip(abs, cut, lead = WHIP_LEAD)` gives `{p, dip}`, a whip pan with anticipation starting `lead` (5) frames
  before the cut; `whipBlur(cut)` is its blur window.
- `iris(frame, at)` is a clip-path circle opening from a point.
- Match cuts: share one function between the two scenes (the teaser's `flight`).

**`lib/timing`**: `makeTiming(timingJson)` gives `line(id)` (start/end) and `word(id, "dónde", nth)` (a word's
start). **`lib/fonts`**: loads the faces (`fontsReady` resolves when they're in); `assets(video)(path)` is a `staticFile` in
`public/<video>/`.

**`brand/`**:

| Piece | What it is |
|---|---|
| `Record`, `spinAngle(t, start, ramp)` | the logo's record, spinning up like a platter to 33⅓ rpm, with a fixed sheen |
| `Grain` | paper/offset grain over everything (multiply, 10%, new seed every 2 frames) |
| `Stripes` | the 70s triple stripe, bands wiping in on springs |
| `PeriodTitle` | the site's period heading (rule, word, rule build in), chained with `exitAt`, `pulse` on the beat |
| `Word`, `Words`, `Letters` | kinetic type: a word on a spring with a settling tilt; a row of timed words; a wordmark letter by letter |
| `Phone`, `phoneAt()`, `PHONE` | a flat phone; its geometry maps site CSS px to the scene (`css`, `sx`, `sy`) |
| `Crop` | part of a screenshot drawn where it sits (a menu or sheet animating on its own) |
| `Thumb` + `ThumbKey[]` | a touch on an arc: taps with a ripple, drags while pressed, lifts |
| `Highlight` | a frame that springs from one rect to the next (pointing at what the voice names) |
| `Rect`, `mid`, `pad`, `union` | rect helpers for capture positions |
| `Flyer`, `toss()` | a real flyer (whole, the site's border, a shadow that lifts); a throw onto a pile with weight |
| `Sticker`, `AppIcon` | the round tomato sticker; the app icon's squircle |

**`data/events`**:
- `VideoEvent` and `EventsSnapshot` are the shape of `events.json`; show `day`/`day_start`, not `date`/`start_time`.
- `daysOf`, `between(events, from, to, styles)` and `weekend(today)` select events.
- `dateLabel`, `spanLabel`, `timeLabel` and `priceLabel` give the site's wording ("sábado 10 oct", "8:00 p. m.", "Desde
  $25.000").

## Videos

| Folder | What | Notes |
|---|---|---|
| [`teaser-v2`](projects/teaser-v2/) | The 21 s teaser of the site: voice, beat-cut scenes, a thumb driving the live site, three deliverables (Story ×2, Reel) | The worked example of everything; renders pixel-identical to the original project (`pa-bailar-teaser`, kept as the archive). Its `capture.mjs` predates the Oct 4 site (filter bar, drawer, no account filter): rewrite it before re-capturing (its README lists what changed) |
| [`este-finde`](projects/este-finde/) | A 12 s weekly Story of the coming weekend's events, from data only, no voice | `events.py este-finde --weekend --live`, then render (`este-finde-story`). Example, not yet reviewed by the owner |

## Rules that bite

- Real material only: text, logos, dates and UI are code or real screenshots; flyers are the academies' own.
  Nothing AI-generated but the voice and the music.
- Owner decisions so far: the light theme, no URL on screen (Story: "Link aquí abajo 👇" over an empty y 1360–1580
  band for the link sticker; Reel: "Link en mi perfil"), fade audio and picture in and out, the Bodoni at
  `opsz` 18 / 600.
- Screens and events date a video: post it before its shelf life ends (`app.json` / `events.json` record it).
- Gemini TTS times out at times: the tool retries, and a cached line never calls it again.
- Don't regenerate what exists: change a line's `take` for a new reading; keep the cache.
