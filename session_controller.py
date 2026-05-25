# amg_app/session_controller.py
import numpy as np

import signal_generator

class SessionController:
    def generate(self, params, mode):
        train_total_s = 0
        if mode in ["Matching Only", "Combined"] and "train_duration" in params:
            # Existing validations for pulse and train
            prf = params["prf"]
            pw_ms = params["pulse_width"] * 1000
            ramp_ms = params["ramp_len"] * 1000
            pri_ms = 1000 / prf if prf > 0 else 0

            train_dur_ms = params.get("train_duration", 0)
            num_trains = params.get("num_trains", 1)
            train_int_ms = params.get("train_interval", 0)

            if train_dur_ms > 0:
                if num_trains < 1 or train_int_ms < 0:  # Changed to < 0 to allow =0
                    raise ValueError("Number of trains ≥ 1 and interval ≥ 0")
                train_total_s = num_trains * (train_dur_ms / 1000) + (num_trains - 1) * (train_int_ms / 1000)
            else:
                train_total_s = 0  # No train extension

            if pw_ms > pri_ms:
                raise ValueError("Pulse Width should be ≤ Pulse Repetition Interval")

            if params["ramp_shape"] != "None" and ramp_ms > pw_ms / 2:  # Conditioned on ramp_shape != "None"
                raise ValueError("Ramp length should be ≤ Pulse Width / 2")

            if train_dur_ms > 0 and train_dur_ms < pw_ms:
                raise ValueError("Train Duration should be ≥ Pulse Width")

        # Mode-specific prelim extension
        specified_ends = []
        if mode in ["Background Only", "Combined"] and params["bg_end_ms"] > 0:
            specified_ends.append(params["bg_end_ms"])
        if mode in ["Matching Only", "Combined"] and params["pulse_end_ms"] > 0:
            specified_ends.append(params["pulse_end_ms"])
        if specified_ends:
            max_ms = max(specified_ends)
            if max_ms > params["duration"] * 1000:
                params["duration"] = max_ms / 1000

        # Mode-specific train extension for duration
        if mode in ["Matching Only", "Combined"] and train_total_s > 0:
            params["duration"] = max(params["duration"], train_total_s)

        # FIXED: If ends flagged as -1 (empty), set to final duration
        if mode in ["Background Only", "Combined"] and params["bg_end_ms"] == -1:
            params["bg_end_ms"] = params["duration"] * 1000
        if mode in ["Matching Only", "Combined"] and params["pulse_end_ms"] == -1:
            params["pulse_end_ms"] = params["duration"] * 1000
        # Extra check: Ensure ends not less than starts
        if mode in ["Background Only", "Combined"] and params["bg_start_ms"] >= params["bg_end_ms"]:
            raise ValueError("Background start must be < end")
        if mode in ["Matching Only", "Combined"] and params["pulse_start_ms"] >= params["pulse_end_ms"]:
            raise ValueError("Pulse start must be < end")

        duration = params["duration"]

        # Extend duration to the end of the last full PRI so the final dead time isn't clipped.
        if mode in ["Matching Only", "Combined"]:
            prf = params.get("prf")
            if prf and prf > 0:
                pri = 1.0 / prf
                old_duration_ms = duration * 1000
                duration = np.ceil(duration / pri) * pri
                params["duration"] = duration
                if params.get("pulse_end_ms", 0) >= old_duration_ms:
                    params["pulse_end_ms"] = duration * 1000
                if mode == "Combined" and params.get("bg_end_ms", 0) >= old_duration_ms:
                    params["bg_end_ms"] = duration * 1000

        fs = params["fs"]
        carrier_freq = params["carrier_freq"]
        bg_type = params["bg_type"]
        bg_volume = params["bg_volume"]
        bg_start_ms = params["bg_start_ms"]
        bg_end_ms = params["bg_end_ms"]

        bg_audio = None
        pulse_audio = None
        gate = None
        t = None

        if mode == "Background Only":
            t = np.arange(0, duration, 1/fs)
            bg_audio = signal_generator.generate_continuous_background(
                duration,
                fs,
                bg_type,
                carrier_freq,
                params.get("bg_ramp_shape", "None"),
                params.get("bg_ramp_length", 0.0),
                params.get("prf"),
                params.get("hybrid_mask_settings"),
                params.get("mondrian_mask_settings"),
                {
                    "center_freq": params.get("bg_center_freq"),
                    "bandwidth": params.get("bg_bandwidth"),
                },
                {
                    "color": params.get("bg_noise_color"),
                },
            )
            bg_audio = signal_generator.apply_timing_gate(bg_audio, fs, bg_start_ms, bg_end_ms, duration)
            bg_audio *= bg_volume
            combined = bg_audio
            pulse_audio = None
            gate = None
        elif mode == "Matching Only":
            params["offset"] = params["pulse_start_ms"] / 1000
            if train_total_s > 0:
                shifted_end_s = params["offset"] + train_total_s
                # Keep the pulse timing gate open through the full repeated-train span.
                params["pulse_end_ms"] = max(params["pulse_end_ms"], shifted_end_s * 1000)
                if shifted_end_s > duration:
                    duration = shifted_end_s
                    params["duration"] = duration
            t, waveform, gate = signal_generator.generate_masking_sound(params)
            pulse_audio = waveform
            pulse_audio = signal_generator.apply_timing_gate(pulse_audio, fs, params["pulse_start_ms"], params["pulse_end_ms"], duration)
            pulse_audio *= params["pulse_volume"]
            combined = pulse_audio
            bg_audio = None
        elif mode == "Combined":
            params["offset"] = params["pulse_start_ms"] / 1000
            if train_total_s > 0:
                shifted_end_s = params["offset"] + train_total_s
                # Keep the pulse timing gate open through the full repeated-train span.
                params["pulse_end_ms"] = max(params["pulse_end_ms"], shifted_end_s * 1000)
                if shifted_end_s > duration:
                    duration = shifted_end_s
                    params["duration"] = duration
                    if params["bg_end_ms"] == params["duration"] * 1000:  # if was -1
                        params["bg_end_ms"] = duration * 1000
            t, waveform, gate = signal_generator.generate_masking_sound(params)
            pulse_audio = waveform
            pulse_audio = signal_generator.apply_timing_gate(pulse_audio, fs, params["pulse_start_ms"], params["pulse_end_ms"], duration)
            pulse_audio *= params["pulse_volume"]
            bg_audio = signal_generator.generate_continuous_background(
                duration,
                fs,
                bg_type,
                carrier_freq,
                params.get("bg_ramp_shape", "None"),
                params.get("bg_ramp_length", 0.0),
                params.get("prf"),
                params.get("hybrid_mask_settings"),
                params.get("mondrian_mask_settings"),
                {
                    "center_freq": params.get("bg_center_freq"),
                    "bandwidth": params.get("bg_bandwidth"),
                },
                {
                    "color": params.get("bg_noise_color"),
                },
            )
            bg_audio = signal_generator.apply_timing_gate(bg_audio, fs, bg_start_ms, bg_end_ms, duration)
            bg_audio *= bg_volume
            # Fixed headroom keeps both volume sliders perceptible in combined mode.
            combined = 0.5 * (pulse_audio + bg_audio)

        # Preserve user-set gains; only safety-scale if clipping.
        max_abs = np.max(np.abs(combined))
        if max_abs > 1.0:
            combined /= max_abs
            if pulse_audio is not None:
                pulse_audio /= max_abs
            if bg_audio is not None:
                bg_audio /= max_abs

        # Apply panning to make stereo.
        if "pan" in params:
            pan = float(params.get("pan", 0.0))
            pan = max(-1.0, min(1.0, pan))
            if pan <= 0:
                left_gain = 1.0
                right_gain = 1.0 + pan
            else:
                left_gain = 1.0 - pan
                right_gain = 1.0
            combined = np.column_stack((combined * left_gain, combined * right_gain))
        elif "left_pan" in params and "right_pan" in params:
            # Backward compatibility for older GUIs.
            left_pan = params["left_pan"]
            right_pan = params["right_pan"]
            combined = np.column_stack((combined * left_pan, combined * right_pan))
        else:
            combined = np.column_stack((combined, combined))

        return combined, t, gate, fs, pulse_audio, bg_audio
