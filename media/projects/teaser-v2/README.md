# Teaser v2

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

From the backend root (the cache already holds the six voice lines and music option 1):

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
**Before posting a new cut, re-capture**: the site's filter bar changed on 4 October (rhythm chips and a "Cuándo"
menu replaced "Ritmo ▾"), so `capture.mjs` section 2 and the matching beats in `scenes/App.tsx` (`TAP_STYLE`,
`TAPS`, `CLOSE`, the menu crops) need updating first.
