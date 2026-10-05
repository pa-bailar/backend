---
name: teaser
description: Make or change a Pa' Bailar video (an Instagram Story or Reel about the site: a teaser, a weekly "este finde", an announcement) with the toolkit in the backend's media/ folder. Use it whenever the owner asks for a video, a new cut of one, or changes to its voice, music, screens or motion.
---

# Make a Pa' Bailar video

The toolkit lives in `pa-bailar/media/` (the backend repo). **Read `media/README.md` first**: it's the catalog of
the tools, the library's building blocks and the workflow, written so you don't need to read the code. Then read
`media/MOTION.md` (the motion rules the owner approved) and `media/DESIGN.md` (tokens, type, safe zones).

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
   transitions, blur on fast moves), and break one only on purpose.

## Before handing a cut over (the pre-post checklist)

- **Shelf life**: `render.py` warns when `app.json`'s `shelfLife`, `events.json`'s `to` or a screen's clock is past
  (`--strict` refuses). Say the date when you hand it over; re-capture or re-run `events.py` if it's close.
- **Sticker band**: `review.py band` (part of `make.py`'s sheet stage and `render.py --review`) passes on every Story
  deliverable: nothing above y 252 except the full-frame transitions `video.json` lists, each with its reason.
- **Loudness**: `mix.py` passed (true peak ≤ −1 dBTP, within 1 LU of −15 voice-only / −14 with music / −16 music
  only); `mix.py <video> --check` measures what's there.
- **Version**: the render's name carries the `version` you'll report, and the previous one is there to compare.
- **Type**: digits (dates, times, prices, counts) in the sans, never the Bodoni italic (its 4 reads as a 1).

## Rules

- Real material only: screens of the live site, the academies' own flyers, the site's data. Only the voice
  (Gemini TTS, free tier) and the music (ACE-Step, local) are generated. $0: no paid APIs.
- The owner's decisions: the light theme; no URL on screen (Story: Instagram keeps a link sticker on for the whole
  clip, so the owner places it at the top, in the band above y 250 that nothing enters on any frame, and the end card
  says "Link aquí arriba" with a drawn up arrow, `Arrow` in the kit, never an emoji hand; Reel: "Link en mi perfil");
  Stories: fade in, no fade-out (the owner, 5 Oct 2026; the audio still ramps 0.3 s at both ends, against clicks);
  no digits in the Bodoni italic; Spanish (Bogotá, informal "tú") on screen and in the voice.
- Screens and events date a video: say its shelf life when you hand it over.
- Never print `.env` or keys. The TTS tool reads `MEDIA_GEMINI_API_KEY` itself; `make.py doctor` only says whether
  it's set.
- Generated files live in the media home (`D:\AI\pa-bailar-media`, or `PA_BAILAR_MEDIA_HOME`): the TTS and music
  cache, `public/<video>/`, renders and the archive. Working in a git worktree is fine: every checkout shares the
  home, and removing a worktree can't delete it.
- Old renders pile up: after the owner settles on a version, run `media/tools/clean.py` (a list), then `--yes`
  (the Recycle Bin, restorable). Site checks go in a scratch folder, not in `media/out/`.
- Renders, the cache and `public/<video>/` aren't committed. Commit the folder's code, `video.json`, `data/*.json`
  and the notes. Changes go through a branch and a PR like any backend change (the docs sync runs before the PR).
