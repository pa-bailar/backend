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
├── brand.json        the canvas, safe zones, sticker band, Reel safe zones, default tempo, loudness targets (TS and
│                     Python read it)
├── tools/            the utilities (Python and Node), each takes a video's name
├── src/
│   ├── kit.ts        the library in one import
│   ├── lib/          tokens, motion, scene clock, motion blur, transitions, voice timing, fonts
│   ├── brand/        the shell and end card, record, stripes, period titles, kinetic type, phone + thumb, flyers
│   ├── data/         helpers over a snapshot of the site's events
│   └── Root.tsx      registers every video's compositions
├── projects/<video>/ one folder per video: video.json (settings for the tools), its compositions, its notes,
│                     data/ (small JSON the composition imports: timing, captures, events; committed)
├── fonts/            the site's three faces (committed, bundled with the code)
└── tests/            the tools' pure functions (pytest) and the weekend rule in JS (node --test)
```

### The media home

Everything generated lives outside the checkout, in **`D:\AI\pa-bailar-media`** (`PA_BAILAR_MEDIA_HOME` overrides
it; `tools/common.py`, `tools/paths.mjs` and `remotion.config.ts` read it), so every worktree shares it and removing a
worktree can't delete it:

```
D:\AI\pa-bailar-media\
├── cache/tts/, cache/music/     TTS lines and music beds, by content hash (the bed can't be made again by chance)
├── public/<video>/              screens, flyers, audio: Remotion's public folder (staticFile, assets(video))
├── out/<video>/                 renders (<video>-v<version>-<deliverable>.mp4), drafts, frames, sheets, comparisons
├── out/.bundle/, out/check/     the stills bundle (made again when the code changes), npm run check's stills
└── archive/<video>/v<version>/  each posted version, whole: its renders, public/ as it was, its project files
```

The checkout's old `media/cache`, `media/public/<video>` and `media/out/<video>` are copies from before the home;
`clean.py` lists them once the home holds identical files. `media/out/` also keeps some site checks (`*.mjs`,
`site-bugs/`, `site-quality/`, `admin-tabs/`): `clean.py` skips them by name. New checks go in a scratch folder, not
in `media/out/`.

## Setup (once per machine)

| What | How |
|---|---|
| Node packages (Remotion 4.0.532, playwright-core) | `cd media && npm ci` |
| ffmpeg 9 | `winget install Gyan.FFmpeg` (the tools also find the winget path off PATH) |
| Python for TTS, mix, events, render, review, make | the backend's `.venv` (google-genai is already there; the rest is the standard library) |
| Whisper (timing) and librosa (music analysis) | `D:\AI\whisper\.venv` (faster-whisper, medium model, CPU) |
| ACE-Step 1.5 (music) | `D:\AI\ace-step\.venv`, on the GPU; see `D:\AI\README.md` |
| Chrome (captures) | the installed Chrome, driven headless |
| Gemini TTS key | `MEDIA_GEMINI_API_KEY` in the backend's `.env` (a separate free-tier project; images and Veo aren't free) |
| The media home | `D:\AI\pa-bailar-media` (made by the tools), or set `PA_BAILAR_MEDIA_HOME` |

Then `.venv/Scripts/python media/tools/make.py doctor` checks all of it (the key: set or not, never shown).

The Remotion agent skills load when working in `media/`. They aren't committed: install them once with
`cd media && npx skills add remotion-dev/skills` (the versions used are pinned in `skills-lock.json`).

## Making a video

Each stage leaves a file the next stage reads. Never put the whole video in one prompt.

1. **Brief**: `tools/new.py <video>` makes the folder, a README for the brief (goal, audience, where it's posted,
   length, deliverables), `video.json` and a composition that already renders (on `VideoShell` and `EndCard`),
   registered in `src/Root.tsx`. Specs: 1080×1920, 30 fps, H.264 + AAC; text inside the safe zones (`SAFE`), nothing
   in a Story's sticker band (`STICKER_BAND`).
2. **Script → voice** (when it has one): the lines go in `video.json` → `tools/tts.py` (cached per line) → listen.
   To choose a voice: `tts.py --audition "<line>" --voices A,B,C`.
3. **Timing**: `tools/timing.py` joins the lines and times every word. The animation follows the voice.
4. **Music** (optional; Stories often use Instagram's): `tools/music.py` generates candidates, then
   `tools/analyze.py` compares them, then set `bed` + `first_hit` → `tools/mix.py`.
5. **Material**: real screens (`tools/capture.mjs`, or a scripted walk like the teaser's), real events and flyers
   (`tools/events.py`). Generate nothing that exists.
6. **Storyboard**: scene by scene, on the beat grid, with one deliberate movement per beat and a motivated
   transition into the next scene.
7. **Composition**: `projects/<video>/*.tsx` built from the kit.
8. **Look before watching**: `tools/stills.mjs` (a few moments, in seconds), then `make.py <video> --draft` (half size,
   reviewed), then `make.py <video>` for the owner: the full render, its keyframe sheet, the sticker-band check and a
   side-by-side with the previous version. Then targeted fixes.

`tools/make.py <video>` runs stages 2–4 and 8 in order (tts → timing → mix → render → sheet), each with the Python it
needs and only when its inputs changed. Material and music stay manual: they change what the video shows.

**Versions.** `video.json` has a `version`; every render is named `<video>-v<version>-<deliverable>.mp4`, and
`out/<video>/<deliverable>.mp4` is a hard link to the newest (a stable name to grab). Bump the version for each cut
the owner sees: the old one stays to compare with (`render.py --review` finds it in `out/` or the archive), and
`clean.py` recycles older versions once a newer one exists. When a version is posted, copy its renders,
`public/<video>/` and project files into `archive/<video>/v<version>/` (as teaser v2.3).

## Tools

Run from the backend root. `.venv` = `.venv/Scripts/python`, whisper = `D:/AI/whisper/.venv/Scripts/python`,
ace = `D:/AI/ace-step/.venv/Scripts/python`. Each tool's docstring has the details (`--help`). Paths in "Writes" are
in the media home unless they start with `projects/`.

| Tool | Python | Does | Writes |
|---|---|---|---|
| `make.py <video> [stage …] [--draft --force --dry-run --strict]` | .venv | runs tts → timing → mix → render → sheet, only the stale ones, each with its Python | what each stage writes |
| `make.py doctor` | .venv | checks ffmpeg (and its libvmaf), Chrome, node and the packages, the three Pythons, the fonts, the key (set or not), each music bed, the media home | (prints) |
| `new.py <video> [--title --duration --reel]` | .venv | a new video's folder: brief, `video.json`, a composition on the kit, its line in `src/Root.tsx` | `projects/<video>/`, `src/Root.tsx` |
| `tts.py <video> [ids]` | .venv | Gemini TTS per line (voice, direction, `take` per line), retries timeouts and busy; stops at once on a refused key, skips a model on its daily quota | `cache/tts/<hash>.wav` |
| `tts.py --audition "<text>" --voices …` | .venv | one sample per voice | `out/auditions/` |
| `timing.py <video>` | whisper | trims and joins the lines (`lead`, `gap`, `max_pause`), Whisper word times, and a `voice_key` of what they were made from | `out/<video>/voice-track.wav`, `projects/<video>/data/timing.json` |
| `timing.py --transcribe <wav>` | whisper | what Whisper hears in a take (QA) | (prints) |
| `music.py <video>` | ace | ACE-Step beds for every prompt × seed (cached) | `cache/music/<prompt>-s<seed>-<hash>.wav` |
| `analyze.py <wavs>` | whisper | bpm, beats, first hit, loudness, a spectrogram strip | `out/music/music-analysis.{png,json}` |
| `mix.py <video> [--check]` | .venv | voice-only (−15 LUFS) and with-music (−14, bed ducked by the voice), fades, exact length; no voice: music-only (−16). Fails when a soundtrack's true peak is over −1 dBTP or its loudness 1 LU off (the old one stays); `--check` only measures | `public/<video>/audio/`, `mix.key` |
| `events.py <video> --from --to \| --weekend [date] [--styles] [--limit n] [--checkout] [--allow-empty]` | .venv | the events on those days from the published data (the site checkout with `--checkout` or offline, with its age), sorted by the day the video shows (`day`, `day_start`, `day_end`), + their cover flyers; written whole or not at all | `projects/<video>/data/events.json`, `public/<video>/flyers/` |
| `node media/tools/capture.mjs <video> <name> [--path --now --theme --full --scroll --click --wait]` | Node | one screen of the live site on a phone, clock frozen (default: the weekend rule's Saturday at 19:00); also the library for scripted walks | `public/<video>/screens/`, `projects/<video>/data/screens.json` |
| `node media/tools/stills.mjs <video> [deliverable] --at 1.5,f255,c4:link [--scale --no-blur --out]` | Node | stills from one bundle (reused while nothing changed): seconds, frames, a line's or a word's start | `out/<video>/frames/` |
| `render.py <video> [deliverables] [--draft] [--review] [--strict]` | .venv | Remotion renders of `video.json`'s `renders`; refuses stale timing, warns past the shelf life (`--strict` refuses); `--review`: Instagram pre-flight, sheet, band check (Stories), Reel safe zones (Reels), side-by-side with the previous version | `out/<video>/<video>-v<version>-<deliverable>[-draft].mp4` |
| `render.py <video> --frames 90,8.5s,c4:link [deliverable]` | .venv | stills through `stills.mjs` | `out/<video>/frames/` |
| `preflight.py <mp4 …> [--story \| --reel] [--api]` | .venv | will Instagram take it: MP4/MOV, H.264 or HEVC 4:2:0, 23–60 fps, 9:16, ≤1920 px wide, ≤25 Mbps, a Story clip ≤60 s / a Reel 3 s–15 min, ≤1 GB, AAC (over 128 kbps is a note), the moov atom first; `--api`: a Story ≤8 MB, faststart required. The kind from the name ("reel") unless given; exit 1 on a failure, warnings otherwise | (prints) |
| `cover.py <video> --at 19.5\|f585\|c4:link [--deliverable reel] [--grid 1080x1350]` | .venv | a Reel's cover: one frame at full size through `stills.mjs` (from the first Reel deliverable by default), the centered crop the profile grid shows, and the Reel safe-zone check on it (warnings) | `out/<video>/<video>-v<version>-cover.png`, `…-cover-grid.png` |
| `review.py sheet <mp4> [--at 1.5,f255,c4:link --timing <video> \| --every 2]` | .venv | a keyframe strip with the safe zones | `<mp4>-sheet.png` |
| `review.py compare <a> <b>` | .venv | side by side, labeled, for the owner (a draft against a full render works too) | `<a>-vs-<b>.mp4` |
| `review.py diff <reference> <new> [--no-vmaf]` | .venv | PSNR (∞ = identical), SSIM (1 = identical) and VMAF per frame, worst first: a refactor must not change a render (PSNR ∞); VMAF says whether an encode visibly damaged it (0–100, ~6 points is one just-noticeable difference; identical still frames score ~97, not 100). Stills too; a smaller one is scaled up. VMAF needs ffmpeg's libvmaf (winget's Gyan.FFmpeg full_build has it; without it, PSNR and SSIM and a note) | (prints) |
| `review.py band <mp4 or png …> [--video <name>] [--allow 4.2-4.3]` | .venv | nothing but the background above y 252 (the sticker band + 2 px) on any frame; `--video` allows its `sticker_band.allow` spans; exit 1 when something enters | (prints) |
| `review.py reel <mp4 or png …> [--video <name>] [--allow 4.2-4.3]` | .venv | the Reel's safe zones (108 top, 320 bottom, 60 left, 120 right): content in those margins is a warning per side, with the frames and how close to the edge it gets (images may run into them, words never); `--video` allows its `reel_safe.allow` spans | (prints) |
| `clean.py [--yes]` | .venv | lists older versions, drafts, stills, sheets, comparisons and scratch folders in the home's `out/`, the checkout's old copies the home already holds, and the teaser archive's leftovers; `--yes` moves them to the Recycle Bin. Latest versions, the archive and anything git tracks stay | (the Recycle Bin) |
| `npm run check` (in `media/`) | Node | `tsc`, every composition registers, one still per video | `out/check/` |
| `npm test` (in `media/`) | Node | the weekend rule in JS against `tests/weekend-cases.json` | (prints) |

The Python tests (`media/tests`, standard library only) run with the backend's: `.venv/Scripts/python -m pytest -q`.
CI's `media` job (in `.github/workflows/ci.yml`) runs `npm ci`, `tsc` and `npm test` when `media/` changes.

## `video.json`

```jsonc
{
  "title": "…", "version": "2.4", "fps": 30, "duration": 21.0,
  "voice": { "name": "Achird", "direction": "(optional; common.py has the owner's chosen one)", "lead": 0.55,
             "max_pause": 0.32, "lines": [{ "id": "a1", "text": "…", "gap": 0.3, "take": 0 }] },
  "music": { "bpm": 98, "duration": 30, "seeds": [7], "prompts": { "name": "…" },
             "bed": "cache/music/….wav", "bed_source": "which prompt and seed", "first_hit": 0.07 },
  "mix": { "fade": 0.3, "voice_only_lufs": -15, "with_music_lufs": -14, "bed_db": -8 },
  "sticker_band": { "deliverables": ["voice-only"], "allow": [[4.2, 4.3, "why: a full-frame transition"]] },
  "reel_safe": { "deliverables": ["reel"], "allow": [] },   // optional: default, every render named "…reel…"
  "renders": { "voice-only": "<composition id>", "reel": "…" }   // file name → composition id
}
```

`duration`, `version` and `renders` are required; compositions import `video.json` for their length
(`vertical(settings)`), so `mix.py` and the picture agree, and `gridOf(settings)` builds the beat grid from
`music.bpm` (brand.json's 98 without one). `bed` is relative to the media home. `sticker_band` names the Story
deliverables the band check applies to, and the spans (seconds) where a full-frame transition sweeps the background
through it. `reel_safe` names the Reel deliverables the Reel safe-zone check applies to (default: every render whose
name contains "reel") and spans to skip. Composition ids are `<video>-<deliverable>`, inside a `<Folder>` named after the video. Every composition
takes a `blur` prop (motion blur on or off; `render.py --draft` turns it off).

## The library (`src/kit.ts`)

**`lib/tokens`**: from `brand.json`: `FPS` 30, `WIDTH`×`HEIGHT` 1080×1920, `SAFE` {top 250, bottom 1580, side 80},
`STICKER_BAND` {top 0, bottom 250, margin 2}, `REEL_SAFE` {top 108, bottom 320, left 60, right 120} (px from each
edge), `TEXT_ZONE.story` / `.reel` (where words may go: x 80–1000 / 80–960, y 250–1580), `TITLE_BAND` {280, 520},
`DEFAULT_BPM` 98. Also `sec(s)`, colors `C`
(light theme "Fania de día"), `STRIPES`, `FONT` (Shrikhand, Bodoni Moda, Instrument Sans, emoji), and type presets
`TYPE.display(size, color?, shadow?)`, `TYPE.serif(size, color?)` (small optical size: hairlines survive H.264; never
digits), `TYPE.sans(size, color?)` (anything with numbers).

**`lib/motion`** (the rules in code):
- `SPRING`: `snap` (default entrance), `sheet`, `weight` (things that land), `pop` (stickers), `thumb` (scrolls),
  `whip`.
- `sp(frame, start, spring)` gives progress 0→1 with overshoot; `spv` is its speed (for squash and stretch).
- `rise(frame, start, {distance, exitAt})` is THE entrance (and exit) as a style. `leave(frame, at)` is an exit
  progress.
- `jit(seed)` gives irregular staggers of ±1–2 frames. `mix(a, b, k)` and `clamp` are helpers.
- `grid(bpm)` gives `BEAT`, `BAR`, `beats(from, to)` and `downbeats(from, to)`; `gridOf(settings)` takes the tempo
  from a video.json.
- `kick(t, times)` is a beat accent 0→1→0. `wobble(frame, times)` is a damped nudge (secondary action).
- `camera(t, from, to, {zoom, driftX, driftY})(depth)` is the slow push-in and drift with parallax by depth.

**`lib/scene`**:
- `<Scene start end pre post move name>` is a scene that overlaps its neighbors for transitions.
- `useScene()` gives `{frame, abs, t}`.
- `<FadeIn frames>` eases in from the paper; `<FadeOut frames>` fades out to it at the end. Stories: fade in, no
  fade-out (the owner, 5 Oct 2026): `VideoShell` does the fade-in and leaves the fade-out off.

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
start). **`lib/fonts`**: loads the faces from `media/fonts/` (`fontsReady` resolves when they're in);
`assets(video)(path)` is a `staticFile` in the home's `public/<video>/`.

**`brand/`**:

| Piece | What it is |
|---|---|
| `VideoShell`, `vertical(settings)` | the paper, the fade-in (no fade-out for Stories), the grain and the soundtrack around a video's scenes; a vertical `<Composition>`'s size, rate and length from its video.json |
| `EndCard`, `Cta`, `CTA_TOP`, `CTA_BOB` | the end card: "Link aquí arriba" with the `Arrow` right under the sticker band (story) or "Link en mi perfil" (reel), the stripes, the video's icon and record, the wordmark, a sign-off |
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
| `Arrow` | a drawn arrow (up, down, left, right) in the brand's ink weight, for calls to action that point at something |

**`data/events`**:
- `VideoEvent` and `EventsSnapshot` are the shape of `events.json`; show `day`/`day_start`, not `date`/`start_time`.
- `daysOf`, `between(events, from, to, styles)` and `weekend(today)` select events. **The weekend rule** (the same in
  `events.py` and `capture.mjs`, tested against one table): Friday to Sunday; Monday to Thursday the coming one,
  Friday to Sunday the one under way (on Sunday, the weekend ending today).
- `dateLabel`, `spanLabel`, `timeLabel` and `priceLabel` give the site's wording ("sábado 10 oct", "8:00 p. m.", "Desde
  $25.000").

## Videos

| Folder | What | Notes |
|---|---|---|
| [`teaser-v2`](projects/teaser-v2/) | The 21 s teaser of the site: voice, beat-cut scenes, a thumb driving the live site, three deliverables (Story ×2, Reel) | The worked example of everything. v2.3 (posted 4 Oct 2026, archived in the home) re-captured every screen with `capture.mjs`, rewritten for the site of 4 October (rhythm chips, pinned bar, details drawer), so it no longer matches the original project (`pa-bailar-teaser`) pixel for pixel. v2.4 (not posted) keeps the arrow and the opening title out of the sticker band |
| [`este-finde`](projects/este-finde/) | A 12 s weekly Story of the coming weekend's events, from data only, no voice | `events.py este-finde --weekend`, then `make.py este-finde` (`este-finde-story`). Example, not yet reviewed by the owner |

## Rules that bite

- Real material only: text, logos, dates and UI are code or real screenshots; flyers are the academies' own.
  Nothing AI-generated but the voice and the music.
- Owner decisions so far: the light theme; no URL on screen (Story: Instagram keeps a link sticker on for the whole
  clip, so the owner places it at the top, in the band above y 250 that nothing enters on any frame, and the end card
  says "Link aquí arriba" with a drawn up arrow, `Arrow` in the kit, never an emoji hand; Reel: "Link en mi perfil");
  Stories: fade in, no fade-out (the owner, 5 Oct 2026; the audio still ramps 0.3 s at both ends, against clicks);
  the Bodoni at `opsz` 18 / 600, never for digits.
- Screens and events date a video: post it before its shelf life ends (`app.json`, `events.json` and `screens.json`'s
  clocks record it; `render.py` warns past it).
- Gemini TTS times out at times: the tool retries, and a cached line never calls it again.
- Don't regenerate what exists: change a line's `take` for a new reading; keep the cache (in the media home).
