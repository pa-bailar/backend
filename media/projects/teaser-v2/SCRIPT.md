# Script

Voice: Gemini TTS `gemini-2.5-flash-preview-tts`, voice **Achird**, one file per line
(`tools/tts.py teaser-v2`, cached in `media/cache/tts/`; the lines are in `video.json`), same direction text as the take the owner liked:

> Lee este texto en español con acento colombiano de Bogotá (rolo), natural y cercano, como un audio de WhatsApp
> a un amigo: relajado, con una sonrisa, sin sonar a locutor ni a comercial. Haz pausas cortas donde hay puntos
> suspensivos.

## The opening (rewritten: the old one was unclear)

The old opening ("Uno quiere salir a bailar… y no sabes pa' dónde coger. Por eso hice Pa' Bailar: los sociales y
talleres de Bogotá, en un solo lugar.") was 10 s and indirect. The new one asks the viewer the question directly,
then names the answer.

### Opening A ✅ (picked)

| id | Line | Length |
|---|---|---|
| a1 | ¿Quieres salir a bailar este finde… y no sabes a dónde ir? | 3.4 s |
| a2s | Por eso hice Pa' Bailar. | 1.7 s |

Why: the question is the viewer's own thought, word for word; "Por eso hice Pa' Bailar" is the maker answering in
first person and says the name once, clearly. The screen carries the rest ("Sociales y talleres de baile en
Bogotá"), which keeps the whole voice at ~19 s.

Longer cut, recorded too (`a2`, 5.3 s): "Yo hice Pa' Bailar: los sociales y talleres de Bogotá, en un solo lugar."
Clearer by ear, but it pushes the voice to ~23 s; use it if the owner prefers the explanation spoken.

### Opening B (alternative)

| id | Line | Length |
|---|---|---|
| b1 | ¿Salsa, bachata, kizomba… y no sabes dónde bailar este finde? | 4.5 s |
| b2 | Mira, hice Pa' Bailar: todos los eventos de baile de Bogotá, en un solo lugar. | 5.6 s |

Names the rhythms up front, but it's longer, and in the test transcription Whisper heard b2's "Mira, hice Pa'
Bailar" as "Mira y sepa bailar": the name gets lost after "Mira".

## The second half (kept, as the owner liked it)

| id | Line | Length |
|---|---|---|
| c1 | Miras qué hay hoy, este finde, la otra semana… | 4.4 s |
| c2 | a qué hora, dónde, cuánto vale y cómo llegar. | 3.5 s |
| c3 | No hay que registrarse, es gratis. | 2.4 s |
| c4 | Te dejo el link… y nos vemos bailando. | 2.1 s |

## Full read (picked version, ~19 s)

> ¿Quieres salir a bailar este finde… y no sabes a dónde ir? Por eso hice Pa' Bailar.
> Miras qué hay hoy, este finde, la otra semana… a qué hora, dónde, cuánto vale y cómo llegar.
> No hay que registrarse, es gratis. Te dejo el link… y nos vemos bailando.

Lines are joined with 0.1–0.4 s gaps, and pauses inside a line are capped at 0.32 s (`tools/timing.py`), so
there's no dead air for Instagram's music to fill awkwardly.

## Notes from generation

- `gemini-3.8-flash-tts` (the fallback model) read the direction text aloud once ("Lee este texto en español…"),
  a 19 s take; caught by the Whisper check and replaced with a 2.5 take. Every line is now checked with Whisper.
- The free tier allows only a few TTS requests per minute (429 after ~5 in a row); the script backs off and
  retries.
