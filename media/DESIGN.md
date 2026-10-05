# Design (video)

The video borrows the site's design system (`pa-bailar-web/docs/DESIGN.md`, `frontend/src/styles/tokens.css`)
and adds only what motion needs. The canvas, the safe zones, the sticker band, the title band, the default tempo
and the loudness targets live in `brand.json` (read by `src/lib/tokens.ts` and the Python tools); colors and type
presets (`TYPE.display/serif/sans`) in `src/lib/tokens.ts`.
Scene numbers below are teaser v2's (`projects/teaser-v2`), as examples.

## Canvas

- 1080×1920, 30 fps. The site's screenshots are 360×640 CSS px at scale 3, so 1 CSS px = 3 video px.
- **Safe zones:** no text above y = 250 or below y = 1580 (1920 − 340), nor closer than 80 px to the sides.
  Images (the phone, flyers) may run into the zones; words never do.
- **Sticker band (Stories):** the owner puts Instagram's link sticker at the top, over y 0–250, for the whole clip,
  so nothing enters it on any frame, image or word (`STICKER_BAND`; `review.py band` allows nothing above y 252,
  except the spans a video.json lists for full-frame transitions). Mind the camera: a 3% push-in at depth 0.6 lifts
  something at y 276 to about y 256, so page heads start at y 276 or lower.
- **Reel safe zones:** a Reel's UI covers other margins than a Story's: 108 px at the top (the header), 320 at the
  bottom (the caption, the audio line), 60 on the left and 120 on the right (the like, comment and share column)
  (`REEL_SAFE`). Words stay inside both: x 80–960, y 250–1580 on a Reel (`TEXT_ZONE.reel`). `review.py reel` warns
  about content in those margins (images may run into them). The teaser's end card (v2.4) reaches x 1000 with the
  wordmark and the stripes: inside the right column on the Reel.
- **Title band:** scene titles sit at y 280–520, the same place in every scene, so the eye never hunts.

## Colors (v2: "Fania de día", the site's light theme, plus the logo's tomato for the cover)

The owner prefers the light theme (and the dark one is being redesigned), so v2 is paper and ink. Contrast on
the paper (`#ecddc6`): wine 13:1, wine-500 italic 7.7:1, tomato-700 4.9:1, tomato-600 4.0:1 (large display
type only, ≥3:1 for AA large); cream-50 on tomato 4.9:1.

| Token | Value | Use |
|---|---|---|
| `paper` | `#ecddc6` | Background of scenes 1, 3–5 (the site's `--bg` in light, cream-150) |
| `cream300` | `#d9c6aa` | Soft offset shadow of titles (`--period-shadow`) |
| `wine900` | `#2a0f14` | Main text (`--text`), flyer borders, the sticker and icon offset shadows |
| `wine500` | `#6e2a33` | Bodoni italic lines (`--text-italic`) |
| `tomato700` | `#b02a17` | Period-style titles (`--period-title`) |
| `tomato600` | `#c8321c` | The cover, the app icon, the "Gratis" sticker (`--sticker-bg`), accents, the highlight frame |
| `cream50` | `#fff8ec` | Text on tomato |
| `marigold400` | `#f2c12e` | The record label |
| `wine950` | `#1e0a0e` | The record's black |
| stripes | `#c8321c`, `#e8791c`, `#e9b021` | `--stripe-1..3` in light |

## Type

| Face | Use | Size at 1080 wide |
|---|---|---|
| Shrikhand | Titles, wordmark, the sticker | 112–168 px (wordmark 168) |
| Bodoni Moda italic 600, `opsz` 18 | The second line of a thought, tagline, sign-off; never digits (its italic 4 reads as a 1) | 64–76 px |
| Instrument Sans 600 | The end card's call to action (no URL on screen), and anything with digits (dates, times, prices, counts) | 30–68 px |

Fonts are the Google Fonts files (OFL) in `fonts/`, bundled with the code (imports, not the public folder). Titles get the period-heading treatment
from the site: a 6 px offset shadow in `cream300` (the site's 2 px × 3).

## Motion

v2's rules, with the research behind them, are in `MOTION.md` and in code in `src/lib/motion.ts`. In short:
one entrance ("rise") on a `snap` spring with a little overshoot, exits accelerating out; springs with weight
for flyers, the record and the sticker; kinetic type word by word with the voice; irregular staggers; a slow
camera push-in and parallax on every scene; beat accents on downbeats only; motivated transitions (iris,
whips, a match cut, one continuous phone shot) instead of hard cuts; motion blur on fast moves.

## The record (the motif)

The site's icon (`frontend/src/pages/icons/[name].png.ts`): a near-black record (`#1E0A0E`) with four faint
grooves (white 7%), a marigold label at 42% of the radius and a wine spindle hole at 10%. Drawn in SVG by code.
It spins up like a platter and turns at 33⅓ rpm (200°/s) wherever it appears (2, 5), with a fixed highlight (a soft
white sheen that doesn't turn) so the turning reads.

## Start and end

- **Stories: fade in, no fade-out (the owner, 5 Oct 2026).** `VideoShell` (`src/brand/shell.tsx`) puts every video on the paper with an 8-frame fade-in from it, the
  grain and the soundtrack; its `fadeOut` is off by default and stays off for Stories. The audio ramps 0.3 s in and
  out (`mix.py`'s "fade"), only so it never clicks.
- **The end card** is the kit's `EndCard` (`src/brand/end.tsx`): "Link aquí arriba" with the drawn `Arrow` right under
  the sticker band (`CTA_TOP` = 276, bobbing `CTA_BOB` = 14 px) for a Story, "Link en mi perfil" for a Reel; the
  stripes at y 500; the app icon and the record around a spot (the video brings its own: a match cut, a pop); the
  wordmark 300 px below it and an optional sign-off 490 px below.

## Texture

- **Grain:** an SVG fractal-noise layer multiplied over everything (paper texture), 10% opacity, its seed changing every 2 frames (a 15 fps
  shimmer like offset print and film, not TV static).
- **Stripes:** only at the top of scenes 4 and 5 (as in the site: page heads), drawn by code, each band wiping
  in from the left on a spring, staggered.
- No gradients, glows, lens flares or 3D.

## Real material only

Text, logos, dates and UI are drawn by code or are real screenshots of the live site. Flyers are the academies'
own (downloaded from the site's data by `tools/events.py`, or by a video's own capture script), shown whole (never cropped), as the site does. Nothing is AI-generated except the voice
(and the optional music bed).
