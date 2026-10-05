# Teaser v2 (v2.3)

The 21 s teaser of the site for an Instagram Story and a Reel. Made 3–4 October 2026 in its own project
(`C:\Users\Jhoan\Code\pa-bailar-teaser`, local git, kept as the archive with v1, v2.1 and v2.2 renders) and moved
here as the toolkit's worked example. It renders pixel-identical to v2.2's code.

- [BRIEF.md](BRIEF.md): goal, audience, deliverables, specs.
- [SCRIPT.md](SCRIPT.md): the lines and why (opening A was picked).
- [STORYBOARD.md](STORYBOARD.md): scene by scene on the 98 bpm grid.
- The motion rules it set: [../../MOTION.md](../../MOTION.md).

| File | What |
|---|---|
| `video.json` | the voice lines, music prompts and bed, mix levels, deliverables |
| `theme.ts` | this video's clock: voice timing, the beat grid, the scene cuts |
| `Teaser.tsx` | the five scenes, the transitions, blur windows, the three compositions |
| `scenes/` | `Question` (flyers tossed), `Cover` (iris, record, wordmark), `App` (the phone walk), `Free` (the sticker), `End` |
| `capture.mjs` | the scripted walk through the live site → `public/teaser-v2/app/` and `data/app.json` |
| `data/` | `timing.json` (from `tools/timing.py`), `app.json` (from `capture.mjs`) |

## Rebuild

From the backend root. On the PC it was made on, `media/cache/` holds the six voice lines and music option 1 (the
cache isn't committed: elsewhere, copy them from `pa-bailar-teaser/out/voice/lines/` and `out/music/option-1.wav`,
or `tts.py` makes new takes):

```bash
.venv/Scripts/python media/tools/tts.py teaser-v2
```

```bash
D:/AI/whisper/.venv/Scripts/python media/tools/timing.py teaser-v2
```

```bash
.venv/Scripts/python media/tools/mix.py teaser-v2
```

```bash
.venv/Scripts/python media/tools/render.py teaser-v2
```

The screens in `public/teaser-v2/app/` were copied from the archive (captured 4 October for Saturday 10 October).
**v2.3 (4 October 2026):** same script, voice and music, every screen and flyer re-captured from the live site for
Saturday 10 October (`capture.mjs` rewritten for the site of that day: the rhythm chips, the pinned bar with its
"N eventos" line, the details drawer at half then full height). Scene 3 follows: the thumb taps the chips (no menu),
the bar stays pinned, the list nudges as the drawer rises (as the site keeps the tapped card in view), and the frame
visits the time on the half drawer, then Lugar, Precio and "Cómo llegar" on the full one. Renders:
`pa-bailar-teaser/out/teaser-v2.3-{voice-only,with-music,reel}.mp4`. Shelf life: Saturday 10 October.

When the site changes again, re-run `capture.mjs` first; if it fails, fix its hooks (it names each) and the matching
beats at the top of `scenes/App.tsx`.
