# amg_app/signal_generator.py
import numpy as np
import colorednoise
from scipy.signal import square, butter, sosfiltfilt

from utils import linear_ramp_window, tukey_ramp_window, exponential_ramp_window, logarithmic_ramp_window

def generate_masking_sound(params):
    fs = params["fs"]
    duration = params["duration"]
    carrier_freq = params["carrier_freq"]
    enable_carrier = params.get("enable_carrier", True)
    prf = params["prf"]
    pulse_width = params["pulse_width"]
    snr = params["snr"]
    ramp_len = params["ramp_len"]
    ramp_shape = params["ramp_shape"]
    train_duration = params.get("train_duration", None)
    num_trains = params.get("num_trains", 1)
    train_interval = params.get("train_interval", None)
    offset = params.get("offset", 0)  # Offset in seconds for pulse start

    offset_samples = int(offset * fs)
    samples_per_pulse = int(fs / prf) if prf > 0 else 0
    pulse_samples = int(pulse_width * fs)
    ramp_samples = int(ramp_len * fs)

    if pulse_samples <= 2:
        raise ValueError("Pulse width too small for given sampling rate.")

    t = np.arange(0, duration, 1/fs)
    carrier = np.sin(2 * np.pi * carrier_freq * t)

    signal = np.zeros_like(t)
    gate = np.zeros_like(t)

    # Pulse gate with offset
    if ramp_shape == "None":
        # Shift the modulation by offset
        gate[offset_samples:] = (np.mod(t[offset_samples:] - offset, 1/prf) < pulse_width).astype(float)
    else:
        ramp_samples = min(ramp_samples, pulse_samples // 2)
        if ramp_shape == "Linear":
            window = linear_ramp_window(pulse_samples, ramp_samples)
        elif ramp_shape == "Tukey":
            window = tukey_ramp_window(pulse_samples, ramp_samples)
        elif ramp_shape == "Exponential":
            window = exponential_ramp_window(pulse_samples, ramp_samples)
        elif ramp_shape == "Logarithmic":
            window = logarithmic_ramp_window(pulse_samples, ramp_samples)
        else:
            raise ValueError(f"Unknown ramp shape: {ramp_shape}")

        # Start pulsing from offset
        current_start = offset_samples
        while current_start < len(t):
            end = min(current_start + pulse_samples, len(t))
            slice_len = end - current_start
            if slice_len > 0:
                gate[current_start:end] = window[:slice_len]
            current_start += samples_per_pulse

    # Train gating (pure silence between trains), starting from offset
    if train_duration is not None and train_interval is not None:
        train_samples = int(train_duration * fs / 1000)
        train_interval_samples = int(train_interval * fs / 1000)
        train_gate = np.zeros_like(t)
        current = offset_samples
        for _ in range(int(num_trains)):
            end = min(current + train_samples, len(t))
            if end > current:
                train_gate[current:end] = 1
            current += train_samples + train_interval_samples
            if current >= len(t):
                break
        gate *= train_gate

    # Signal
    if enable_carrier:
        signal = carrier * gate
    else:
        signal = gate.copy()

    # Noise ONLY during active gate periods
    if snr is not None:
        noise = np.random.randn(len(signal))
        signal_rms = np.sqrt(np.mean(signal ** 2)) if np.any(signal) else 1e-10
        noise_rms  = np.sqrt(np.mean(noise ** 2))  if np.any(noise)  else 1e-10
        noise *= (signal_rms / (snr * noise_rms)) if noise_rms > 0 else 0
        waveform = signal + noise * gate   # noise gated
    else:
        waveform = signal

    # Normalize
    max_abs = np.max(np.abs(waveform))
    if max_abs > 0:
        waveform /= max_abs

    return t, waveform, gate

def bandpass_filter(data, lowcut, highcut, fs, order=4):
    low = max(lowcut, 1.0)
    high = min(highcut, fs / 2 - 1.0)
    if low >= high:
        return np.zeros_like(data)
    sos = butter(order, [low, high], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, data)

def prf_mask(duration, sr, prf, harmonics=10, bandwidth=200):
    samples = int(duration * sr)
    mask = np.zeros(samples)

    for harmonic in range(1, int(harmonics) + 1):
        center = prf * harmonic
        low = center - bandwidth
        high = center + bandwidth

        if high >= sr / 2:
            break

        noise = np.random.randn(samples)
        mask += bandpass_filter(noise, low, high, sr)

    return mask

def mondrian_mask(duration, sr, density=4, tone_duration=0.5):
    samples = int(duration * sr)
    mask = np.zeros(samples)
    tone_samples = max(1, int(tone_duration * sr))
    tones = max(1, int(duration * density))

    if tone_samples >= samples:
        tone_samples = samples

    for _ in range(tones):
        t = np.arange(tone_samples) / sr
        carrier = np.sin(2 * np.pi * 15000 * t)
        prf = np.random.uniform(1000, 15000)
        pulse = square(2 * np.pi * prf * t, duty=0.5)
        tone = carrier * pulse

        start = 0 if samples == tone_samples else np.random.randint(0, samples - tone_samples)
        mask[start:start + tone_samples] += tone

    return mask

def generate_auditory_mondrian_mask(duration, sr, density=8, tone_duration=0.5,
                                    pf_min=20, pf_max=15000,
                                    prf_min=1000, prf_max=15000, duty=0.5):
    samples = int(duration * sr)
    mask = np.zeros(samples)
    tone_samples = max(1, int(tone_duration * sr))
    tones = max(1, int(duration * density))

    if tone_samples >= samples:
        tone_samples = samples

    pf_low, pf_high = sorted((pf_min, pf_max))
    prf_low, prf_high = sorted((prf_min, prf_max))

    for _ in range(tones):
        t = np.arange(tone_samples) / sr
        carrier_freq = np.random.uniform(pf_low, pf_high)
        carrier = np.sin(2 * np.pi * carrier_freq * t)
        prf = np.random.uniform(prf_low, prf_high)
        pulse = square(2 * np.pi * prf * t, duty=duty)
        tone = carrier * pulse

        start = 0 if samples == tone_samples else np.random.randint(0, samples - tone_samples)
        mask[start:start + tone_samples] += tone

    max_abs = np.max(np.abs(mask))
    if max_abs > 0:
        mask = mask / max_abs

    return mask

def broadband_mask(duration, sr):
    samples = int(duration * sr)
    noise = np.random.randn(samples)
    return bandpass_filter(noise, 500, 18000, sr)


def generate_colored_noise(duration, sr, color_name):
    color_exponents = {
        "White": 0.0,
        "Pink": 1.0,
        "Brown": 2.0,
        "Blue": -1.0,
        "Violet": -2.0,
    }
    beta = color_exponents.get(color_name, 0.0)
    samples = max(1, int(duration * sr))
    noise = colorednoise.powerlaw_psd_gaussian(beta, samples)
    return np.asarray(noise, dtype=float)

def generate_hybrid_mask(duration=10, sr=44100, prf=1000, harmonics=10, bandwidth=200,
                         mondrian_density=4, mondrian_tone_duration_ms=500,
                         prf_mask_weight=0.5, mondrian_weight=0.3, broadband_weight=0.2):
    prf_layer = prf_mask(duration, sr, prf, harmonics=harmonics, bandwidth=bandwidth)
    mondrian_layer = mondrian_mask(
        duration,
        sr,
        density=mondrian_density,
        tone_duration=mondrian_tone_duration_ms / 1000.0,
    )
    broadband_layer = broadband_mask(duration, sr)

    mask = (
        prf_mask_weight * prf_layer
        + mondrian_weight * mondrian_layer
        + broadband_weight * broadband_layer
    )

    max_abs = np.max(np.abs(mask))
    if max_abs > 0:
        mask = mask / max_abs

    return mask

def generate_continuous_background(duration, fs, bg_type, carrier_freq=0, bg_ramp_shape="None", bg_ramp_length=0.0,
                                   prf=None, hybrid_settings=None, mondrian_settings=None,
                                   narrowband_settings=None, colored_noise_settings=None):
    n = int(duration * fs)
    t = np.arange(n) / fs
    if bg_type == "White Noise":
        bg = generate_colored_noise(duration, fs, "White")
    elif bg_type == "Narrowband Noise":
        narrowband_settings = narrowband_settings or {}
        center_freq = float(narrowband_settings.get("center_freq", 1000.0))
        bandwidth = float(narrowband_settings.get("bandwidth", 100.0))
        noise = np.random.randn(n)
        lowcut = max(1.0, center_freq - bandwidth / 2.0)
        highcut = center_freq + bandwidth / 2.0
        bg = bandpass_filter(noise, lowcut, highcut, fs)
    elif bg_type == "Colored Noise":
        colored_noise_settings = colored_noise_settings or {}
        bg = generate_colored_noise(duration, fs, colored_noise_settings.get("color", "White"))
    elif bg_type == "Hybrid Ultrasound Mask":
        hybrid_settings = hybrid_settings or {}
        bg = generate_hybrid_mask(
            duration=duration,
            sr=fs,
            prf=prf if prf is not None else 1000,
            harmonics=hybrid_settings.get("prf_harmonics", 10),
            bandwidth=hybrid_settings.get("harmonic_bandwidth", 200),
            mondrian_density=hybrid_settings.get("mondrian_density", 4),
            mondrian_tone_duration_ms=hybrid_settings.get("mondrian_tone_duration_ms", 500),
            prf_mask_weight=hybrid_settings.get("prf_mask_weight", 0.5),
            mondrian_weight=hybrid_settings.get("mondrian_weight", 0.3),
            broadband_weight=hybrid_settings.get("broadband_weight", 0.2),
        )
    elif bg_type == "Auditory Mondrian":
        mondrian_settings = mondrian_settings or {}
        bg = generate_auditory_mondrian_mask(
            duration=duration,
            sr=fs,
            density=mondrian_settings.get("density", 8),
            tone_duration=mondrian_settings.get("tone_duration_ms", 500) / 1000.0,
            pf_min=mondrian_settings.get("pf_min", 20),
            pf_max=mondrian_settings.get("pf_max", 15000),
            prf_min=mondrian_settings.get("prf_min", 1000),
            prf_max=mondrian_settings.get("prf_max", 15000),
            duty=mondrian_settings.get("duty_cycle", 50) / 100.0,
        )
    else:
        raise ValueError(f"Unknown background type: {bg_type}")

    if bg_ramp_shape != "None" and bg_ramp_length > 0:
        ramp_samples = min(int(bg_ramp_length * fs), n // 2)
        if ramp_samples > 0:
            if bg_ramp_shape == "Linear":
                bg_window = linear_ramp_window(n, ramp_samples)
            elif bg_ramp_shape == "Tukey":
                bg_window = tukey_ramp_window(n, ramp_samples)
            else:
                raise ValueError(f"Unknown background ramp shape: {bg_ramp_shape}")
            bg = bg * bg_window

    max_abs = np.max(np.abs(bg))
    if max_abs > 0:
        bg /= max_abs
    return bg

def apply_timing_gate(waveform, fs, start_ms, end_ms, duration):
    start_sample = int(start_ms * fs / 1000)
    end_sample = int(end_ms * fs / 1000) if end_ms > 0 else int(duration * fs)
    gate = np.zeros_like(waveform)
    gate[start_sample:end_sample] = 1
    return waveform * gate

def generate_background_sound(duration, fs, level=0.15):
    n = int(duration * fs)
    background = np.random.randn(n)
    background /= np.max(np.abs(background)) if np.max(np.abs(background)) > 0 else 1
    return background * level
