"""The voice: one Gemini TTS file per script line (free tier, MEDIA_GEMINI_API_KEY in the backend's .env), cached.

  .venv/Scripts/python media/tools/tts.py <video> [line-id ...]
      Every line of projects/<video>/video.json ("voice"."lines") that isn't cached yet → media/cache/tts/. A line is
      cached by its words, voice, direction and "take": the same line never calls Gemini twice. For another reading
      of a line, add or bump its "take" in video.json and run again (the old take stays cached).
  .venv/Scripts/python media/tools/tts.py --audition "<text>" --voices Achird,Sulafat,Puck [--direction "<text>"]
      One sample per voice → media/out/auditions/<voice>-<key>.wav, to choose a voice or a direction.

Then tools/timing.py joins the lines and times every word.
"""

import argparse
import os
import time

from common import CACHE, MEDIA, key, load_env, tts_path, video, write_wav

# 2.5 answers reliably on the free tier; both time out at times (90 s timeout, retries with backoff).
MODELS = ("gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts")
DIRECTION = (
    "Lee este texto en español con acento colombiano de Bogotá (rolo), natural y cercano, como un audio de "
    "WhatsApp a un amigo: relajado, con una sonrisa, sin sonar a locutor ni a comercial. Haz pausas cortas "
    "donde hay puntos suspensivos."
)


def say(text: str, voice: str, direction: str) -> tuple[bytes, str]:
    from google import genai
    from google.genai import types

    load_env()
    client = genai.Client(api_key=os.environ["MEDIA_GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=90_000))
    last = ""
    for model in MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=f"{direction}\n\n{text}",
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                            )
                        ),
                    ),
                )
                return response.candidates[0].content.parts[0].inline_data.data, model
            except Exception as error:  # timeouts and "busy" are common: back off and retry
                last = " ".join(str(error).split())[:120]
                wait = 5 * 2**attempt
                print(f"   {model} attempt {attempt + 1} failed ({last}); retry in {wait} s", flush=True)
                time.sleep(wait)
    raise SystemExit(f"No TTS model answered: {last}")


def lines(name: str, wanted: list[str]) -> None:
    settings = video(name).settings["voice"]
    voice = settings["name"]
    direction = settings.get("direction", DIRECTION)
    for line in settings["lines"]:
        if wanted and line["id"] not in wanted:
            continue
        path = tts_path(line["text"], voice, direction, line.get("take", 0))
        if path.exists():
            print(f"{line['id']}: cached ({path.name}) {line['text']}")
            continue
        pcm, model = say(line["text"], voice, direction)
        write_wav(path, pcm)
        print(f"{line['id']}: {len(pcm) / 48000:.2f} s ({model}) {line['text']}", flush=True)


def audition(text: str, voices: list[str], direction: str) -> None:
    out = MEDIA / "out" / "auditions"
    for voice in voices:
        path = out / f"{voice}-{key(text, direction)}.wav"
        if not path.exists():
            pcm, _ = say(text, voice, direction)
            write_wav(path, pcm)
        print(path.relative_to(MEDIA).as_posix())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?")
    parser.add_argument("lines", nargs="*")
    parser.add_argument("--audition")
    parser.add_argument("--voices", default="Achird,Sulafat,Puck,Laomedeia")
    parser.add_argument("--direction", default=DIRECTION)
    args = parser.parse_args()
    (CACHE / "tts").mkdir(parents=True, exist_ok=True)
    if args.audition:
        audition(args.audition, args.voices.split(","), args.direction)
    elif args.video:
        lines(args.video, args.lines)
    else:
        parser.print_help()
