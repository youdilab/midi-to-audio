#!/usr/bin/env python3
"""Smoke-check that the assessment environment is ready before you start coding."""

from __future__ import annotations

import importlib
import sys
import wave
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
KICK_SAMPLE_PATH = PACKAGE_ROOT / "instruments" / "tr909" / "samples" / "kick.wav"
SFZ_INSTRUMENT_PATH = PACKAGE_ROOT / "instruments" / "tr909" / "samples" / "placeholder.sfz"
REQUIRED_PACKAGES = ("mido", "numpy", "pedalboard", "pysfizz", "pytest")


def main() -> int:
    errors: list[str] = []

    if sys.version_info < (3, 11):
        errors.append(
            f"Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})"
        )

    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
        except ImportError:
            errors.append(f"Missing package: {package}")

    try:
        import pysfizz

        pysfizz.Synth(sample_rate=48_000)
    except Exception as exc:
        errors.append(f"pysfizz.Synth() failed: {exc}")

    if not KICK_SAMPLE_PATH.is_file():
        errors.append(f"Missing bundled sample: {KICK_SAMPLE_PATH}")
    else:
        try:
            with wave.open(str(KICK_SAMPLE_PATH), "rb") as wav_file:
                if wav_file.getnframes() == 0:
                    errors.append(f"Bundled sample is empty: {KICK_SAMPLE_PATH}")
        except wave.Error as exc:
            errors.append(f"Bundled sample is not a valid WAV: {KICK_SAMPLE_PATH} ({exc})")

    if not SFZ_INSTRUMENT_PATH.is_file():
        errors.append(f"Missing SFZ instrument: {SFZ_INSTRUMENT_PATH}")

    if errors:
        print("Environment check failed:")
        for error in errors:
            print(f"  - {error}")
        print()
        print("See README.md → Requirements for setup instructions.")
        return 1

    print("Environment check passed.")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Kick sample: {KICK_SAMPLE_PATH.name}")
    print(f"  SFZ instrument: {SFZ_INSTRUMENT_PATH.name}")
    print()
    print("Next: implement TODO(candidate) sections in test_render_pipeline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
