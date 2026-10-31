"""Pick the best generated alternatives for each sound and build a listening page.

sa3_generate.py writes several raw takes per sound (<key>__s<seed>.wav; any
<key>__<name>.wav in the raw folder counts, e.g. a sliced library recording). This
screens them against the sound that is in the game now, keeps the best three,
cuts and levels them the way the game import does (import_fal_sfx.process) and
writes art/audio_review/: alts/<key>_<n>.wav, alts.json (which take each
alternative came from) and index.html - every sound with its current version
and the three alternatives side by side. The page remembers the choices in the
browser and copies them as JSON for the import step.

Screening, per take, against the current file:
  * noise: generated takes that collapsed into hiss have a flat spectrum;
  * character: spectral centroid and flatness near the current sound's;
  * one-shots: an early peak and a real decay (no endless drone);
  * "max" (seconds, in the plan): the longest an alternative may be; a take
    longer than that is split into its separate events (a walk into single
    footsteps, a recording into its hits) and only its best event competes;
    "single": true splits every take that way (one footstep, one click);
  * one take gives at most one alternative, so the alternatives differ;
  * loops: the steadiest window of the current length (even level);
  * music ("music": true in the plan): kept whole, only centroid/flatness.
Every alternative is levelled to the current file's loudness for a fair listen.

Usage (any python with numpy; mp3 needs soundfile, e.g. the SA3 venv): python review_alts.py --plan plan.json --raw ../art/audio_sa3/alts_raw
                             --client . --out ../art/audio_review
plan.json: {key: {"text": prompt, "loop": bool, "orig": seconds, "seconds": generated, "max": seconds}}
A second review round gets its own --out and --store, so each page keeps its own choices.

Import the choices (the page's copied JSON, {key: alt number or "other_key:n"}) into the game:
  python review_alts.py --client . --out ../art/audio_review --apply picks.json [--note "..."]
Each chosen alternative replaces the file its library entry points at exactly as
it sounded on the page (already cut, processed and levelled to the old file); the
entry's length, purpose and source follow, and --note is appended once to the
library's provenance and licence.
"""
import argparse, glob, html, json, os, sys, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_fal_sfx import process, write_wav

SR = 44100


def read(path):
    if not path.lower().endswith(".wav"):
        # The music is mp3; libsndfile (soundfile, in the SA3 venv) decodes it.
        import soundfile
        x, sr = soundfile.read(path, dtype="float32", always_2d=True)
        return resample(x.mean(axis=1), sr)
    with wave.open(path, "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype=np.uint8)
    if sw == 3:
        b = raw.reshape(-1, 3).astype(np.int32)
        x = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = (np.where(x >= 1 << 23, x - (1 << 24), x) / float(1 << 23)).astype(np.float32)
    else:
        x = np.frombuffer(raw.tobytes(), dtype=np.int16).astype(np.float32) / 32768.0
    return resample(x.reshape(-1, ch).mean(axis=1), sr)


def resample(x, sr):
    if sr != SR:
        m = int(round(len(x) * SR / sr))
        X = np.fft.rfft(x)
        Y = np.zeros(m // 2 + 1, dtype=complex)
        k = min(len(Y), len(X))
        Y[:k] = X[:k]
        x = (np.fft.irfft(Y, m) * (m / len(x))).astype(np.float32)
    return x


def envelope(x, hop=0.05):
    h = int(SR * hop)
    return np.array([20 * np.log10(np.sqrt(np.mean(x[i:i + h] ** 2)) + 1e-9) for i in range(0, max(1, len(x) - h), h)])


def spectrum_traits(x):
    """Centroid (Hz) and spectral flatness (0 tonal .. 1 white noise) of the loud part."""
    n = 2048
    frames = [x[i:i + n] for i in range(0, max(1, len(x) - n), n // 2)]
    level = np.array([np.sqrt(np.mean(f ** 2)) for f in frames])
    keep = [f for f, l in zip(frames, level) if l > level.max() * 0.1] or frames
    power = np.mean([np.abs(np.fft.rfft(f * np.hanning(len(f)))) ** 2 for f in keep], axis=0) + 1e-12
    freqs = np.fft.rfftfreq(n, 1 / SR)[:len(power)]
    centroid = float(np.sum(power * freqs) / np.sum(power))
    flatness = float(np.exp(np.mean(np.log(power))) / np.mean(power))
    return centroid, flatness


def one_shot_cut(x, orig, cap=None):
    """From the start to where it has fallen 40 dB under its peak (at most `cap`, else 1.6x the current length + 1 s)."""
    e = envelope(x)
    i = int(np.argmax(e))
    below = np.nonzero(e[i:] < e.max() - 40)[0]
    end = (i + (below[0] if len(below) else len(e) - i)) * 0.05 + 0.05
    end = min(end, cap or orig * 1.6 + 1.0, len(x) / SR)
    y = x[:int(end * SR)].copy()
    k = min(len(y), int(0.08 * SR))
    y[-k:] *= np.linspace(1.0, 0.0, k) ** 2
    return y


def events(x, cap, gap=0.12):
    """The separate sounds in a take: runs above 35 dB under its peak, joined across gaps
    under `gap` seconds, each from 10 ms before its onset to its fall (at most `cap` seconds).
    Returns (start seconds, samples, peak dB under the take's peak) per event."""
    e = envelope(x, 0.01)
    on = e > e.max() - 35
    runs, i = [], 0
    while i < len(on):
        if not on[i]:
            i += 1
            continue
        j = i
        while j < len(on) and (on[j] or on[j:j + int(gap / 0.01)].any()):
            j += 1
        if j - i >= 3:
            runs.append((i, j))
        i = j
    found = []
    for a, b in runs:
        start = max(0, int((a * 0.01 - 0.01) * SR))
        y = x[start:start + int(cap * SR)]
        found.append((start / SR, one_shot_cut(y, cap, cap), float(e.max() - e[a:b].max())))
    return found


def steadiest(x, length):
    """The window of `length` seconds with the most even level (skipping the first 0.4 s)."""
    n = int(length * SR)
    if len(x) <= n + int(0.4 * SR):
        return x
    e = envelope(x, 0.1)
    w = max(1, int(length / 0.1))
    best, at = 1e9, 4
    for s in range(4, max(5, len(e) - w)):
        seg = e[s:s + w]
        if len(seg) < w:
            break
        score = seg.std() - 0.05 * seg.mean()
        if score < best:
            best, at = score, s
    return x[int(at * 0.1 * SR):int(at * 0.1 * SR) + n]


def score_take(x, item, ref):
    c, f = spectrum_traits(x)
    rc, rf = ref
    s = abs(np.log2(max(c, 50) / max(rc, 50))) * 2.0 + abs(f - rf) * 6.0
    if f > 0.45 and rf < 0.3:
        s += 10.0  # collapsed into hiss
    e = envelope(x)
    if item.get("music"):
        return s
    if item["loop"]:
        mid = e[4:-4] if len(e) > 12 else e
        s += mid.std() * 0.25
    else:
        i = int(np.argmax(e))
        s += max(0.0, i * 0.05 - max(0.4, item["orig"] * 0.6)) * 3.0
        if e[-6:].mean() > e.max() - 25:
            s += 6.0  # never decays
    return s


def build_page(rows, out, store):
    groups = {}
    for r in rows:
        groups.setdefault(r["key"].split("_")[0], []).append(r)
    parts = []
    for g, items in groups.items():
        parts.append('<h2>%s <span class="n">%d</span></h2>' % (html.escape(g), len(items)))
        for r in items:
            cells = []
            for n, (label, src) in enumerate([("Mevcut", r["current"])] + [("Alt %d" % i, s) for i, s in enumerate(r["alts"], 1)]):
                cells.append('<label class="opt"><input type="radio" name="%s" value="%d"%s> %s'
                    '<audio controls preload="none" src="%s"></audio></label>'
                    % (r["key"], n, " checked" if n == 0 else "", label, html.escape(src)))
            parts.append('<div class="row" data-key="%s"><div class="meta"><b>%s</b>%s<p>%s</p></div><div class="opts">%s</div></div>'
                % (r["key"], html.escape(r["key"]), ' <span class="loop">döngü</span>' if r["loop"] else "",
                   html.escape(r["text"]), "".join(cells)))
    page = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ses Alternatifleri</title><style>
:root{--bg:#14161a;--card:#1d2026;--ink:#e8e6e1;--mute:#9aa0a8;--acc:#e0b04a}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:#0f1114;padding:12px 16px;border-bottom:1px solid #2a2e35;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:2}
header b{font-size:16px}button{background:var(--acc);color:#1a1a1a;border:0;border-radius:6px;padding:7px 12px;font-weight:600;cursor:pointer}
main{padding:8px 16px 60px;max-width:1400px;margin:auto}h2{margin:28px 0 8px;text-transform:uppercase;letter-spacing:.06em;font-size:13px;color:var(--acc)}
.n{color:var(--mute)}.row{background:var(--card);border-radius:8px;padding:10px 12px;margin:8px 0;display:grid;grid-template-columns:minmax(220px,1fr) 3fr;gap:12px}
.row.changed{outline:2px solid var(--acc)}.meta p{margin:4px 0 0;color:var(--mute);font-size:12px}.loop{font-size:11px;color:var(--acc)}
.opts{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:8px}.opt{display:flex;flex-direction:column;gap:4px;font-size:12px}
audio{width:100%;height:32px}@media(max-width:800px){.row{grid-template-columns:1fr}.opts{grid-template-columns:1fr 1fr}}
#count{color:var(--mute)}</style></head><body>
<header><b>Ses Alternatifleri</b><span id="count"></span><button id="copy">Seçimleri kopyala</button><button id="reset" style="background:#3a3f47;color:var(--ink)">Sıfırla</button></header>
<main>""" + "".join(parts) + """</main><script>
const KEY='""" + store + """';let picks={};try{picks=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(picks))}catch(e){};paint()}
function paint(){document.querySelectorAll('.row').forEach(r=>{const k=r.dataset.key,v=picks[k]||0;
 const i=r.querySelector('input[value="'+v+'"]');if(i)i.checked=true;r.classList.toggle('changed',v>0)});
 document.getElementById('count').textContent=Object.keys(picks).length+' ses değişecek'}
document.addEventListener('change',e=>{if(e.target.type!=='radio')return;const v=+e.target.value;
 if(v)picks[e.target.name]=v;else delete picks[e.target.name];save()});
document.addEventListener('play',e=>{document.querySelectorAll('audio').forEach(a=>{if(a!==e.target)a.pause()})},true);
document.getElementById('copy').onclick=()=>{const t=JSON.stringify(picks);navigator.clipboard.writeText(t).then(()=>alert('Kopyalandı, sohbete yapıştır:\\n'+t),()=>prompt('Kopyala:',t))};
document.getElementById('reset').onclick=()=>{if(confirm('Tüm seçimler sıfırlansın mı?')){picks={};save()}};paint();
</script></body></html>"""
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)


def apply(args):
    review = json.load(open(os.path.join(args.out, "alts.json"), encoding="utf-8"))
    picks = json.load(open(args.apply, encoding="utf-8"))
    lib_path = os.path.join(args.client, "assets", "audio", "sound_library.json")
    library = json.load(open(lib_path, encoding="utf-8"))
    for key, n in sorted(picks.items()):
        # A choice is an alt number, or "other_key:n" to take another sound's alternative.
        other, n = (str(n).split(":") + [None])[:2] if ":" in str(n) else (key, n)
        entry, item = library["sounds"][key], review["plan"][other]
        if not entry["path"].endswith(".wav"):
            raise SystemExit("%s is not a WAV entry (music variants: import_music_variants.py)" % key)
        src = os.path.join(args.out, "alts", "%s_%d.wav" % (other, int(n)))
        y = read(src)
        write_wav(os.path.join(args.client, entry["path"]), y, SR)
        entry["seconds"] = round(len(y) / SR, 3)
        entry["sample_rate"] = SR
        entry["purpose"] = item["text"].split(", game sound effect")[0]
        take = review["chosen"][other][int(n) - 1]["take"]
        entry["source"] = "%s; %s" % ("Sonniss GDC 2026 Game Audio Bundle, art/audio_sonniss/raw" if "__x" in take
            else "Stable Audio 3 small-sfx or small-music (local, CPU)", take)
        print(key, n, take)
    if args.note:
        for field in ["provenance", "license"]:
            if args.note not in library[field]:
                library[field] = library[field].rstrip(".") + ". " + args.note
    with open(lib_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(library, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("applied %d" % len(picks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan")
    ap.add_argument("--raw")
    ap.add_argument("--client", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=int, default=3)
    ap.add_argument("--store", default="hpmmo-audio-picks", help="the page's localStorage key")
    ap.add_argument("--apply", help="the page's copied choices (JSON file): import them into the game")
    ap.add_argument("--note", help="with --apply: appended to the library's provenance and licence")
    args = ap.parse_args()
    if args.apply:
        return apply(args)
    plan = json.load(open(args.plan, encoding="utf-8"))
    library = json.load(open(os.path.join(args.client, "assets", "audio", "sound_library.json"), encoding="utf-8"))["sounds"]
    os.makedirs(os.path.join(args.out, "alts"), exist_ok=True)
    rows, chosen = [], {}
    for key, item in plan.items():
        current = os.path.join(args.client, library[key]["path"])
        takes = sorted(glob.glob(os.path.join(args.raw, key + "__*.wav")))
        if not takes or not os.path.exists(current):
            print("skip", key)
            continue
        now = read(current)
        ref = spectrum_traits(now)
        loudness = float(np.sqrt(np.mean(now ** 2)))
        scored = []
        for t in takes:
            x = read(t)
            if item.get("music"):
                x = x[:int(item["orig"] * SR)].copy()
                if not item["loop"]:
                    k = min(len(x), int(1.5 * SR))
                    x[-k:] *= np.linspace(1.0, 0.0, k)
            elif item["loop"]:
                x = steadiest(x, max(2.0, item["orig"]))
            elif item.get("single") or item.get("max") and len(x) > item["max"] * 1.2 * SR:
                # Too long to be one sound (or a "single" hit wanted: a footstep, a click):
                # its best single event competes.
                found = events(x, item.get("max") or item["orig"] * 1.6, 0.06 if item.get("single") else 0.12)
                if not found:
                    continue
                best = min(((score_take(y, item, ref) + quiet * 0.3, at, y) for at, y, quiet in found), key=lambda f: f[0])
                scored.append((best[0], "%s@%.2fs" % (t, best[1]), best[2]))
                continue
            else:
                x = one_shot_cut(x, item["orig"], item.get("max"))
            scored.append((score_take(x, item, ref), t, x))
        scored.sort(key=lambda s: s[0])
        alts = []
        for n, (s, t, x) in enumerate(scored[:args.keep], 1):
            y = process(x.astype(np.float32), SR, item["loop"])
            y = y * (loudness / (np.sqrt(np.mean(y ** 2)) + 1e-9))
            y = y / max(1.0, float(np.abs(y).max()) / 0.89)
            name = "%s_%d.wav" % (key, n)
            write_wav(os.path.join(args.out, "alts", name), y, SR)
            alts.append("alts/" + name)
            chosen.setdefault(key, []).append({"take": os.path.basename(t), "score": round(float(s), 2)})
        rel = os.path.relpath(current, args.out).replace(os.sep, "/")
        rows.append({"key": key, "text": item["text"], "loop": item["loop"], "current": rel, "alts": alts})
        print(key, [c["score"] for c in chosen[key]])
    json.dump({"plan": plan, "chosen": chosen}, open(os.path.join(args.out, "alts.json"), "w", encoding="utf-8"), indent=1)
    build_page(rows, args.out, args.store)
    print("page:", os.path.join(args.out, "index.html"), len(rows), "sounds")


if __name__ == "__main__":
    main()
