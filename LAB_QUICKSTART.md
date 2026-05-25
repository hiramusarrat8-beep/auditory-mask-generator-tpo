# Lab Quick Start

This quick-start guide is a short cross-platform setup reference for lab members.
It does not replace the main `README.md`.

## 1. Get the Project

Clone the private repository or copy the project folder.

```bash
git clone <private-repo-url>
cd amg_app
```

If you are not using Git, copy the full project folder and open a terminal inside it.

## 2. Create the Conda Environment

```bash
conda env create -f environment.yml
conda activate amg_app
```

The environment file installs the Python packages from `requirements.txt`, so the Conda setup matches the manual `pip install -r requirements.txt` workflow.

## 3. Run the App

```bash
python main_gui.py
```

## Notes

- This project is intended to work on Windows, macOS, and Linux.
- The NeuroFUS device should be connected before starting a stimulation session.
- If audio playback or serial access fails, see the main `README.md` for troubleshooting notes.
