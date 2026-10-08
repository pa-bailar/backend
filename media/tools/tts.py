"""The voice: Gemini TTS (free tier, MEDIA_GEMINI_API_KEY in the backend's .env), cached. Directing it: AUDIO.md.

  .venv/Scripts/python media/tools/tts.py <video> [line-id ...]
      Every line of projects/<video>/video.json ("voice"."lines") that isn't cached yet → cache/tts/ (media home). A
      line is cached by its words, voice, direction and "take": the same line never calls Gemini twice. For another
      reading of a line, add or bump its "take" in video.json and run again (the old take stays cached).
      With "voice"."one_take": true, the whole script is read in ONE request instead (it sounds far less robotic:
      the owner, 8 Oct 2026), cached by the script, voice, direction and "voice"."take"; tools/timing.py then cuts it
      and finds each line in it.
  .venv/Scripts/python media/tools/tts.py --audition "<text>" --voices Achird,Sulafat,Puck [--direction "<text>"]
      One sample per voice → out/auditions/<voice>-<key>.wav (media home), to choose a voice or a direction.

Then tools/timing.py joins the lines and times every word.
"""

import argparse
import os
import re
import time

from common import CACHE, DIRECTION, HOME, key, load_env, one_take_path, script_text, shown, tts_path, video, write_wav

# 2.5 answers reliably on the free tier; both time out at times (90 s timeout, retries with backoff).
MODELS = ("gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts")


def classify(error: Exception) -> str:
    """What to do after a failed call: "retry" (timeouts, busy, per-minute limits, 5xx), "next" (this model won't
    answer today: its daily quota, a bad request, an unknown model) or "stop" (the key itself is refused)."""
    code = getattr(error, "code", None)
    text = str(error)
    if code in (401, 403) or (code == 400 and "API key" in text):
        return "stop"
    if code == 429 and re.search(r"per ?day|daily", text, re.IGNORECASE):
        return "next"
    if code in (400, 404):
        return "next"
    return "retry"


def api_key() -> str:
    """MEDIA_GEMINI_API_KEY from the environment or the backend's .env (a worktree: the main checkout's); a clear stop
    when it's missing (only new lines need it: cached ones never call Gemini)."""
    load_env()
    value = os.environ.get("MEDIA_GEMINI_API_KEY", "").strip()
    if not value:
        raise SystemExit(
            "MEDIA_GEMINI_API_KEY isn't set: add it to the backend's .env (a free-tier Gemini key; README.md, Setup). "
            "Only lines not in the cache need it."
        )
    return value


def say(text: str, voice: str, direction: str) -> tuple[bytes, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key(), http_options=types.HttpOptions(timeout=90_000))
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
            except Exception as error:  # timeouts and "busy" are common: back off and retry; not the rest
                last = " ".join(str(error).split())[:160]
                action = classify(error)
                if action == "stop":
                    raise SystemExit(f"TTS refused the key (MEDIA_GEMINI_API_KEY): {last}") from None
                if action == "next":
                    print(f"   {model}: {last}; not retrying this model", flush=True)
                    break
                wait = 5 * 2**attempt
                print(f"   {model} attempt {attempt + 1} failed ({last}); retry in {wait} s", flush=True)
                time.sleep(wait)
    raise SystemExit(f"No TTS model answered: {last}")


def lines(name: str, wanted: list[str]) -> None:
    settings = video(name).settings["voice"]
    voice = settings["name"]
    direction = settings.get("direction", DIRECTION)
    if settings.get("one_take"):
        path = one_take_path(settings)
        if path.exists():
            print(f"one take: cached ({path.name})")
            return
        pcm, model = say(script_text(settings), voice, direction)
        write_wav(path, pcm)
        print(f"one take: {len(pcm) / 48000:.2f} s ({model}); check it: timing.py --transcribe {shown(path)}")
        return
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
    out = HOME / "out" / "auditions"
    for voice in voices:
        path = out / f"{voice}-{key(text, direction)}.wav"
        if not path.exists():
            pcm, _ = say(text, voice, direction)
            write_wav(path, pcm)
        print(shown(path))


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
