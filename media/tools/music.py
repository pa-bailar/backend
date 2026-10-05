"""Music beds with ACE-Step 1.5 (local, D:\\AI\\ace-step): every prompt × seed in video.json, one model load, cached.

Run with the ACE-Step venv (it holds the GPU: don't run ComfyUI at the same time):
  D:/AI/ace-step/.venv/Scripts/python media/tools/music.py <video>
  → media/cache/music/<prompt>-s<seed>-<key>.wav (48 kHz stereo), skipping those already made

video.json's "music": "prompts" ({name: description: style, mood, instruments, texture, "No vocals"}), "seeds",
"bpm", "duration" (seconds; make it longer than the video). Listen, compare them with tools/analyze.py, then set
"bed" to the chosen file (relative to media/) and "first_hit" to its first hit's time; tools/mix.py does the rest.
"""

import shutil
import sys
import time
from pathlib import Path

from common import CACHE, MEDIA, key, video

ACE = Path(r"D:\AI\ace-step")


def path_for(name: str, prompt: str, seed: int, bpm: int, duration: int) -> Path:
    return CACHE / "music" / f"{name}-s{seed}-{key(prompt, seed, bpm, duration)}.wav"


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
            print(f"cached: {path.relative_to(MEDIA).as_posix()}")
    todo = [t for t in todo if not t[3].exists()]
    if not todo:
        return

    sys.path.insert(0, str(ACE))
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    t0 = time.time()
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=str(ACE), config_path="acestep-v15-turbo", device="cuda")
    if not ok:
        raise SystemExit(f"DiT init failed: {msg}")
    llm = LLMHandler()
    msg, ok = llm.initialize(
        checkpoint_dir=str(ACE / "checkpoints"), lm_model_path="acestep-5Hz-lm-1.7B", backend="pt", device="cuda"
    )
    if not ok:
        raise SystemExit(f"LM init failed: {msg}")
    print(f"loaded in {time.time() - t0:.0f} s", flush=True)

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
            inference_steps=8,
            shift=3.0,
            seed=seed,
            thinking=True,
        )
        config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format="wav")
        res = generate_music(dit, llm, params, config, save_dir=str(ACE / "outputs"))
        if not res.success:
            print(f"{label} s{seed}: FAILED {res.error}", flush=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(res.audios[0]["path"], path)
        print(f"{path.relative_to(MEDIA).as_posix()}: {time.time() - t1:.0f} s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
