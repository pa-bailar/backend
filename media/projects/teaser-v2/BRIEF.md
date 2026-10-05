# Brief: Pa' Bailar teaser

**What:** a ~21 s vertical teaser of the site itself, https://pa-bailar.github.io/: a free page that lists the
dance events of Bogotá (socials, workshops, festivals, congresses; salsa, bachata, kizomba…) collected from
the academies' Instagram posts.

**Goal:** someone who dances (or wants to) understands in one watch what the page is for, sees that it's real
and free, and taps the link.

**Audience:** dancers in Bogotá, 18–45, who follow academies and socials on Instagram and today piece the week
together from scattered posts. Spanish (Colombian, Bogotá register), informal "tú".

**Where:** an Instagram Story (with a link sticker added by the owner in Instagram) and a Reel. The Story will
most likely get licensed music from Instagram's Music sticker, so we deliver two files:

| File | Audio | Use |
|---|---|---|
| `out/teaser-v2/voice-only.mp4` | voice only, −16 to −14 LUFS, no long silences | Story, with Instagram's music under it and the link sticker ("Link aquí abajo 👇" on screen) |
| `out/teaser-v2/with-music.mp4` | voice + ACE-Step salsa bed, ducked | Story with our own music |
| `out/teaser-v2/reel.mp4` (Reel only) | voice + bed | Reel (no link stickers there): "Link en mi perfil" on screen |

No URL on screen (the owner's call, v2): the Story's link sticker carries it, with custom text like "Ver los
eventos"; the end card leaves y 1360–1580 empty for it.

**Specs:** 1080×1920, 30 fps, H.264 + AAC. Safe zones: keep text out of the top ~250 px (progress bar, account)
and the bottom ~340 px (reply bar, link sticker area, Reel caption), and ≥80 px from the sides.

**Voice:** Gemini TTS, voice "Achird", the relaxed "audio de WhatsApp a un amigo" direction the owner liked. First
person (the maker talking).

**Look:** 2D vector motion graphics in the site's own design system: the record logo, the 70s Fania stripes,
Shrikhand / Bodoni Moda italic / Instrument Sans, the light theme "Fania de día" (v2; v1 was Noche Fania), real screenshots of the live site and real
flyers of upcoming events. No 3D, no AI-generated people, text, logos or UI. An AI label for the voice is fine.

**Edit:** calm compositions, one deliberate movement per beat, scene changes on the beat of a typical salsa
tempo (98 bpm, a beat every 0.61 s), so the cut feels rhythmic with or without the baked-in track.

**Budget:** $0. Gemini free tier for the voice; ACE-Step 1.5, faster-whisper, Remotion and ffmpeg locally.

**Out of scope for v1:** the owner's link sticker and Instagram music (added in Instagram), English version,
captions file.
