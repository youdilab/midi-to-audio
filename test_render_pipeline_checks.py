"""Pytest checks for a completed take-home assessment implementation.

These tests import ``test_render_pipeline`` and assert MIDI timing, audible SFZ
output, master-chain processing, and WAV export. They are expected to **fail**
against the starter stubs and pass once the ``TODO(candidate)`` sections are
implemented.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from mido import MidiFile

PACKAGE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_ROOT))

import test_render_pipeline as pipeline  # noqa: E402

KICK_NOTE = 36


def _kick_note_on_ticks(midi: MidiFile, kick_note: int = KICK_NOTE) -> list[int]:
    """Return absolute tick positions of kick note_on events across all tracks."""
    ticks: list[int] = []
    for track in midi.tracks:
        elapsed = 0
        for msg in track:
            elapsed += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.note == kick_note:
                ticks.append(elapsed)
    return sorted(ticks)


def test_midi_construction() -> None:
    midi = pipeline.parse_arrangement_to_midi(pipeline.MOCK_ARRANGEMENT)
    assert isinstance(midi, MidiFile)
    assert len(midi.tracks) >= 2

    note_ons = 0
    for track in midi.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                note_ons += 1

    bars = pipeline.arrangement_bars(pipeline.MOCK_ARRANGEMENT)
    kicks_per_bar = sum(pipeline.MOCK_ARRANGEMENT["drum_grid"])
    chord_notes = len(pipeline.MOCK_ARRANGEMENT["synth_chords"])
    expected_note_ons = kicks_per_bar * bars + chord_notes
    assert note_ons == expected_note_ons, (
        f"expected {expected_note_ons} note_on events, got {note_ons}"
    )


def test_drum_kick_timing() -> None:
    """Kick hits must land on the correct 16th-note steps, not all at time=0."""
    midi = pipeline.parse_arrangement_to_midi(pipeline.MOCK_ARRANGEMENT)
    step_tick = midi.ticks_per_beat // 4

    kick_ticks = _kick_note_on_ticks(midi)
    bars = pipeline.arrangement_bars(pipeline.MOCK_ARRANGEMENT)
    drum_grid = pipeline.MOCK_ARRANGEMENT["drum_grid"]
    expected: list[int] = []
    for bar in range(bars):
        bar_offset = bar * pipeline.STEPS_PER_BAR
        for step_index, hit in enumerate(drum_grid):
            if hit:
                expected.append((bar_offset + step_index) * step_tick)

    assert kick_ticks == expected, (
        f"expected kick note_on ticks {expected}, got {kick_ticks}"
    )


def test_sfz_render_non_silent() -> None:
    midi = pipeline.parse_arrangement_to_midi(pipeline.MOCK_ARRANGEMENT)
    duration = pipeline.arrangement_duration_sec(pipeline.MOCK_ARRANGEMENT)
    audio = pipeline.render_midi_with_sfizz(
        midi,
        pipeline.SFZ_INSTRUMENT_PATH,
        sample_rate=pipeline.SAMPLE_RATE,
        block_size=pipeline.BLOCK_SIZE,
        duration_sec=duration,
    )
    assert audio is not None
    peak = float(np.max(np.abs(audio)))
    assert peak > 0.01, f"expected audible SFZ render, peak={peak}"


def test_master_chain_changes_audio() -> None:
    midi = pipeline.parse_arrangement_to_midi(pipeline.MOCK_ARRANGEMENT)
    duration = pipeline.arrangement_duration_sec(pipeline.MOCK_ARRANGEMENT)
    dry = pipeline.render_midi_with_sfizz(
        midi,
        pipeline.SFZ_INSTRUMENT_PATH,
        sample_rate=pipeline.SAMPLE_RATE,
        block_size=pipeline.BLOCK_SIZE,
        duration_sec=duration,
    )
    assert dry is not None
    wet = pipeline.apply_master_chain(dry, pipeline.SAMPLE_RATE)
    assert wet is not None
    diff = float(np.mean(np.abs(wet - dry)))
    assert diff > 1e-6, "master chain should modify the dry buffer"


def test_pipeline_writes_wav(tmp_path: Path) -> None:
    output = tmp_path / "test_mix_output.wav"
    original_output = pipeline.OUTPUT_WAV_PATH
    pipeline.OUTPUT_WAV_PATH = output
    try:
        pipeline.run_pipeline(pipeline.MOCK_ARRANGEMENT)
    finally:
        pipeline.OUTPUT_WAV_PATH = original_output

    assert output.is_file()

    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnchannels() == 2
        assert wav_file.getframerate() == pipeline.SAMPLE_RATE
        frames = wav_file.readframes(wav_file.getnframes())

    samples = np.frombuffer(frames, dtype=np.int16)
    peak = float(np.max(np.abs(samples)))
    assert peak > 100, f"output WAV should not be silent, peak={peak}"
