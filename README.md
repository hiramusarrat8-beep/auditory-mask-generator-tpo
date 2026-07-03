# Auditory Mask Generator – NeuroFUS Edition
> Developed by Hira Musarrat and Dr. Benjamin Kop

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20681923.svg)](https://zenodo.org/doi/10.5281/zenodo.20681923)

> [!WARNING]
> This software is intended for research use only and should be operated only by trained users following institutional ultrasound safety guidelines. This software governed by an [End User License Agreement](EULA.md).

A PyQt6-based auditory masking GUI designed for transcranial ultrasound stimulation (TUS) experiments, supporting customizable masking paradigms and optional NeuroFUS-compatible stimulation workflow integration.

This version extends the standalone auditory mask generator by integrating:
- NeuroFUS system control
- NeuroFUS-compatible workflow support
- Ultrasound parameter synchronization with auditory stimuli
- Combined TUS + auditory masking execution modes

---

# Table of Contents

- [Screenshots of GUI](#screenshots-of-gui)
- [Tutorial video](#tutorial-video)
- [Stimulation Mode](#about-tus-+-mask-mode)
- [Installation](#installation)
- [Run the Application](#run-the-application)
- [Main Features](#main-features)
- [Project Files](#project-files)
- [Typical Workflow](#typical-workflow)
- [Save Behavior](#save-behavior)
- [Presets](#presets)
- [Requirements](#requirements)
- [Important Safety Notice](#important-safety-notice)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Citation](#citation)

---

# Screenshot of Main GUI

<img width="1596" height="895" alt="image" src="https://github.com/user-attachments/assets/32f4847b-3f96-4afe-9cd8-b321ec450bbf" />



# Tutorial video
[![Watch the tutorial](https://img.youtube.com/vi/gU6FDSrJ-Fk/maxresdefault.jpg)](https://www.youtube.com/watch?v=gU6FDSrJ-Fk)
---

# About TUS + Mask Mode:
Under **Stimulation Mode**, you can choose between two modes:

**• TUS:** Simply delivers ultrasound sonication using the parameters you have entered in the Ultrasound Parameters panel.

**• TUS + Mask:** This is one of my favourite features of the GUI. It allows ultrasound sonication and the auditory mask to be played together while letting you define the precise timing of the masking sound relative to the ultrasound stimulation.

To make the process transparent, we have also included a detailed **timestamped execution log**. This records how the timing unfolds during the sonication session, including mask onset, TUS start commands, device acknowledgement of sonication, planned pulse-train completion, and mask offset.

**Note:** The example below is a demonstration created to illustrate the timing information available in the GUI. The application also provides a **timeline view** for visualizing the sequence of events throughout the stimulation session.
<img width="1858" height="995" alt="image" src="https://github.com/user-attachments/assets/b965e8bd-d8a7-4649-8c21-c926a9a21286" />

<img width="1876" height="1043" alt="image" src="https://github.com/user-attachments/assets/8a508771-e429-42ea-b9cc-a6c74ee77842" />



# Installation

Make sure that Anaconda or Miniconda is installed before proceeding.

Clone the repository:

```bash
git clone https://github.com/hiramusarrat8-beep/auditory-mask-generator-tpo.git
```

Move into the project folder:

```bash
cd auditory-mask-generator-tpo
```

Create the Conda environment:

```bash
conda env create -f environment.yml
```

Activate the environment:

```bash
conda activate amg_app
```

The environment file installs the required Python packages from `requirements.txt`.

---

# Run the Application

```bash
python main_gui.py
```

---

# Main Features

## Audio Generation Modes

- `Matching Only`
- `Background Only`
- `Combined`

---

## Stimulation Matching Audio Controls

- pulse train duration
- PRI / PRF
- pulse duration
- carrier frequency
- ramp shape and ramp length
- signal-to-noise ratio
- pulse train repetition
- matching volume

---
## Background Types

- Broadband Noise
- Narrowband Noise
- Hybrid Ultrasound Mask
- Auditory Mondrian

---
## Background Audio Controls

- background duration
- background volume
- background ramping
- hybrid mask configuration
- Mondrian settings

---

## Spatialization

- pan/lateralization control
- left/right channel monitoring

---

## Visualization

- PRF envelope zoom
- full burst waveform view
- FFT view
- spectrogram view

---

## TPO / NeuroFUS Integration

- TPO connection management
- automatic COM port detection
- ultrasound parameter synchronization
- TUS-only mode
- TUS + Mask mode
- pre-mask and post-mask timing support

---

## Playback & File Actions

- `Generate`
- `Play`
- `Stop Audio`
- `Sonicate`
- `Stop Sonication`
- `Save WAV`
- `Preset Save/Load`

---

# Project Files

Core files used by the application:

- `main_gui.py` — main PyQt6 GUI
- `session_controller.py` — audio session orchestration
- `signal_generator.py` — signal generation utilities
- `audio_engine.py` — playback, stop, and WAV saving
- `plotting.py` — waveform and spectrum visualization
- `logger.py` — session metadata logging
- `preset_manager.py` — save/load/reset preset handling
- `example_stimulation.py` — TPO stimulation workflow integration
- `neurofus_sdk.py` — NeuroFUS SDK communication layer
- `utils.py` — helper utilities

---

# Typical Workflow

1. Connect the NeuroFUS/TPO device.
2. Select a playback mode.
3. Configure masking parameters.
4. Configure ultrasound parameters if using TUS mode.
5. Generate the masking audio.
6. Preview the audio if needed.
7. Start sonication using:
   - `TUS Only`
   - `TUS + Mask`
8. Save generated audio and metadata.

---

# Save Behavior

`Save` writes:

- generated WAV audio
- JSON metadata sidecar
- component WAVs for combined output when available

The JSON metadata contains:

- playback mode
- generation parameters
- saved filenames
- audio duration
- sample rate
- channel count

---

# Presets

Presets save only GUI configuration state, including:

- stimulation matching audio fields
- background audio fields
- hybrid mask settings
- Mondrian settings
- ramping controls
- volume sliders
- pan/lateralization
- graph display settings
- playback mode

---

# Requirements

Install Python packages manually if needed:

```bash
pip install -r requirements.txt
```

Current `requirements.txt` includes:

- numpy
- scipy
- matplotlib
- PyQt6
- sounddevice
- colorednoise

---

# Important Safety Notice

This software is intended for research use only.

Users are responsible for:
- validating all ultrasound parameters
- following institutional safety protocols
- verifying NeuroFUS/TPO device configuration before sonication
- ensuring safe stimulation operation
- ensuring proper synchronization between stimulation and masking playback

Never sonicate directly in air and always follow manufacturer safety recommendations.

The developers are not responsible for misuse of stimulation hardware or unsafe experimental configurations.

---

# Troubleshooting

## Audio playback fails

Confirm that the system has a working output device selected.

If `sounddevice` has installation/runtime issues:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## TPO connection not detected

- verify USB connection
- verify COM port access
- reconnect the device
- use the refresh connection button
- ensure no other application is controlling the TPO simultaneously

---

# License

This software is provided for non-commercial research use only.

By using this software, users agree to follow all applicable institutional, ethical, and ultrasound safety guidelines.

See the `LICENSE` file for full terms and conditions.

NeuroFUS SDK components and related hardware interfaces remain the property of their respective developers/manufacturers.

---
# Contact
 Email: hiramusarrat8@gmail.com or benjamin.kop@outlook.com
 
# Citation

If you use this GUI in research or academic work, please cite:

Hira Musarrat, Benjamin Kop  
Auditory Mask Generator – NeuroFUS Edition  
GitHub repository:  
https://github.com/hiramusarrat8-beep/auditory-mask-generator-tpo
