---
name: teaser
description: Make or change a Pa' Bailar video (an Instagram Story or Reel about the site: a teaser, a weekly "este finde", an announcement) with the toolkit in the backend's media/ folder. Use it whenever the owner asks for a video, a new cut of one, or changes to its voice, music, screens or motion.
---

# Make a Pa' Bailar video

The toolkit lives in `pa-bailar/media/` (the backend repo). **Read `media/README.md` first**: it's the catalog of
the tools, the library's building blocks and the workflow, written so you don't need to read the code. Then read
`media/MOTION.md` (the motion rules the owner approved), `media/DESIGN.md` (tokens, type, safe zones) and
`media/AUDIO.md` (the voice and the music: record the script in one take, direct it in Spanish, structured,
with the city's accent; the owner picks the voice and the track by ear).

## How to work

1. **Start from the owner's direction**: what the video is for, where it's posted, by when. Ask only for
   creative direction. Decide the mechanics yourself and report afterwards.
2. **Make a folder** with `media/tools/new.py <video>` (a README for the brief, `video.json` with `version` "1", a
   composition on `VideoShell` and `EndCard` that already renders, its line in `media/src/Root.tsx`). Build from
   `src/kit.ts`. Reuse a piece before writing a new one. When something new is clearly reusable (a component, a
   transition), add it to `src/brand/` or `src/lib/`, and add a line to the catalog.
3. **Stage by stage**, each leaving a file: script → `tools/tts.py` → `tools/timing.py` → (music: `tools/music.py`,
   `tools/analyze.py`) → `tools/mix.py` → material (`tools/capture.mjs`, `tools/events.py`) → storyboard →
   composition. The animation follows the voice's timing, and cuts land on the beat grid. `tools/make.py <video>`
   runs tts → timing → mix → render → sheet, only what's stale, each with the right Python (`make.py doctor` first
   on a new machine).
4. **Look before you show**: `tools/stills.mjs <video> --at 1.5,c4:link` (seconds, frames, words), then
   `make.py <video> --draft`, then `make.py <video>` for the owner: a full render, its keyframe sheet, the
   sticker-band check and a side-by-side with the previous version. Check the safe zones, the text and the first
   frame. They review on the phone.
5. **Version every cut the owner sees**: bump `version` in `video.json` (renders are
   `<video>-v<version>-<deliverable>.mp4`; `out/<video>/<deliverable>.mp4` links the newest), so the last one stays to
   compare with. When one is posted, archive it in the media home (`archive/<video>/v<version>/`: renders, `public/`,
   project files), as teaser v2.3.
6. **Keep the format free.** No fixed template: every video can differ in length, structure and pieces. Follow the
   motion rules (springs, irregular staggers, a camera that never stops, accents on downbeats only, motivated
   transitions, blur on fast moves), and break one only on purpose. Keep to MOTION.md's motion vocabulary: a few
   kinds of motion, one thing moving at a time per region, nothing moving for its own sake (too many moving parts
   is what makes AI-made videos look AI-made).

## Before handing a cut over (the pre-post checklist)

- **Shelf life**: `render.py` warns when `app.json`'s `shelfLife`, `events.json`'s `to` or a screen's clock is past
  (`--strict` refuses). Say the date when you hand it over; re-capture or re-run `events.py` if it's close.
- **Sticker band**: `review.py band` (part of `make.py`'s sheet stage and `render.py --review`) passes on every Story
  deliverable: nothing above y 462 (Instagram's top row and the sticker's band under it) except the full-frame
  transitions `video.json` lists, each with its reason. A Story's `VideoShell` takes `story` (the fit that puts the
  content under the band).
- **Instagram pre-flight**: `preflight.py` (part of `render.py --review`) passes on every deliverable you hand over
  (codec, 9:16, fps, bitrate, length, size). A half-size draft only warns; hand over full renders. For the API (a
  Reel ≤300 MB, a Story ≤100 MB and 3–60 s: Meta's IG User Media reference), run it with `--api`.
- **Instagram practices** (`media/README.md` → "Instagram practices", with sources): a hook in the first 1.5–3 s (the
  question or the promise, not the logo); a Reel's length fits its goal (7–15 s reach, 15–30 s explain; past 3 min
  Instagram stops recommending it, and `preflight.py` warns); captions for silent viewers when the owner wants them;
  a Story frame about 10–15 s, one clear call to action, the link sticker where the eye lands after the message and
  never under Instagram's UI (our band at the top, "Link aquí arriba"); the Reel's cover 9:16 with its words inside
  the centered 3:4 grid crop; our own audio and picture, never a watermarked repost.
- **Posting**: the owner posts by hand. `media/tools/publish.py` (the Graph API) exists but is disabled
  (`media/README.md` → "Publishing (disabled)"); never enable it, add `--confirm` or touch the Meta app yourself. A
  dry run (`publish.py <video> <deliverable>`) is fine: it calls nothing and shows the requests. Stories with a link
  sticker always stay manual (the API can't add stickers).
- **Reel safe zones**: `review.py reel` (part of `render.py --review` for Reel deliverables) lists content in the
  margins the Reel's UI covers (108 top, 320 bottom, 60 left, 120 right). Images may run into them; check that no
  word does (the sheet draws them in magenta). The end card takes `cta="reel"` for its Reel layout (`REEL_END`).
- **Reel cover**: for a Reel, `cover.py <video> --at <moment>` exports the cover (1080×1920) and the profile grid's
  centered crop; pick a frame whose words survive the crop and sit outside the Reel's margins, and hand both over.
- **Loudness**: `mix.py` passed (true peak ≤ −1 dBTP, within 1 LU of −15 voice-only / −14 with music / −16 music
  only); `mix.py <video> --check` measures what's there.
- **Phone speaker** (a voice with music): `mix.py` prints voice over music as a phone plays it (mono, 300 Hz–6 kHz)
  in the voice band; no warning means at least +10 dB and under 10% of the speech masked. A warning: lower `bed_db`.
- **Refactors and encodes**: after a change that shouldn't move a pixel, `review.py diff <old> <new>` must say every
  frame is identical (PSNR ∞). To judge an encode (Instagram's copy, a smaller file), read its VMAF (~6 points is one
  just-noticeable difference) and its worst frames.
- **Music provenance**: a video with a generated bed records it in `video.json`'s `music.provenance` (model,
  revision, prompt, seed, reference audio, date; `music.py` leaves a `.json` next to each bed to copy in). `mix.py`
  and `render.py` warn without it; use `make.py <video> --strict` for anything you hand over to post.
- **Version**: the render's name carries the `version` you'll report, and the previous one is there to compare.
- **Type**: digits (dates, times, prices, counts) in the sans, never the Bodoni italic (its 4 reads as a 1).
- **Captions** (when the owner wants them; off by default): `"captions": {"style": "minimal" | "kinetic", …}` in
  `video.json` and `<Captions video={settings} timing={timingJson} format={cta} />` after the scenes. Look at stills
  (`stills.mjs --at c2:vale`): no line twice (skip with `lines` the ones the picture writes out), nothing they cover
  that matters, inside the safe zones of each deliverable.

## Rules

- Real material only: screens of the live site, the academies' own flyers, the site's data. Only the voice
  (Gemini TTS, free tier) and the music (ACE-Step, local) are generated. $0: no paid APIs.
- The owner's decisions: the light theme; no URL on screen (Story: Instagram keeps a link sticker on for the whole
  clip, so the owner places it right under Instagram's own top row (the account's name), in y 250–460, which nothing
  enters on any frame (the Story fit moves the content below it), and the end card
  says "Link aquí arriba" with a drawn up arrow, `Arrow` in the kit, never an emoji hand; Reel: "Link en mi perfil");
  Stories: fade in, no fade-out (the owner, 5 Oct 2026; the audio still ramps 0.3 s at both ends, against clicks);
  no digits in the Bodoni italic; Spanish (Bogotá, informal "tú") on screen and in the voice.
- Screens and events date a video: say its shelf life when you hand it over.
- Never print `.env` or keys. The TTS tool reads `MEDIA_GEMINI_API_KEY` itself; `make.py doctor` only says whether
  it's set.
- Generated files live in the media home (`D:\AI\pa-bailar-media`, or `PA_BAILAR_MEDIA_HOME`): the TTS and music
  cache, `public/<video>/`, renders and the archive. Working in a git worktree is fine: every checkout shares the
  home, and removing a worktree can't delete it.
- **Clean up before ending any video session** (the `media-clean` skill): when the owner approves a cut, a voice or a
  track, and at the end. `media/tools/clean.py` lists old versions, sheets, stills, auditions and the takes and
  tracks no video uses; `--yes` sends them to the Recycle Bin. Leaving versions behind is what the owner asked to
  stop (8 Oct 2026). Site checks go in a scratch folder, not in `media/out/`.
- Renders, the cache and `public/<video>/` aren't committed. Commit the folder's code, `video.json`, `data/*.json`
  and the notes. Changes go through a branch and a PR like any backend change (the docs sync runs before the PR).
