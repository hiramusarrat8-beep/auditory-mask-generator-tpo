# Auditory Mask Generator + NeuroFUS GUI

This project provides a PyQt6 GUI for:

* generating auditory masking sounds
* connecting to a NeuroFUS TPO device
* running `TUS Only` or `TUS + Mask` stimulation workflows
* previewing and saving generated audio
* saving and loading presets

## Main Features

* Audio generation modes:

  * `Background Only`
  * `Matching Only`
  * `Combined`
* Background types:

  * `Narrowband Noise`
  * `Colored Noise`
  * `Hybrid Ultrasound Mask`
  * `Auditory Mondrian`
* Playback controls:

  * `Play Audio`
  * `Stop Audio`
  * `Save`
  * `Presets`
  * `Reset`
* TPO controls:

  * automatic or manual serial-port selection
  * transducer listing after connect
  * NeuroFUS stimulation parameter entry
  * `Start Sonication`
  * `Stop Sonication`
* Stimulation modes:

  * `TUS Only`
  * `TUS + Mask` with pre-mask and post-mask timing
* Extra workflow support:

  * preset save/load for GUI state
  * audio/ultrasound/full reset actions
  * `TUS + Mask` execution log with elapsed-time events
  * double-click plot popups for enlarged waveform/spectral views
* Session saving:

  * generated `.wav`
  * metadata `.json`
  * optional component WAVs for combined output

## Project Files

Core files currently used by the app:

* [main\_gui.py](./main_gui.py): main PyQt6 GUI
* [session\_controller.py](./session_controller.py): builds audio sessions
* [signal\_generator.py](./signal_generator.py): signal generation utilities
* [utils.py](./utils.py): ramp/window helper functions
* [audio\_engine.py](./audio_engine.py): play, stop, save audio
* [plotting.py](./plotting.py): waveform and spectrum plots
* [example\_stimulation.py](./example_stimulation.py): NeuroFUS stimulation execution
* [stimulation\_mode.py](./stimulation_mode.py): coordinates `TUS Only` and `TUS + Mask`
* [neurofus\_sdk.py](./neurofus_sdk.py): SDK wrapper for NeuroFUS serial commands
* [logger.py](./logger.py): session metadata saving
* [preset\_manager.py](./preset_manager.py): preset save/load and reset actions



## Requirements

Install Python packages:

```bash
pip install -r requirements.txt
```

Current `requirements.txt` includes:

* `numpy`
* `scipy`
* `matplotlib`
* `PyQt6`
* `sounddevice`
* `pyserial`
* `colorednoise`

## Run

Start the GUI with:

```bash
python main\_gui.py
```

## Windows Setup Notes

If you are sharing this on Windows, these are the most common setup points:

* Use a recent Python 3 installation.
* Open the project in PowerShell or Command Prompt.
* Install dependencies with:

```bash
pip install -r requirements.txt
```

* Make sure the NeuroFUS device is connected by USB before trying to connect from the GUI.
* If the TPO device does not appear, unplug and reconnect it, then click `Refresh` in the GUI.
* If Windows assigned a COM port, the app can usually detect it automatically through the `Auto` option.
* If audio playback fails, confirm that the system has a working output device selected in Windows sound settings.
* If `sounddevice` has installation or runtime issues on another machine, updating `pip` and reinstalling the requirements usually helps:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

* If serial access fails, close any other app that may already be using the same COM port.

## macOS / Linux Notes

* Install dependencies the same way:

```bash
pip install -r requirements.txt
```

* Typical serial device names are:

  * macOS: `/dev/tty.usbmodem...` or `/dev/cu.usbmodem...`
  * Linux: `/dev/ttyACM0` or `/dev/ttyUSB0`
* The GUI `Auto` option should usually detect the NeuroFUS serial device if it is connected.
* On Linux, if serial access is denied, the user may need permission for serial devices, depending on system configuration.
* If audio playback does not work, confirm the correct output device is available and not blocked by another process.

## Typical Workflow

### Audio Only

1. Choose a playback mode.
2. Enter the sound parameters.
3. Click `Generate`.
4. Click `Play Audio` to preview.
5. Click `Save` to save the generated audio and metadata.
6. Use `Presets` to save or restore a parameter setup if needed.

### TUS Only

1. Connect the NeuroFUS device in the `TPO Connection` panel.
2. Confirm the status changes from `Disconnected` to `Connected: <port> (Firmware <version>)`.
3. Select a transducer.
4. Enter ultrasound parameters.
5. Set `Stimulation Mode` to `TUS Only`.
6. Click `Start Sonication`.

### TUS + Mask

1. Generate the masking audio first.
2. Connect the NeuroFUS device.
3. Enter ultrasound parameters.
4. Set `Stimulation Mode` to `TUS + Mask`.
5. Enter `Pre-Mask` and `Post-Mask` times if needed.
6. Click `Start Sonication`.

In `TUS + Mask` mode, the app:

* starts mask playback
* waits for the pre-mask delay
* starts sonication
* keeps the mask running through the requested timing
* stops audio automatically at the end

After a `TUS + Mask` run, the GUI can show an elapsed-time execution log for:

* mask start
* sonication start
* sonication stop
* mask stop

## Save Behavior

`Save` writes:

* the main generated WAV
* a JSON metadata sidecar
* extra component WAVs for combined output when available

The JSON contains:

* playback mode
* stimulation mode
* generation parameters
* saved filenames
* audio duration and sample rate
* current ultrasound/TPO settings summary
* execution log entries for `TUS + Mask` runs when available

## TPO Connection Notes

* The TPO port selector supports `Auto` plus manually detected serial ports.
* After connection, the GUI shows the connected port and firmware.
* `Start Sonication` is disabled until the TPO is connected.
* `Stop Sonication` is enabled only while a stimulation run is active.

## Notes

* `nf\_start()` on the NeuroFUS side is non-blocking.
* For repeated trains, the app handles repetition timing in Python.
* `Stop Sonication` is most useful for repeated trains or immediate abort requests.
* In `Full Burst View`, the red gate/envelope trace is a visibility-oriented summary for long-duration plotting, while `PRF Envelope Zoom` is the detailed local view.
* In `TUS + Mask` mode, make sure the generated audio is long enough to cover:

  * pre-mask
  * stimulation duration
  * post-mask

## Troubleshooting

### Transducer list is empty

* Make sure the TPO device is actually connected first.
* The transducer list is populated only after a successful TPO connection.

### Start Sonication is disabled

* Connect the TPO device first.

### Save is disabled

* Generate audio first.

### Stop Audio is disabled

* It starts disabled on app launch and becomes available after audio is generated.

