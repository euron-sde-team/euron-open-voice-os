"""Speech recognition accuracy on public recordings: word and character error rate.

``make wer`` (``voiceos wer``) transcribes the first N test utterances of Google FLEURS
(CC-BY-4.0) for English, Hindi and Marathi through the running speech service, with each
Whisper size, and writes ``docs/benchmarks/wer.md`` and ``wer.json`` labelled with the
dataset, the model and the machine.

Nothing is committed: the TSV and only as much of each language's test archive as the
first N clips need are streamed from the Hugging Face copy of FLEURS into a local cache.
Error rates are computed after the same normalization for reference and hypothesis
(lower case, punctuation removed, including the Devanagari danda), so they measure words,
not formatting. CER is reported because WER is harsh on Indic scripts, where one word
often carries several morphemes.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import tarfile
import time
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
LANGUAGES = {"en": "en_us", "hi": "hi_in", "mr": "mr_in"}
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}


# ── scoring ──────────────────────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    """Lower case, punctuation (any Unicode P* category) to spaces, whitespace collapsed."""
    text = unicodedata.normalize("NFC", text.lower())
    chars = [" " if unicodedata.category(c).startswith("P") else c for c in text]
    return " ".join("".join(chars).split())


def edit_distance(ref: list[str], hyp: list[str]) -> int:
    """Levenshtein distance over tokens (words or characters)."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def error_rates(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Corpus WER and CER: total edits over total reference tokens."""
    word_edits = word_total = char_edits = char_total = 0
    for ref, hyp in pairs:
        r, h = normalize(ref), normalize(hyp)
        word_edits += edit_distance(r.split(), h.split())
        word_total += len(r.split())
        rc, hc = list(r.replace(" ", "")), list(h.replace(" ", ""))
        char_edits += edit_distance(rc, hc)
        char_total += len(rc)
    return word_edits / max(1, word_total), char_edits / max(1, char_total)


# ── data ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Clip:
    name: str
    text: str
    path: Path


def read_tsv(data: str) -> dict[str, str]:
    """FLEURS TSV: id, file name, raw transcription, normalized transcription, ..."""
    rows = csv.reader(io.StringIO(data), delimiter="\t", quoting=csv.QUOTE_NONE)
    return {row[1]: row[2] for row in rows if len(row) > 2}


def fetch_clips(lang: str, n: int, cache: Path) -> list[Clip]:
    """The first ``n`` test clips, streamed from the archive and cached locally."""
    config = LANGUAGES[lang]
    folder = cache / config
    folder.mkdir(parents=True, exist_ok=True)
    tsv_path = folder / "test.tsv"
    if not tsv_path.exists():
        with urllib.request.urlopen(f"{FLEURS}/{config}/test.tsv", timeout=60) as resp:  # noqa: S310 fixed https URL
            tsv_path.write_bytes(resp.read())
    texts = read_tsv(tsv_path.read_text(encoding="utf-8"))
    clips = [
        Clip(name, texts[name], folder / name) for name in sorted(texts) if (folder / name).exists()
    ]
    if len(clips) >= n:
        return clips[:n]
    url = f"{FLEURS}/{config}/audio/test.tar.gz"
    with (
        urllib.request.urlopen(url, timeout=60) as resp,  # noqa: S310 fixed https URL
        tarfile.open(fileobj=resp, mode="r|gz") as tar,
    ):
        for member in tar:
            name = Path(member.name).name
            if not member.isfile() or name not in texts or (folder / name).exists():
                continue
            data = tar.extractfile(member)
            if data is None:
                continue
            (folder / name).write_bytes(data.read())
            clips.append(Clip(name, texts[name], folder / name))
            if len(clips) >= n:
                break
    return clips[:n]


# ── run ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Result:
    language: str
    model: str
    utterances: int
    wer: float
    cer: float
    audio_seconds: float
    seconds_per_audio_second: float


def transcribe_all(speech_url: str, model: str, lang: str, clips: list[Clip]) -> Result:
    pairs: list[tuple[str, str]] = []
    audio_s = elapsed = 0.0
    with httpx.Client(base_url=speech_url.rstrip("/"), timeout=300) as client:
        for clip in clips:
            started = time.perf_counter()
            resp = client.post(
                "/v1/audio/transcriptions",
                files={"file": (clip.name, clip.path.read_bytes(), "audio/wav")},
                data={"model": f"whisper-{model}", "language": lang},
            )
            resp.raise_for_status()
            elapsed += time.perf_counter() - started
            audio_s += float(resp.headers.get("x-voiceos-audio-seconds", 0))
            pairs.append((clip.text, str(resp.json()["text"])))
    wer, cer = error_rates(pairs)
    return Result(
        lang, f"whisper-{model}", len(pairs), wer, cer, audio_s, elapsed / max(audio_s, 1e-9)
    )


def hardware() -> dict[str, Any]:
    return {"machine": platform.machine(), "system": platform.system(), "cpus": os.cpu_count()}


def markdown(results: list[Result], n: int, hw: dict[str, Any], note: str) -> str:
    lines = [
        "# Speech recognition accuracy",
        "",
        f"Generated by `make wer` on {time.strftime('%Y-%m-%d')}. Dataset: the first {n} test",
        "utterances per language of [Google FLEURS](https://huggingface.co/datasets/google/fleurs)",
        "(CC-BY-4.0), transcribed by the VoiceOS speech service (faster-whisper, int8, CPU) with",
        "the language set. Lower is better. Reference and hypothesis are normalized the same way",
        "(lower case, punctuation removed).",
        "",
        f"Machine: {hw['machine']} {hw['system']}, {hw['cpus']} CPUs, no GPU. {note}",
        "",
        "| Language | Model | Utterances | WER | CER | Seconds per audio second |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {LANGUAGE_NAMES[r.language]} | {r.model} | {r.utterances} | {r.wer:.1%} | "
            f"{r.cer:.1%} | {r.seconds_per_audio_second:.2f} |"
        )
    lines += [
        "",
        "Seconds per audio second includes the HTTP round trip; below 1.0 is faster than real",
        "time. Reproduce with `make up` then `make wer`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="WER and CER on FLEURS through the speech service")
    parser.add_argument(
        "--speech-url", default=os.environ.get("SPEECH_URL", "http://localhost:4537")
    )
    parser.add_argument("--languages", default="en,hi,mr")
    parser.add_argument("--models", default="base,small")
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--cache", default=".cache/fleurs")
    parser.add_argument("--out", default="../../docs/benchmarks")
    parser.add_argument("--note", default="", help="Context for the reader, e.g. machine load")
    args = parser.parse_args(argv)
    results: list[Result] = []
    for lang in [x for x in args.languages.split(",") if x]:
        clips = fetch_clips(lang, args.n, Path(args.cache))
        for model in [x for x in args.models.split(",") if x]:
            r = transcribe_all(args.speech_url, model, lang, clips)
            print(f"{lang} {r.model}: WER {r.wer:.1%} CER {r.cer:.1%} over {r.utterances} clips")
            results.append(r)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hw = hardware()
    (out / "wer.json").write_text(
        json.dumps(
            {
                "dataset": "google/fleurs test",
                "n": args.n,
                "hardware": hw,
                "note": args.note,
                "results": [asdict(r) for r in results],
            },
            indent=2,
        )
        + "\n"
    )
    (out / "wer.md").write_text(markdown(results, args.n, hw, args.note))
    print(f"wrote {out / 'wer.md'}")
