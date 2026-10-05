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
2. **Make a folder** `media/projects/<video>/`: a README with the brief, `video.json`, then the composition
   (`<Name>.tsx`, `scenes/`) and one line in `media/src/Root.tsx`. Build from `src/kit.ts`. Reuse a piece before
   writing a new one. When something new is clearly reusable (a component, a transition), add it to `src/brand/`
   or `src/lib/`, and add a line to the catalog.
3. **Stage by stage**, each leaving a file: script → `tools/tts.py` → `tools/timing.py` → (music: `tools/music.py`,
   `tools/analyze.py`) → `tools/mix.py` → material (`tools/capture.mjs`, `tools/events.py`) → storyboard →
   composition. The animation follows the voice's timing, and cuts land on the beat grid.
4. **Look before you show**: `tools/render.py <video> --frames …`, then `--draft`, then
   `tools/review.py sheet`. Check the safe zones, the text and the first frame. Show the owner a full render plus
   `review.py compare` against the last version. They review on the phone.
5. **Keep the format free.** No fixed template: every video can differ in length, structure and pieces. Follow the
   motion rules (springs, irregular staggers, a camera that never stops, accents on downbeats only, motivated
   transitions, blur on fast moves), and break one only on purpose.

## Rules

- Real material only: screens of the live site, the academies' own flyers, the site's data. Only the voice
  (Gemini TTS, free tier) and the music (ACE-Step, local) are generated. $0: no paid APIs.
- The owner's decisions: the light theme, no URL on screen (Story: Instagram keeps a link sticker on for the whole clip, so the owner
  places it at the top, in the band above y 250 that every scene leaves empty, and the end card says "Link aquí
  arriba" with a drawn up arrow, `Arrow` in the kit, never an emoji hand; Reel: "Link en mi perfil"), fade audio and picture in and out, Spanish (Bogotá, informal "tú") on screen
  and in the voice.
- Screens and events date a video: say its shelf life when you hand it over.
- Never print `.env` or keys. The TTS tool reads `MEDIA_GEMINI_API_KEY` itself.
- Old renders pile up: after the owner settles on a version, run `media/tools/clean.py` (a list), then `--yes`
  (the Recycle Bin, restorable).
- Renders, the cache and `public/<video>/` aren't committed. Commit the folder's code, `video.json`, `data/*.json`
  and the notes. Changes go through a branch and a PR like any backend change (the docs sync runs before the PR).
