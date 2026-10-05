# Storyboard (v2)

21.0 s, 630 frames at 30 fps. Times are video seconds from `TIMING.json` (voice starts at 0.55 s); script,
voice and timing unchanged from v1. Tempo grid: 98 bpm, a beat every 0.612 s, a bar every 2.449 s. Scene
changes sit on beats (4.29 = beat 7, 6.12 = beat 10, 14.69 = beat 24 = bar 6, 17.14 = beat 28 = bar 7).

v2 changes (MOTION.md): the light theme "Fania de día" throughout (the owner's call), physical motion
(springs, weight, overlap, a camera that never stops), motivated transitions instead of hard cuts, the list and
the detail merged into one continuous phone shot driven by a thumb, the new multi-select "Ritmo ▾" menu, and
no URL on screen (an Instagram link sticker carries it).

| # | Time | Voice | Picture | Movement | Into the next |
|---|---|---|---|---|---|
| 1 | 0.00–4.29 | "¿Quieres salir a bailar este finde… y no sabes a dónde ir?" | Paper. "¿Quieres salir a bailar **este finde**?" (Shrikhand, wine; "este finde?" tomato), "¿Y no sabes a dónde ir?" (Bodoni italic). Real flyers of upcoming events land in a messy pile (the chosen rhythms on top). | Words spring up as they're said. Flyers tossed on arcs, one per beat (±1–2 frames), drop onto the table with a bounce, shadows tightening, nudging the pile. Push-in 6% with parallax. "este finde?" kicks on the downbeat (2.45). | An iris: a tomato disc grows out of the record's spot (8 frames, accelerating). |
| 2 | 4.29–6.12 | "Por eso hice Pa' Bailar." | The logo's tomato: the record, "Pa' Bailar" in cream with a wine offset shadow, the tagline. | The record drops in (`weight`) and spins up like a platter; letters land one by one from above on "Pa' Bailar"; tagline rises; the record kicks on the downbeat (4.90). | Whip pan up: leans down 22 px, then the whole cover flies up with blur and the phone scene arrives from below, overshooting a little. |
| 3 | 6.12–14.69 | "Miras qué hay hoy, este finde, la otra semana… a qué hora, dónde, cuánto vale y cómo llegar." | The live site in a phone, light theme. Above it, a period-heading title: "Salsa + Bachata" → "Hoy" → "Este finde" → "La otra semana" → "¿A qué hora?" → "¿Dónde?" → "¿Cuánto vale?" → "¿Cómo llegar?". | v2.3: a thumb taps the Salsa (6.50) and Bachata (6.82) chips in the bar (each turns dark, the list filters) and flicks to Hoy (7.28), Este fin de semana (8.16), Próxima semana (9.41): each flick glides with blur and settles a hair past, the bar pinned on top with "19 eventos · Salsa, Bachata". Taps "Detalles ›" on the first event of Próxima semana (10.86): the site's details drawer rises to half height (the list nudging so the card stays in view); a tomato frame pops onto the time (11.11); the thumb pulls the drawer up to full height (11.58) and the frame springs to Lugar, Precio, Cómo llegar. Titles build rule–word–rule and kick on downbeats (7.35, 9.80, 12.24). | Whip pan left with blur. |
| 4 | 14.69–17.14 | "No hay que registrarse, es gratis." | Paper, the stripes. "Sin **registro.**" and "Ni cuentas, ni contraseñas."; the round tomato sticker "Gratis · $0". | Words spring in with the voice; the sticker pops (`pop`) on "gratis" and sways on the beat; the texts fall away. | Match cut: the sticker squashes, launches up spinning, and arrives as the record. |
| 5 | 17.14–21.00 | "Te dejo el link… y nos vemos bailando." | v2.3: at the top, under the band where the owner keeps the Story's link sticker, "Link aquí arriba" with a drawn arrow up (Reel: "Link en mi perfil", no arrow); the stripes; the app icon (record on the tomato squircle); "Pa' Bailar" in tomato; "Nos vemos bailando.". | The record lands in place; the squircle pops behind it; letters land on "Te dejo…"; the call to action rises on "link" (17.86) and its arrow bobs up on every beat; sign-off on "nos" (18.6); the icon kicks on the downbeat (19.59); the record keeps spinning. | — (holds) |

## Deliverables

| File | Audio | End card |
|---|---|---|
| `out/teaser-v2/voice-only.mp4` | voice only, −15 LUFS | Story: "Link aquí arriba" ↑ |
| `out/teaser-v2/with-music.mp4` | voice + ACE-Step bed, ducked, −14 LUFS | Story: "Link aquí arriba" ↑ |
| `out/teaser-v2/reel.mp4` (Reel only) | voice + bed | Reel: "Link en mi perfil" |

## App footage

All from the live site (as deployed 4 Oct 2026, 13:10: light theme by default, multi-select menus, the card's
"Detalles · Compartir · Guardar" row and the half-height details sheet), captured by `capture.mjs` (see
its header): 360×640 CSS px at scale 3, light theme, a cache-busting query, clock frozen at Saturday 10 Oct
2026, 7 p.m. Bogotá (shelf life: post by that Saturday). The scenes read every position from
`data/app.json`, so a later re-capture (`node media/projects/teaser-v2/capture.mjs`, optionally `--now <a Saturday>`)
flows straight into a re-render.

## v2.1 (owner feedback)

- Sound: both soundtracks fade in over 0.3 s from true zero (DC removed with a 20 Hz high-pass) and fade out
  over the last 0.3 s; the voice starts at 0.55 s, so nothing of the first word is touched. Also fixed: the
  bed stopped at full level at 19.9 s (the ducking compressor ended with the voice); it now fades out to 21 s.
- Picture: eases in from the paper over the first 8 frames.
- Story end card (v2.3): "Link aquí arriba" under a drawn arrow pointing up at the link sticker, which the owner
  keeps at the top for the whole Story (above y 250, empty in every scene); the arrow bobs on the beat. The icon,
  wordmark and sign-off sit below it. The Reel-only file says "Link en mi perfil" in the same place, no arrow.
