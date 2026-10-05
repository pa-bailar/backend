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
**Before posting a new cut, re-capture, after rewriting `capture.mjs`**: the site changed on 4 October and every
section of it breaks (a toolkit review checked each against the site):
- §1–2: `#jump-style` and its "Ritmo ▾" checklist (`#jump-style-menu`, `.bar-menu__*`, `#jump-style-label`) are gone:
  tap the rhythm chips (`#jump-chips [data-filter="styles"][data-value="salsa"]`, `aria-pressed`); the summary line is
  `#jump-summary`; "Cuándo" is `#when-open` and `#when-menu [data-when=…]`. Cards' accounts are `[data-profile]`, not
  `[data-account]` (the pile's one-flyer-per-account rule depends on it).
- §3: the bar no longer hides on scroll and `#jump-period-label` is gone: one bar capture; drop the bar-hiding logic
  in `scenes/App.tsx` (MOTION.md rule 12 describes the old bar).
- §4: the details are a drawer now: `.event-dialog__info` → `.event-detail__info`, `.viewer-panel` → `.drawer__panel`,
  `.viewer-bar` → `.drawer__head`, `.event-dialog__when` → `.event-detail__when`; the quick actions are Instagram ·
  Compartir · Guardar ("Cómo llegar" is in the Lugar row). Check the drawer's scroller in a browser.
- Then `scenes/App.tsx`: `TAP_STYLE`, `TAPS`, `CLOSE`, the menu crops and the half/full sheet model follow.
