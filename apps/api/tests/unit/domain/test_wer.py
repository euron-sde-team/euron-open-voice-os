"""Word and character error rate scoring for the FLEURS benchmark."""

from __future__ import annotations

import pytest

from voiceos.benchmarks.wer import Result, edit_distance, error_rates, markdown, normalize, read_tsv


def test_normalization_ignores_case_and_punctuation_in_every_script() -> None:
    assert normalize("Hello, World!  It's 5 p.m.") == "hello world it s 5 p m"
    assert normalize("नमस्ते, आप कैसे हैं? मैं ठीक हूँ।") == "नमस्ते आप कैसे हैं मैं ठीक हूँ"


def test_edit_distance_and_rates() -> None:
    assert edit_distance(list("kitten"), list("sitting")) == 3
    assert edit_distance([], ["a"]) == 1
    wer, cer = error_rates([("the cat sat", "the cat sat"), ("a b c d", "a x c")])
    assert wer == pytest.approx(2 / 7)  # one substitution, one deletion over seven words
    assert cer == pytest.approx(2 / 13)
    assert error_rates([("Hello.", "hello")]) == (0.0, 0.0)


def test_tsv_and_report() -> None:
    tsv = "1\t10.wav\tHello there.\thello there\n2\t11.wav\tBye.\tbye\nbroken\n"
    assert read_tsv(tsv) == {"10.wav": "Hello there.", "11.wav": "Bye."}
    md = markdown(
        [Result("hi", "whisper-small", 25, 0.31, 0.12, 120.0, 0.8)],
        25,
        {"machine": "arm64", "system": "Linux", "cpus": 8, "load_start": 1.0, "load_end": 2.0},
        "Quiet machine.",
    )
    assert "| Hindi | whisper-small | 25 | 31.0% | 12.0% | 0.80 |" in md
    assert "CC-BY-4.0" in md and "8 CPUs" in md and "1.0 at the start" in md
