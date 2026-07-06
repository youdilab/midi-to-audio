# GluonForce Audio Engineer — Take-Home Assessment

Build a miniature **MIDI-to-audio rendering and mixing prototype** in Python. You will read a JSON arrangement, synthesize MIDI events, render them through an SFZ sampler, process the result with a master effect chain, and export a stereo WAV file.

**Target time:** 1 to 1.5 hours. Partial solutions with clear structure and comments are welcome.

## Quick start

Open a terminal **in this folder** (the directory that contains `test_render_pipeline.py` and `README.md`), then:

```bash
# Recommended — installs exact versions from uv.lock
uv sync --frozen --group dev
uv run python verify_environment.py
uv run python test_render_pipeline.py
```

The starter script exits with an error until you implement the `TODO(candidate)` sections — that is expected.

If you do not use [uv](https://docs.astral.sh/uv/), see **Requirements** below for a pip-based setup.

---

## Objective

Implement the pipeline sketched in `test_render_pipeline.py`:

1. **Parse** the mock JSON arrangement into MIDI note events (`mido`)
2. **Render** those events through an SFZ instrument (`sfizz` / `pysfizz`)
3. **Process** the dry mix with Spotify's `pedalboard` in this order:
   - Saturation
   - Compressor
   - Delay
4. **Export** a stereo file named `test_mix_output.wav` in this directory

The package includes runnable stubs with clear `TODO(candidate)` markers. The script verifies bundled assets on startup and exits non-zero until SFZ rendering returns audio (so a silent WAV is not mistaken for success).

---

## Provided Files

| File | Purpose |
|------|---------|
| `test_render_pipeline.py` | Main scaffold — implement the `TODO(candidate)` sections |
| `test_render_pipeline_checks.py` | Pytest suite to verify your implementation |
| `verify_environment.py` | Smoke-check Python, dependencies, and bundled assets after setup |
| `instruments/tr909/samples/placeholder.sfz` | Minimal SFZ mapping (kick on MIDI note 36) |
| `instruments/tr909/samples/kick.wav` | Bundled kick one-shot for the placeholder SFZ |
| `pyproject.toml` / `uv.lock` | Dependency manifest (uv) |
| `requirements.txt` | Same dependencies for pip users |
| `README.md` | This instruction manual |

---

## Requirements

- Python **3.11+** (required for this assessment because of the committed `uv.lock` and `pysfizz` wheel availability on common platforms)
- Packages:
  - [`mido`](https://mido.readthedocs.io/) — MIDI file construction
  - [`sfizz`](https://sfz.tools/sfizz/) via [`pysfizz`](https://pypi.org/project/pysfizz/) — SFZ sample rendering
  - [`pedalboard`](https://github.com/spotify/pedalboard) — master bus effects
  - [`numpy`](https://numpy.org/) — audio buffers (used by pedalboard and WAV export)
  - [`pytest`](https://docs.pytest.org/) — optional, for running the bundled checks

### Suggested setup ([uv](https://docs.astral.sh/uv/) — recommended)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if you do not have it yet, then from **this folder**:

```bash
# Create .venv and install exact versions from the committed uv.lock
uv sync --frozen --group dev

# Confirm Python, packages, and bundled samples are present
uv run python verify_environment.py

# Run scripts without manually activating the venv:
uv run python test_render_pipeline.py
uv run pytest test_render_pipeline_checks.py -v
```

Optional: activate the virtual environment the classic way:

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python verify_environment.py
python test_render_pipeline.py
pytest test_render_pipeline_checks.py -v
```

#### Fallback: pip + venv

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python verify_environment.py
```

> **Note:** Use `uv sync --frozen` on Python 3.11–3.13 for the best chance of a pre-built `pysfizz` wheel. If installation fails, document the blocker in your submission and keep your MIDI + pedalboard code complete.

### Sample asset

A short royalty-free `kick.wav` is bundled next to the placeholder SFZ:

```
instruments/tr909/samples/kick.wav
```

The SFZ maps MIDI note 36 to that sample. You may swap in your own one-shot if you prefer — see comments inside `placeholder.sfz` for mapping notes.

If `kick.wav` is missing, `test_render_pipeline.py` exits with a non-zero status before rendering.

---

## Running the Script

After `uv sync` (or pip install) and a passing `verify_environment.py`:

```bash
uv run python test_render_pipeline.py
```

On success you should see log lines for each pipeline stage and a file at:

```
test_mix_output.wav
```

Listen to the WAV and confirm you hear **kick hits** plus **audible master processing** (saturation, compression, delay).

> The placeholder SFZ only maps MIDI note 36 (kick). `synth_chords` entries use higher note numbers and will not produce audible SFZ output unless you add more `<region>` blocks or implement a separate synth path. Focus on kick rendering and the master chain for this exercise.

### Self-check with pytest

After implementing the pipeline, run:

```bash
uv run pytest test_render_pipeline_checks.py -v
```

The checks assert MIDI event counts, non-silent SFZ output, master-chain processing, and WAV export. They are expected to fail against the starter stubs.

---

## Mock Arrangement Schema

The scaffold uses an inline dictionary at the top of `test_render_pipeline.py`:

```python
{
    "tempo": 120,                          # BPM (integer)
    "length": 2,                           # number of bars to render
    "drum_grid": [1, 0, 0, ...],         # 16-step binary pattern (1 = hit)
    "synth_chords": [
        {"note": 60, "velocity": 90, "beat": 0.0},
        ...
    ],
}
```

- **`length`:** total bars to render. The pipeline duration is derived from this value.
- **`drum_grid`:** one bar of 16th notes; `1` triggers a kick (MIDI note 36 is a sensible default). **Repeat the same 16-step pattern for each bar** in `length` (bar 1 uses steps 0–15, bar 2 uses steps 16–31, and so on).
- **`synth_chords`:** polyphonic chord tones with MIDI note number, velocity, and start time in **quarter-note beats** (`"beat": 0.0` = downbeat of bar 1, `"beat": 2.0` = beat 3 of bar 1).

> **Schema note:** This assessment uses `"beat"` (quarter-note beats) for chord timing. Other codebases sometimes use `"step"` (16th-note steps) instead. Either convention is fine here — just stay consistent within your implementation.

You may extend the schema if it helps your design — just document any changes.

---

## Implementation Hints

### MIDI (`mido`)

- Create a `MidiFile` with at least one `MidiTrack` (the scaffold exposes `TICKS_PER_BEAT = 480`).
- Insert a tempo meta message from `arrangement["tempo"]`.
- Convert each active step in `drum_grid` to `note_on` / `note_off` pairs spaced by 16th-note durations, looping the grid once per bar in `length`.
- Map `synth_chords` entries to timed note events on a separate track or channel if you prefer.
- **Delta-time tip:** `mido` expects each message's `time` field to be ticks *since the previous message*, not an absolute position. A practical pattern: schedule events as `(absolute_tick, message)` pairs, sort by tick, then append with `message.copy(time=tick - previous_tick)`.

### SFZ render (`pysfizz`)

- Load `instruments/tr909/samples/placeholder.sfz` with a `pysfizz.Synth`.
- **Recommended for this exercise:** call `pysfizz.Synth.render_note()` for each scheduled drum hit (note, velocity, duration). The placeholder SFZ maps one-shot kick on MIDI note 36 — this path is simpler than block rendering and avoids voice-scheduling edge cases.
- Alternatively, schedule note events at sample offsets and accumulate `synth.render(block_size)` blocks until the arrangement duration elapses.

Return a **float32 numpy array shaped `(num_samples, 2)`** (samples × stereo channels). The bundled `write_wav` helper expects that layout and duplicates mono to stereo if needed.

> **Gain staging:** SFZ output can peak very quietly without post-render normalization. Peak-normalize the dry stem (or raise `amplitude` in the SFZ) so the master chain receives a sensible level before compression and delay.

### Audio buffer axis conventions

Different stages expect different channel layouts — transpose when moving between them:

| Stage | Expected shape |
|-------|----------------|
| `write_wav` helper | `(num_samples, 2)` — samples × stereo |
| `pysfizz.Synth.render_note()` | `(channels, samples)` — transpose before mixing |
| `pedalboard.Pedalboard(...)(audio, sr)` | `(channels, samples)` — transpose dry stem before processing |

A common failure mode is silent or corrupted output despite correct MIDI timing when these layouts are not reconciled.

### Master chain (`pedalboard`)

Apply effects **in this order**:

1. **Saturation** — e.g. `Distortion(drive_db=...)`
2. **Compressor** — bus glue settings
3. **Delay** — subtle echo / space

Use `logging` throughout — **do not use `print()`** for pipeline status.

---

## What to Submit

Return both of the following:

1. **Your completed `test_render_pipeline.py`** (with your implementations and any brief comments explaining design choices)
2. **`test_mix_output.wav`** produced by your script

Optional: a few sentences on what you would improve given more time (e.g. multi-stem mixing, proper SFZ voice management, unit tests).

---

## Evaluation Criteria

We look for:

- Correct pipeline structure and readable, PEP 8–friendly Python
- Working MIDI timing from the JSON mock data
- Successful SFZ rendering (even a single mapped drum is sufficient)
- Audible master chain in the specified effect order
- Sensible use of `logging` and relative file paths

Good luck — we are excited to hear your mix.
