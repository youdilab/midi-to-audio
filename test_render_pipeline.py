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
from mido import (
    Message,
    MidiFile,
    MidiTrack,
    MetaMessage,
    bpm2tempo,
    tempo2bpm,
    tick2second,
)
from collections import deque
import pysfizz
from typing import Dict, Tuple
import numpy as np
from pedalboard import Pedalboard, Compressor, Delay, Distortion

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

DEFAULT_BPM = 120
SECONDS_PER_MINUTE = 60


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
    Convert a JSON arrangement into a multi-track MIDI file.

    Builds a MidiFile with 3 tracks: metadata (tempo and time
    signature), drums (kick hits from the 16-step drum grid, repeated
    once per bar), and synth chords (note on/off pairs derived from
    beat-timed chord events).

    Args:
        arrangement: Parsed arrangement JSON containing:
            - "tempo": Tempo in BPM.
            - "length": Number of bars to render.
            - "drum_grid": 16-step list where a ``1`` marks a kick hit.
            - "synth_chords": List of chord notes, each with "note",
              "velocity", and "beat" (assumed sorted by beat).

    Returns:
        MidiFile: The assembled MIDI file, ready for rendering.
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
    Render a MIDI sequence to audio using an SFZ instrument via sfizz.

    Extracts note on/off events from every track in ``midi_data``, converts
    each note's timing to sample offsets using the MIDI file's tempo (or a
    default tempo if none is found), renders each note through the loaded
    SFZ instrument, and mixes the results into a single stereo buffer. The
    output is peak-normalized. If ``sfz_path`` doesn't exist, a silent stem
    of the requested duration is returned instead.

    Args:
        midi_data: A parsed ``mido.MidiFile`` (or equivalent) containing one
            or more tracks of note_on/note_off messages.
        sfz_path: Path to the ``.sfz`` instrument definition to render with.
        sample_rate: Output audio sample rate, in Hz.
        block_size: Block size used internally by the sfizz synth engine.
        duration_sec: Total duration of the rendered audio, in seconds.
            Notes starting after this point are skipped; notes extending
            past it are clipped to fit.

    Returns:
        np.ndarray: A float32 array of shape ``(num_samples, 2)``
        (samples x stereo channels) containing the rendered, normalized
        mix. Silent (all-zero) if ``sfz_path`` does not exist.
    """
    logger.info("Rendering MIDI via SFZ instrument at %s", sfz_path)

    if not sfz_path.is_file():
        logger.warning("SFZ not found at %s — returning silent stem stub", sfz_path)
        return np.zeros((int(duration_sec * sample_rate), 2), dtype=np.float32)

    synth = pysfizz.Synth(sample_rate=sample_rate, block_size=block_size)
    synth.load_sfz_file(str(sfz_path))

    # detecting tempo or falling back to default
    midi_tempo = None

    for midi_msg in midi_data.tracks[0]:
        if midi_msg.type == 'set_tempo':
            midi_tempo = midi_msg.tempo
            break

    if midi_tempo is None:
        midi_tempo = bpm2tempo(DEFAULT_BPM)
        logger.warning(
            "Tempo not found. Falling back to default tempo of %s",
            midi_tempo
        )

    midi_bpm = tempo2bpm(midi_tempo)
    logger.info("Detected MIDI tempo: %s microseconds per beat", midi_tempo)
    logger.info("BPM: %s", midi_bpm)

    samples_per_second = sample_rate
    beats_per_second = midi_bpm / SECONDS_PER_MINUTE  # 60 seconds per minute
    ticks_per_second = TICKS_PER_BEAT * beats_per_second
    samples_per_tick = samples_per_second / ticks_per_second

    MidiNoteData = Tuple[
        int,  # velocity
        float,  # start time in seconds
        float,  # duration in seconds
        int  # start sample
    ]
    MidiNoteEvents = Dict[int, MidiNoteData]  # note number -> MidiNoteData

    # extract note events from MIDI tracks and convert to sample offsets
    midi_notes = []

    for i, track in enumerate(midi_data.tracks):

        note_events: MidiNoteEvents = {}
        time_ticks = 0
        time_sec = 0.0

        logger.info("Reading track %s: %s", i, track.name)

        for midi_msg in track:
            if midi_msg.type == 'note_on' and midi_msg.velocity > 0:
                time_ticks += midi_msg.time
                time_sec = tick2second(time_ticks, TICKS_PER_BEAT, midi_tempo)
                note_events[midi_msg.note] = (
                    midi_msg.velocity,
                    time_sec,
                    None,
                    int(time_ticks * samples_per_tick)
                )
            elif midi_msg.type == 'note_off' or (midi_msg.type == 'note_on' and midi_msg.velocity == 0):
                time_ticks += midi_msg.time
                time_sec = tick2second(time_ticks, TICKS_PER_BEAT, midi_tempo)
                if midi_msg.note in note_events:
                    velocity, start_time, _, start_sample = note_events[
                        midi_msg.note
                    ]
                    midi_notes.append(
                        (
                            midi_msg.note,
                            velocity,
                            start_time,
                            time_sec - start_time,
                            start_sample,
                        )
                    )

    # render notes and mix
    duration_samples = int(duration_sec * sample_rate)
    rendered_mix = np.zeros((2, duration_samples), dtype=np.float32)

    tail_sec = 0.0  # extra time for note tails

    for midi_note in midi_notes:
        note = midi_note[0]
        velocity = midi_note[1]
        duration = midi_note[3]
        render_duration = duration + tail_sec
        start_sample = midi_note[4]

        rendered_note = synth.render_note(
            note,
            velocity,
            duration,
            render_duration
        )

        note_length_samples = rendered_note.shape[1]
        if start_sample >= duration_samples:
            logger.warning(
                "Note %s starts too late; skipping", note
            )
            continue

        if start_sample + note_length_samples > duration_samples:
            logger.warning(
                "Note %s exceeds total duration; clipping to fit", note
            )
            rendered_note = rendered_note[:, :duration_samples - start_sample]
            note_length_samples = rendered_note.shape[1]

        # add note to final mix
        rendered_mix[
            :,
            start_sample:(start_sample + note_length_samples)
        ] += rendered_note

    # peak normalize the final mix
    peak = np.max(np.abs(rendered_mix))
    if peak != 0:
        rendered_mix /= peak

    logger.info("%s MIDI notes rendered in total", len(midi_notes))

    # transpose to (num_samples, channels)
    rendered_mix_formatted = rendered_mix.T.astype(np.float32)

    return rendered_mix_formatted


def apply_master_chain(dry_audio: Any, sample_rate: int) -> Any:
    """
    Apply a fixed master processing chain to a rendered stereo mix 
    with hardcoded parameters.

    Runs the audio through a Pedalboard signal chain in a fixed order —
    Saturation (gentle distortion for warmth/glue), Compressor (bus
    compression), and Delay (feedback delay for space) and returns the
    processed result in the same layout as the input.

    Args:
        dry_audio: Unprocessed stereo mix as a float32 array shaped
            ``(num_samples, 2)``.
        sample_rate: Audio sample rate, in Hz.

    Returns:
        np.ndarray: The processed stereo mix, float32, shaped
        ``(num_samples, 2)`` — same layout as ``dry_audio``. Internally
        transposed to ``(channels, samples)`` for Pedalboard and back
        again before returning.
    """
    logger.info("Applying master chain: Saturation → Compressor → Delay")

    board = Pedalboard(
        [
            Distortion(drive_db=6.0),
            Compressor(
                threshold_db=-20,
                ratio=2,
                attack_ms=5,
                release_ms=100,
            ),
            Delay(delay_seconds=0.35, feedback=0.4, mix=0.25),
        ]
    )

    processed = board(dry_audio.T, sample_rate)
    logger.info("Applying master chain: Completed")
    return processed.T


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
