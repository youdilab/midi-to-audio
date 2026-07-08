#!/usr/bin/env python3
"""
Take-home assessment scaffold: JSON arrangement → MIDI → SFZ render → master mix.

Candidates implement the marked sections. The script runs end-to-end with stubs
so imports succeed; it exits non-zero when bundled assets are missing or when
rendering returns no audio buffer.
"""

from __future__ import annotations

import logging
import sys
import wave
from pathlib import Path
from typing import Any
from mido import Message, MidiFile, MidiTrack, MetaMessage, bpm2tempo
from collections import deque

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock arrangement payload (edit or replace for local experiments)
# ---------------------------------------------------------------------------
MOCK_ARRANGEMENT: dict[str, Any] = {
    "tempo": 120,
    "length": 2,
    # 16 steps = one bar of 16th notes; repeated for each bar in "length"
    "drum_grid": [
        1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0,
    ],
    "synth_chords": [
        {"note": 60, "velocity": 90, "beat": 0.0},
        {"note": 64, "velocity": 85, "beat": 0.0},
        {"note": 67, "velocity": 88, "beat": 0.0},
        {"note": 60, "velocity": 80, "beat": 2.0},
        {"note": 65, "velocity": 82, "beat": 2.0},
        {"note": 69, "velocity": 84, "beat": 2.0},
    ],
}

# Relative paths (resolved from this file's directory)
PACKAGE_ROOT = Path(__file__).resolve().parent
SFZ_INSTRUMENT_PATH = PACKAGE_ROOT / "instruments" / "tr909" / "samples" / "placeholder.sfz"
KICK_SAMPLE_PATH = SFZ_INSTRUMENT_PATH.parent / "kick.wav"
OUTPUT_WAV_PATH = PACKAGE_ROOT / "test_mix_output.wav"

SAMPLE_RATE = 48_000
BLOCK_SIZE = 512
STEPS_PER_BAR = 16
TICKS_PER_BEAT = 480  # used for 16th-note grid math in MIDI construction

TYPE_SYNCHRONOUS = 1  # MIDI file type to start all tracks at the same time

CHANNEL_DRUMS = 9  # MIDI channel used for drums by convention
CHANNEL_SYNTH = 0

MIDI_NOTE_KICK = 36

DEFAULT_VELOCITY_DRUMS = 127
BAR_LENGTH_IN_BEATS = 4


def configure_logging() -> None:
    """Configure pipeline-wide logging (use logging, not print)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def arrangement_bars(arrangement: dict[str, Any]) -> int:
    """Return the number of bars to render from the arrangement payload."""
    return int(arrangement.get("length", 1))


def verify_bundled_assets() -> None:
    """Ensure required sample assets exist before rendering."""
    if not KICK_SAMPLE_PATH.is_file():
        logger.error(
            "Missing bundled kick sample at %s — add kick.wav beside placeholder.sfz",
            KICK_SAMPLE_PATH,
        )
        sys.exit(1)

    if not SFZ_INSTRUMENT_PATH.is_file():
        logger.error("Missing SFZ instrument at %s", SFZ_INSTRUMENT_PATH)
        sys.exit(1)


def parse_arrangement_to_midi(arrangement: dict[str, Any]) -> Any:
    """
    Build one or more MIDI tracks from the JSON arrangement using mido.

    Hints:
    - Import: ``from mido import Message, MidiFile, MidiTrack, bpm2tempo``
    - Loop ``drum_grid`` once per bar in ``arrangement["length"]`` (16 steps per bar).
    - Map each ``1`` in ``drum_grid`` to a kick hit on the corresponding 16th step.
    - Convert ``synth_chords`` entries (note, velocity, beat) to note_on / note_off pairs.
    - Use ``bpm2tempo(arrangement["tempo"])`` for the MIDI tempo meta message.
    - Return a ``MidiFile`` (or a list of track-specific MidiFiles) for rendering.
    """
    logger.info("Parsing arrangement to MIDI (tempo=%s)", arrangement["tempo"])

    mid = MidiFile(ticks_per_beat=TICKS_PER_BEAT, type=TYPE_SYNCHRONOUS)

    tempo = arrangement["tempo"]
    length = arrangement["length"]

    # Metadata
    metadata_track = MidiTrack()
    mid.tracks.append(metadata_track)
    metadata_track.append(MetaMessage('track_name', name='Metadata', time=0))
    metadata_track.append(
        MetaMessage(
            'time_signature',
            numerator=4,
            denominator=4,
            time=0
        )
    )
    metadata_track.append(
        MetaMessage(
            'set_tempo', tempo=bpm2tempo(tempo), time=0
        )
    )

    # Drums
    drum_track = MidiTrack()
    mid.tracks.append(drum_track)
    drum_track.append(MetaMessage('track_name', name='Drums', time=0))

    steps_per_beat = STEPS_PER_BAR / BAR_LENGTH_IN_BEATS
    drum_note_duration = int(TICKS_PER_BEAT / steps_per_beat)

    wait_time_drums = 0  # time since last MIDI message in ticks

    for bar in range(length):
        for step in arrangement["drum_grid"]:
            if step == 1:
                drum_track.append(
                    Message(
                        'note_on',
                        note=MIDI_NOTE_KICK,
                        velocity=DEFAULT_VELOCITY_DRUMS,
                        channel=CHANNEL_DRUMS,
                        time=wait_time_drums
                    )
                )
                drum_track.append(
                    Message(
                        'note_off',
                        note=MIDI_NOTE_KICK,
                        velocity=DEFAULT_VELOCITY_DRUMS,
                        channel=CHANNEL_DRUMS,
                        time=drum_note_duration
                    )
                )
                wait_time_drums = 0
            else:
                wait_time_drums += drum_note_duration

    logger.info("Parsing drums arrangement completed")

    # Synth
    synth_chords_track = MidiTrack()
    mid.tracks.append(synth_chords_track)
    synth_chords_track.append(
        MetaMessage('track_name', name='Synth Chords', time=0)
    )

    for bar in range(length):
        current_notes = deque()  # notes currently on
        current_beat = 0.0  # current beat
        wait_time_synth_chords = 0  # time since last MIDI message in ticks

        # This assumes arrangement["synth_chords"] is sorted by beat
        for note in arrangement["synth_chords"]:
            if note["beat"] == current_beat:
                # notes falling on the same beat
                synth_chords_track.append(
                    Message(
                        'note_on',
                        note=note["note"],
                        velocity=note["velocity"],
                        channel=CHANNEL_SYNTH,
                        time=wait_time_synth_chords
                    )
                )
                wait_time_synth_chords = 0
                current_notes.append(note)
            else:
                # note off for currently on notes
                wait_time_synth_chords = int(
                    (note["beat"] - current_beat) * TICKS_PER_BEAT
                )
                current_beat = note["beat"]
                while current_notes:
                    current_note = current_notes.popleft()
                    synth_chords_track.append(
                        Message(
                            'note_off',
                            note=current_note["note"],
                            velocity=current_note["velocity"],
                            channel=CHANNEL_SYNTH,
                            time=wait_time_synth_chords
                        )
                    )
                    wait_time_synth_chords = 0

                # note falling on a new beat
                synth_chords_track.append(
                    Message(
                        'note_on',
                        note=note["note"],
                        velocity=note["velocity"],
                        channel=CHANNEL_SYNTH,
                        time=wait_time_synth_chords
                    )
                )
                current_notes.append(note)

        # clearing remaining on notes at the end of the bar
        beats_advanced = BAR_LENGTH_IN_BEATS - current_beat
        wait_time_synth_chords = int(beats_advanced * TICKS_PER_BEAT)

        while current_notes:
            current_note = current_notes.popleft()
            synth_chords_track.append(
                Message(
                    'note_off',
                    note=current_note["note"],
                    velocity=current_note["velocity"],
                    channel=CHANNEL_SYNTH,
                    time=wait_time_synth_chords
                )
            )
            wait_time_synth_chords = 0

    logger.info("Parsing synth chords arrangement completed")
    return mid


def render_midi_with_sfizz(
    midi_data: Any,
    sfz_path: Path,
    *,
    sample_rate: int,
    block_size: int,
    duration_sec: float,
) -> Any:
    """
    Render audio from MIDI through an SFZ instrument.

    Hints:
    - Python binding: ``import pysfizz`` (install the sfizz / pysfizz package).
    - Load the SFZ: ``synth = pysfizz.Synth(sample_rate=..., block_size=...)``
    - ``synth.load_sfz_file(str(sfz_path))``
    - Schedule note_on / note_off from your MIDI data at the correct sample offsets.
    - Pull blocks with ``synth.render(block_size)`` until ``duration_sec`` is covered.
    - Or use ``synth.render_note(...)`` for one-shot hits.
    - Peak-normalize the dry stem if levels are very quiet before returning.
    - Return a float32 numpy array shaped ``(num_samples, 2)`` (samples × stereo).
    """
    logger.info("Rendering MIDI via SFZ instrument at %s", sfz_path)

    if not sfz_path.is_file():
        logger.warning("SFZ not found at %s — returning silent stem stub", sfz_path)

    # TODO(candidate): load pysfizz, schedule events, render blocks into numpy audio

    return None  # stub — replace with rendered numpy array


def apply_master_chain(dry_audio: Any, sample_rate: int) -> Any:
    """
    Process the rendered mix through a Pedalboard master chain.

    Required effect order: Saturation → Compressor → Delay

    Hints:
    - ``from pedalboard import Pedalboard, Compressor, Delay, Distortion``
    - Saturation: ``Distortion(drive_db=6.0)`` or similar gentle saturation.
    - Compressor: set threshold, ratio, attack_ms, release_ms for bus glue.
    - Delay: ``Delay(delay_seconds=0.35, feedback=0.4, mix=0.25)``
    - Expect ``dry_audio`` as float32 shaped ``(num_samples, 2)``; return the same layout.
    - Pedalboard expects ``(channels, samples)``, so transpose around processing::

          board = Pedalboard([...])
          # Transpose before processing: Pedalboard expects (channels, samples).
          processed = board(dry_audio.T, sample_rate)
          # Transpose back to (num_samples, 2) for write_wav.
          return processed.T
    """
    logger.info("Applying master chain: Saturation → Compressor → Delay")

    # TODO(candidate): build Pedalboard chain in the order above and process audio

    return dry_audio  # stub — pass-through until implemented


def write_wav(path: Path, audio: Any, sample_rate: int) -> None:
    """Write stereo float audio to a 16-bit PCM WAV file.

    Expects ``audio`` as float32 shaped ``(num_samples, 2)``. Mono buffers shaped
    ``(num_samples,)`` are duplicated to stereo before export.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if audio is None:
        logger.error(
            "No audio buffer produced — rendering is incomplete (stub not replaced?)"
        )
        return

    import numpy as np

    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = np.column_stack([samples, samples])

    peak = np.max(np.abs(samples))
    if peak > 1.0:
        samples = samples / peak

    pcm = (samples * 32_767).astype(np.int16)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())

    logger.info("Wrote output WAV to %s", path)


def arrangement_duration_sec(arrangement: dict[str, Any]) -> float:
    """Derive render length from tempo and arrangement bar count."""
    beats_per_bar = 4
    return arrangement_bars(arrangement) * beats_per_bar * 60.0 / float(arrangement["tempo"])


def run_pipeline(arrangement: dict[str, Any]) -> Path:
    """Execute the full render pipeline and return the output WAV path."""
    logger.info("Starting render pipeline")

    midi_data = parse_arrangement_to_midi(arrangement)
    duration_sec = arrangement_duration_sec(arrangement)

    dry_audio = render_midi_with_sfizz(
        midi_data,
        SFZ_INSTRUMENT_PATH,
        sample_rate=SAMPLE_RATE,
        block_size=BLOCK_SIZE,
        duration_sec=duration_sec,
    )

    if dry_audio is None:
        logger.error("SFZ render returned no audio — implement render_midi_with_sfizz")
        sys.exit(1)

    mastered = apply_master_chain(dry_audio, SAMPLE_RATE)
    write_wav(OUTPUT_WAV_PATH, mastered, SAMPLE_RATE)

    logger.info("Pipeline complete")
    return OUTPUT_WAV_PATH


def main() -> None:
    configure_logging()
    verify_bundled_assets()
    output = run_pipeline(MOCK_ARRANGEMENT)
    logger.info("Done — inspect %s", output)


if __name__ == "__main__":
    main()
