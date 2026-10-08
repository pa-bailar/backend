# Audio: the voice and the music

What we learned getting a voice and a track the owner approves, so the next video starts from it. The tools are in
the catalog (`README.md`); this is how to use them well. Each rule names where it came from.

## The voice (Gemini TTS, free tier)

The owner's bar: **it must not sound AI** (the puente teaser, 8 Oct 2026: line-by-line takes were "too robotic",
the first one-take had "an American accent" and "sped up"; the fourth was "great").

1. **Record the whole script in one take** (`"voice"."one_take": true` in `video.json`). Recorded line by line, every
   line restarts its intonation: six separate readings, which is what sounds robotic. In one take she carries the
   momentum from phrase to phrase. `tools/tts.py` sends the whole script in one request; `tools/timing.py` cuts it
   from just before the first word to just after the last and finds each line by its first two words (Whisper, with
   the script as a hint so names come out as written). The video's sections then follow her pauses: put each on the
   beat at or just before its line (`beatAt(line(id).start)`), not on a fixed grid with gaps.
2. **Write the direction in Spanish, structured** as Google's TTS prompting guide does: a profile, the scene, the
   director's notes, then the transcript. In English, the model drifted to an American accent; unstructured, the
   newer model (`gemini-3.8-flash-tts`) read the direction aloud before the script. The approved one:

   ```
   # PERFIL DE AUDIO: Valentina, 25 años, rola, nacida y criada en Bogotá.
   ## LA ESCENA: Le manda una nota de voz por WhatsApp a una amiga para contarle los planes de baile del puente
   festivo en Bogotá. Está tranquila, en su casa.
   ### NOTAS DE DIRECCIÓN: Acento colombiano de Bogotá, español colombiano natural; nada de acento gringo, mexicano
   ni de España. Habla como en una nota de voz de verdad, no como si estuviera leyendo: con una sonrisa en la voz,
   relajada y sin afán, un poquito más despacio que una conversación normal, con pausas naturales entre frases para
   respirar. Nada de locutora ni de comercial. Lee exactamente la transcripción, sin agregar palabras.
   #### TRANSCRIPCIÓN:
   ```

   The script follows it. Adapt the scene to the video; keep the accent, the pace and the last two sentences.
3. **The accent: name the city and the person, and rule out the others** ("rola, nacida y criada en Bogotá"; "nada
   de acento gringo, mexicano ni de España").
4. **The pace: ask for relaxed.** "Rápida y animada" came out sped up (16.6 s for a 20 s script); "relajada y sin
   afán, un poquito más despacio que una conversación normal" gave 19.8 s and sounded natural.
5. **"Lee exactamente la transcripción, sin agregar palabras."** A take added a word ("Todo **va** en Pa' Bailar").
6. **The voice:** Despina (the owner's pick, 8 Oct 2026, over Laomedeia, Aoede, Callirrhoe, Sulafat and Leda; all
   six read the same lines with the same direction, `tts.py --audition … --voices …`). The male voice of teaser v2:
   Achird. Audition a handful before choosing; the owner judges by ear.
7. **Check every take before showing it:** `timing.py --transcribe <wav>` (what Whisper hears: a swallowed or added
   word shows up). Then the owner listens: the accent, the pace, the end. Send samples as MP3 (`ffmpeg -b:a 160k`).
8. **The model can leave noise after the last word:** the approved take clipped (34 samples at 0 dBFS) right after
   "link". `timing.py`'s one-take cut ends 0.12 s after the last word, with a fade; for a sample sent by hand, cut
   there too.
9. **Keep an approved take; never re-record it.** TTS isn't deterministic: the same prompt reads differently each
   time. An approved audition (`out/auditions/<voice>-<key>.wav`) is copied to the cache under the video's key
   (`one_take_path` in `tools/common.py`, the same script, voice and direction), so `tts.py` finds it cached.
10. **Quotas and models:** `gemini-2.5-flash-preview-tts` has a small free daily quota (it ran out after about 15
    requests on 8 Oct 2026); `tts.py` then falls back to `gemini-3.8-flash-tts`, which works with the structured
    direction (rule 2). A take that comes out far too long read something aloud: transcribe it. The quota resets at
    midnight Pacific (2:00 a.m. in Bogotá).
11. **The mix on a phone speaker:** `mix.py` warns when the music masks the voice (over 10% of the speech under +3
    dB). Lower `mix.bed_db` until it passes: the line-by-line take needed −14 dB (28% masked at −8); the one take,
    clearer, passes at −14 with 1%. Passing isn't the target: the owner found −14 too low and −8 too loud, and
    settled on −11 (puente v5, 8 Oct 2026). Start a voice-and-music video there.
12. **When Gemini isn't enough:** a real person from the city reading the script on a phone (free; the only sure way
    to not sound AI; clean it, then time it like a take), ElevenLabs' Latin American voices (natural; commercial use
    needs a paid plan: the owner's call), or an open model on the GPU (Chatterbox and others: free, more setup).

## The music

1. **The owner picks by ear.** Generated beds (ACE-Step) didn't convince for salsa (teaser v2: "the salsa was not
   all that great"); the puente teaser used a free library's track (Pixabay's "Latin Salsa Music" by Tunetank, the
   owner's pick, from 0:09.85). Offer a shortlist, send the owner the pages or 15 s samples, and let them choose.
2. **Free libraries:** Pixabay Music (the Pixabay Content License: no attribution, commercial use allowed) is
   reachable from here; YouTube's Audio Library and Meta's Sound Collection need the owner's sign-in. Much of
   Pixabay's salsa is AI-generated (the tag "Generated By Ai"): say so next to each candidate. Rank by downloads.
   Track pages are behind Cloudflare: fetch them slowly (one a second); the page's HTML has the file
   (`cdn.pixabay.com/download/audio/…mp3`). Ask before downloading (the file, the source, the size).
3. **Record where it came from:** `video.json` `music.provenance[<bed>]` with `source`, `url`, `author`, `license`
   and `downloaded` (a licensed track; a generated bed keeps its model, prompt and seed). `mix.py` and `render.py`
   check it.
4. **The tempo:** salsa reads in half time (a 90 bpm grid for ~180 bpm music), and trackers disagree. Check with
   `analyze.py` and an autocorrelation of the onsets, then fit a line through the beat times for the exact tempo
   (90.51 bpm for the puente track; ±18 ms). `music.bpm` sets the grid the video cuts on.
5. **Where to start:** where the full band comes in (the loudness doubles: `first_hit`); the owner can say it ("from
   second 9–10").
6. **One track, not a medley,** unless the owner asks: a salsa → reggaeton switch on the same tempo grid was possible
   but "let's not overcomplicate" (the owner, 8 Oct 2026).
7. **Instagram's music instead:** a Creator account gets the licensed library (a Business account mostly Meta's
   Sound Collection), but the owner chooses where the song starts, so cuts only roughly match. Baking our own track
   keeps the sync exact.
