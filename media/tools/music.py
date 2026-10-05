"""Music beds with ACE-Step 1.5 (local, D:\\AI\\ace-step): every prompt × seed in video.json, one model load, cached.

Run with the ACE-Step venv (it holds the GPU: don't run ComfyUI at the same time):
  D:/AI/ace-step/.venv/Scripts/python media/tools/music.py <video>
  → cache/music/<prompt>-s<seed>-<key>.wav in the media home (48 kHz stereo), skipping those already made, and
    <same name>.json next to each: how it was made (model, revision, prompt, seed, reference audio, date)

video.json's "music": "prompts" ({name: description: style, mood, instruments, texture, "No vocals"}), "seeds",
"bpm", "duration" (seconds; make it longer than the video). Listen, compare them with tools/analyze.py, then set
"bed" to the chosen file (relative to the media home), "first_hit" to its first hit's time, and copy its .json into
"provenance" under the bed's path (mix.py and render.py warn without it, --strict refuses); tools/mix.py does the rest.
"""

import json
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from common import CACHE, key, shown, video

ACE = Path(r"D:\AI\ace-step")


# The generation settings (ACE-Step 1.5 turbo): part of each bed's cache key, so changing one never reuses a bed.
STEPS, SHIFT, THINKING = 8, 3.0, True
DIT, LM = "acestep-v15-turbo", "acestep-5Hz-lm-1.7B"


def path_for(name: str, prompt: str, seed: int, bpm: int, duration: int) -> Path:
    return CACHE / "music" / f"{name}-s{seed}-{key(prompt, seed, bpm, duration, STEPS, SHIFT, THINKING)}.wav"


def provenance(name: str, prompt: str, seed: int, bpm: int, duration: int, revision: str, day: str) -> dict:
    """How a bed was made, in the shape of video.json's "music"."provenance"[<bed>] (common.PROVENANCE_FIELDS):
    written next to each new bed as <bed>.json, to copy into video.json when the bed is chosen."""
    return {
        "model": f"ACE-Step 1.5 ({DIT} DiT + {LM}, thinking {THINKING})",
        "revision": revision,
        "prompt_name": name,
        "prompt": prompt,
        "seed": seed,
        "settings": {"bpm": bpm, "duration": duration, "steps": STEPS, "shift": SHIFT},
        "reference_audio": None,
        "generated": day,
    }


def ace_revision() -> str:
    """The ACE-Step checkout's commit (D:\\AI\\ace-step is a git clone)."""
    done = subprocess.run(["git", "-C", str(ACE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return f"ace-step/ACE-Step-1.5@{done.stdout.strip()}" if done.returncode == 0 else "unknown"


def main(name: str) -> None:
    music = video(name).settings["music"]
    bpm, duration = int(music["bpm"]), int(music.get("duration", 30))
    todo = [
        (p, prompt, seed, path_for(p, prompt, seed, bpm, duration))
        for p, prompt in music["prompts"].items()
        for seed in music.get("seeds", [7])
    ]
    for *_, path in todo:
        if path.exists():
            print(f"cached: {shown(path)}")
    todo = [t for t in todo if not t[3].exists()]
    if not todo:
        return

    sys.path.insert(0, str(ACE))
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    t0 = time.time()
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=str(ACE), config_path=DIT, device="cuda")
    if not ok:
        raise SystemExit(f"DiT init failed: {msg}")
    llm = LLMHandler()
    msg, ok = llm.initialize(checkpoint_dir=str(ACE / "checkpoints"), lm_model_path=LM, backend="pt", device="cuda")
    if not ok:
        raise SystemExit(f"LM init failed: {msg}")
    print(f"loaded in {time.time() - t0:.0f} s", flush=True)
    revision = ace_revision()

    for label, prompt, seed, path in todo:
        t1 = time.time()
        params = GenerationParams(
            caption=prompt,
            lyrics="[Instrumental]",
            instrumental=True,
            bpm=bpm,
            keyscale="",
            timesignature="4",
            duration=duration,
            inference_steps=STEPS,
            shift=SHIFT,
            seed=seed,
            thinking=THINKING,
        )
        config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format="wav")
        res = generate_music(dit, llm, params, config, save_dir=str(ACE / "outputs"))
        if not res.success:
            print(f"{label} s{seed}: FAILED {res.error}", flush=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(res.audios[0]["path"], path)
        made = provenance(label, prompt, seed, bpm, duration, revision, date.today().isoformat())
        path.with_suffix(".json").write_text(json.dumps(made, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{shown(path)}: {time.time() - t1:.0f} s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        raise SystemExit(__doc__)
    main(sys.argv[1])
