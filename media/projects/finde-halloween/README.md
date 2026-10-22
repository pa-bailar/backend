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

- **v1:** the first cut.

## Make

From the backend root: `.venv/Scripts/python media/tools/make.py finde-halloween --draft`, then `make.py
finde-halloween --strict` for the owner. Bump `version` in `video.json` for each cut the owner sees.
