"""Generate SFX takes locally with Stable Audio 3 small-sfx (CPU, no quota).

Runs inside the Stable Audio 3 checkout's own environment (Stability-AI/
stable-audio-3, set up with `uv sync` outside this repo; the model weights are
gated - accept the licence on huggingface.co/stabilityai/stable-audio-3-small-sfx
once). Reads a job list and writes one WAV per job; takes that already exist are
skipped, so a list can be extended and re-run. The chosen takes are then
imported with import_fal_sfx.py (spec in the same art folder).

Job list (JSON): [{"name": "...", "prompt": "...", "negative": "...",
                   "seconds": 1.5, "seed": 31, "cfg": 1.0, "steps": 8}]
A job with "init" (a 16-bit WAV) and "init_noise" (0..1, lower stays closer)
makes a variation of that sound instead of starting from noise.

Usage (from the stable-audio-3 checkout):
  .venv/Scripts/python <game>/client/tools/audio/sa3_generate.py jobs.json <out_dir> [small-sfx|small-music]
"""
import json, os, sys, time, wave
import numpy as np
from stable_audio_3 import StableAudioModel


def save(path, audio, sr):
    stereo = audio.float().clamp(-1, 1).cpu().numpy().T
    with wave.open(path, "wb") as w:
        w.setnchannels(stereo.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype(np.int16).tobytes())


def load(path):
    import torch
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return sr, torch.from_numpy(pcm.reshape(-1, ch).T.astype(np.float32) / 32768.0)


def main():
    jobs = json.load(open(sys.argv[1], encoding="utf-8"))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    model = StableAudioModel.from_pretrained(sys.argv[3] if len(sys.argv) > 3 else "small-sfx", device="cpu")
    sr = model.model.sample_rate
    for job in jobs:
        path = os.path.join(out_dir, job["name"] + ".wav")
        if os.path.exists(path):
            continue
        start = time.time()
        init = {}
        if job.get("init"):
            init = {"init_audio": load(job["init"]), "init_noise_level": float(job.get("init_noise", 0.7))}
        audio = model.generate(prompt=job["prompt"], negative_prompt=job.get("negative") or None,
            duration=float(job["seconds"]), steps=int(job.get("steps", 8)),
            cfg_scale=float(job.get("cfg", 1.0)), seed=int(job.get("seed", -1)), **init)
        save(path, audio[0], sr)
        print("%s  %.1fs" % (job["name"], time.time() - start), flush=True)


if __name__ == "__main__":
    main()
