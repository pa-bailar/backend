# Puente festivo

The long weekend of 9–12 Oct 2026 (Monday 12 a holiday, a "puente"), as a 23 s Story and Reel. Started 8 Oct 2026
with `tools/new.py`.

- **Goal:** that someone thinking of staying home this puente opens Pa' Bailar ("Puente festivo… ¿y tú en la
  casa?"), then the link.
- **Audience:** the owner's Instagram, as a Story (link sticker at the top) and a Reel ("Te dejo el link", "Link en
  mi perfil"), posted Thursday 8 or Friday 9 Oct.
- **The idea:** the site's three stripes draw a bridge over VIE · SÁB · DOM · LUN (festivo). It becomes the header
  while a record crosses it day by day; under it, the six events the owner chose land as she names them; then the
  rest of the weekend riffles in ("+25 planes más") and the bridge comes down into the end card.
- **The owner's picks:** the events (Párchese la Salsa; Tardeo Latino, the LuDance anniversary, Social pa'l Parche;
  ¡Viva Salsa!, El Golazo de Bulevar), the hook, the bridge, the voice (Despina, one take: `../../AUDIO.md`) and
  the music (Pixabay's "Latin Salsa Music" by Tunetank, from 0:09.85).
- **Material:** `data/events.json` (`tools/events.py puente --from 2026-10-09 --to 2026-10-11`), the flyers and two
  clips (Tardeo Latino, El Golazo) in the media home's `public/puente/`.
- **Shelf life:** Sunday 11 Oct 2026. Re-run `events.py` before posting if a sweep changed a time or the count.

## Versions

- **v1:** no voice, 21.2 s on an 8-bar grid. The "festivo" tag came too late, and the bridge sat over the first
  flyer.
- **v2:** Despina line by line, with the day names while she says them. Too robotic.
- **v3:** Despina's one take with a Spanish Bogotá direction; the sections follow her pauses.
- **v4–v5:** a Story only; the music up 6 dB (too loud), then 3 dB (`bed_db` −11).
- **v6:** the link sticker's band under Instagram's account row (y 250–460), the content fitted below it (the kit's
  Story fit).

## Make

From the backend root: `.venv/Scripts/python media/tools/make.py puente --draft`, then `make.py puente` for the
owner (render, keyframe sheet, sticker-band check, side-by-side with the previous version). Bump `version` in
`video.json` for each cut the owner sees.
