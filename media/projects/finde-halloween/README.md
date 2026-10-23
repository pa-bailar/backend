# Este finde, Halloween

The socials of the weekend of 23–25 Oct 2026 (all five on Saturday 24), as a 23 s Story with an October / Halloween
look. Started 22 Oct 2026 with `tools/new.py`; the first weekly "este finde" Story with a voice.

- **Goal:** that someone planning their Saturday opens Pa' Bailar ("¿Y ya tienes disfraz pa'l sábado?"), then the
  link.
- **Audience:** the owner's Instagram, as a Story (link sticker under the account row), posted Thursday 22 or
  Friday 23 Oct.
- **The idea:** Saturday from the afternoon into the night. The hook on the paper, with the record dressed as a
  jack-o'-lantern (it has its costume); "Sábado de tarde" and Tardeo de Muertos; on "En la noche" the paper darkens to
  the record's black, three bats cross the head once and "de tarde" becomes "de noche"; the two Halloween socials;
  "¿Sin disfraz?" and the two others; the end card stays at night (the kit's `EndCard` with `ink`). The night breaks
  the light-theme rule on purpose (the owner asked for a Halloween theme; the flyers are black and orange).
- **The socials:** every `social` of the snapshot, in the order she names them: Tardeo de Muertos (Bogotá Dance
  Club), the costume contest at Show Stars, Bembé's Social de Halloween, Salsa en Digital (siga.bog), Latinholic Night
  (Danceholic).
- **Voice:** Despina, one take (`../../AUDIO.md`), the direction adapted to a Halloween Saturday.
- **Music:** puente's track for now (Pixabay's "Latin Salsa Music" by Tunetank, from 0:09.85), `bed_db` −11 as the
  owner chose for puente; the phone-speaker check warns (31% masked), so −14 is the fallback if the voice gets lost.
- **Material:** `data/events.json` (`tools/events.py finde-halloween --weekend 2026-10-22`), the flyers in the media
  home's `public/finde-halloween/`. No screens of the site.
- **Shelf life:** Saturday 24 Oct 2026. Re-run `events.py` before posting if a sweep changed a time or a price.

## Versions

- **v1:** the first cut, approved by the owner (22 Oct 2026) and archived in the media home
  (`archive/finde-halloween/v1/`). Then the owner's notes: "Pa' Bailar" sounded odd (Whisper heard "pabellar"), it
  felt slow, it showed only 5 of the weekend's 32 events, and wanted more Halloween and more excitement.
- **v2:** 18 s instead of 23. A livelier one take (the direction asks for excitement at a normal pace, and says how
  "Pa' Bailar" is said; three takes, the one Whisper heard cleanest), night from the first frame, lightning on the
  open and on "¡Halloween!", cobwebs, a full moon with bats crossing it, the pumpkin's face flickering like a candle;
  Saturday's three Halloween socials, then the other flyers piling in while the count climbs to the real 32.
- **v3:** the owner on v2: the main socials must still be named. Back in the voice and on screen: a whip to
  "¿Sin disfraz?" with Salsa en Digital and Latinholic Night (flyer and facts each), then the pile and the count.
  21 s; a new take (three recorded, the cleanest kept). The phone-speaker check warns again with this take (32%
  masked at −11 dB, as v1).
- **v4:** the owner on v3: "sin disfraz" claims something the data doesn't say about those two events, and parts of
  the voice felt disconnected. It was one take already (the script in one request, only trimmed at its ends); the
  seams were the reading (the direction asked for short pauses between phrases) and the music swelling back in every
  pause (the ducking's 350 ms release). Now "Y más sociales: …" on screen and in the voice, a direction for connected
  phrases (three takes; the one with the shortest pauses kept, 17.2 s), and `mix.release` 900 ms, which holds the bed
  down through her pauses (and the phone check passes: +21.5 dB, 2% masked). 19.5 s.
- **v5:** the owner on v4: the music takes a while to be heard. The bed, set for under the voice, measured −30 LUFS
  alone against −14 with her, and she spoke from 0.15 s. Now the voice starts at 0.7 s (`lead`), so the band hits
  alone on the opening lightning, at `mix.intro_db` +4 dB (−18 LUFS), ramping down to `bed_db` (now −9) just
  before her first word. Phone check: +19.4 dB, 8% masked. 20 s.
- **v6:** the owner on v5: a click at the start, and no flashing at the start. The click was the take's: Gemini left
  a full-scale 5 ms burst at its first sample and Whisper put her first word at 0.0 s, so the cut kept it (since v4);
  `timing.py` now opens a one take on 20 ms of silence and a fade-in. The mix's intermediates are float too (v5's loud
  opening reached 0 dBFS in a 16-bit file). The opening lightning is gone; it strikes once, on "¡Halloween!".

## Make

From the backend root: `.venv/Scripts/python media/tools/make.py finde-halloween --draft`, then `make.py
finde-halloween --strict` for the owner. Bump `version` in `video.json` for each cut the owner sees.
