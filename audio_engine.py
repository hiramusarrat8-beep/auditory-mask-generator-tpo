# amg_app/audio_engine.py
import time

import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write

sd.default.latency = 'low'
sd.default.blocksize = 512

def play(audio, fs):
    audio_float32 = audio.astype(np.float32)
    requested_at = time.perf_counter()
    sd.play(audio_float32, fs)
    stream_started_at = time.perf_counter()

    time.sleep(0.02)

    latency_s = 0.0
    try:
        stream = sd.get_stream()
        raw_latency = getattr(stream, "latency", 0.0)
        if hasattr(raw_latency, "output"):
            latency_s = float(raw_latency.output or 0.0)
        else:
            latency_s = float(raw_latency or 0.0)
    except Exception:
        latency_s = 0.0

    blocksize_s = sd.default.blocksize / float(fs)
    latency_s = max(0.0, latency_s) + blocksize_s
    return {
        "requested_at": requested_at,
        "stream_started_at": stream_started_at,
        "latency_s": latency_s,
        "estimated_output_start_at": stream_started_at + latency_s,
    }

def get_default_sample_rate():
    try:
        device_info = sd.query_devices(kind='output')
        return int(device_info.get('default_samplerate') or 44100)
    except Exception:
        return 44100

def stop():
    sd.stop()

def wait():
    sd.wait()

def save_wav(audio, fs, filepath):
    audio_int16 = np.int16(audio * 32767)
    write(filepath, fs, audio_int16)
