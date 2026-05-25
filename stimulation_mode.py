"""Coordinate TUS-only and TUS-plus-mask execution flows."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import audio_engine
from example_stimulation import (
    close_prepared_stimulation,
    execute_prepared_stimulation,
    prepare_stimulation,
    run_stimulation,
)
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


_SETTINGS_ORG = "AMG"
_SETTINGS_APP = "AuditoryMaskGenerator"
_MASK_NOTICE_KEY = "ui/tus_mask_notice_hidden"


class TusMaskNoticeDialog(QDialog):
    def __init__(self, parent, playback_mode):
        super().__init__(parent)
        self.setWindowTitle("TUS + Mask")
        self.setModal(True)
        self.resize(360, 150)

        layout = QVBoxLayout(self)

        label = QLabel(f"Masking type for TUS + Mask will be: {playback_mode}.")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.hide_checkbox = QCheckBox("Don't show again")
        layout.addWidget(self.hide_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def should_hide_future_notices(self):
        return self.hide_checkbox.isChecked()


def maybe_show_tus_mask_notice(parent, playback_mode):
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    if settings.value(_MASK_NOTICE_KEY, False, type=bool):
        return

    mode_text = playback_mode or "the currently generated playback mode"
    dialog = TusMaskNoticeDialog(parent, mode_text)
    dialog.exec()

    if dialog.should_hide_future_notices():
        settings.setValue(_MASK_NOTICE_KEY, True)


def _estimate_stimulation_duration_s(stimulation_params: dict[str, Any]) -> float:
    ptd_s = float(stimulation_params.get("ptd", 0.0)) / 1000.0
    repetitions = int(stimulation_params.get("num_repetitions", 1) or 1)
    repetition_interval = float(stimulation_params.get("repetition_interval", 0.0) or 0.0)
    if repetitions <= 1:
        return ptd_s
    return ptd_s + max(0, repetitions - 1) * repetition_interval


def _format_elapsed_event(elapsed_s: float, label: str) -> str:
    return f"+{elapsed_s:.3f} s  {label}"


def _run_tus_plus_mask(
    audio_data,
    sample_rate: int,
    stimulation_params: dict[str, Any],
    tus_start_ms: float,
    stop_event=None,
) -> dict[str, Any]:
    if audio_data is None:
        raise ValueError("Generate masking audio before running TUS + Mask mode.")
    if sample_rate is None:
        raise ValueError("Audio sample rate is missing for TUS + Mask mode.")

    tus_start_s = tus_start_ms / 1000.0

    if tus_start_s < 0:
        # TUS starts before mask: prepend silence so mask is delayed, both start at t=0.
        silence_samples = int(abs(tus_start_s) * sample_rate)
        if audio_data.ndim == 1:
            silence = np.zeros(silence_samples, dtype=audio_data.dtype)
        else:
            silence = np.zeros((silence_samples, audio_data.shape[1]), dtype=audio_data.dtype)
        audio_data = np.concatenate([silence, audio_data], axis=0)
        pre_tus_s = 0.0
        log_mask_start = f"Mask starts in {abs(tus_start_ms):.0f} ms (estimated audio onset)"
    else:
        # Mask starts before TUS: play audio then wait before sonication.
        pre_tus_s = tus_start_s
        log_mask_start = "Mask started (estimated audio onset)"

    required_duration_s = pre_tus_s + _estimate_stimulation_duration_s(stimulation_params)
    available_duration_s = len(audio_data) / float(sample_rate)

    if available_duration_s + 1e-9 < required_duration_s:
        raise ValueError(
            "Generated mask audio is shorter than the TUS start offset + stimulation duration. "
            "Increase the generated audio duration before starting TUS + Mask mode."
        )

    prepared_stimulation = None
    mask_stopped_at = None
    execution_log = []
    timeline_start = None
    stimulation_result = None

    try:
        prepared_stimulation = prepare_stimulation(stimulation_params)
        playback_info = audio_engine.play(audio_data, sample_rate) or {}
        timeline_start = playback_info.get("estimated_output_start_at", time.perf_counter())
        execution_log = [_format_elapsed_event(0.0, log_mask_start)]
        tus_start_deadline = timeline_start + pre_tus_s

        # Prepare all serial/device state before the mask timeline begins, then
        # schedule START against the audio-output timeline.
        stimulation_result = execute_prepared_stimulation(
            prepared_stimulation,
            start_deadline=tus_start_deadline,
        )

        start_command_at = stimulation_result.get("start_command_at")
        if start_command_at is not None:
            execution_log.append(
                _format_elapsed_event(max(0.0, start_command_at - timeline_start), "TUS START sent")
            )

        start_ack_at = stimulation_result.get("start_ack_at")
        if start_ack_at is not None:
            execution_log.append(
                _format_elapsed_event(
                    max(0.0, start_ack_at - timeline_start),
                    "TPO acknowledged sonication started",
                )
            )

        stop_command_at = stimulation_result.get("stop_command_at")
        if stop_command_at is not None:
            execution_log.append(
                _format_elapsed_event(max(0.0, stop_command_at - timeline_start), "ABORT sent")
            )

        stop_ack_at = stimulation_result.get("stop_ack_at")
        if stop_ack_at is not None:
            execution_log.append(
                _format_elapsed_event(max(0.0, stop_ack_at - timeline_start), "TPO acknowledged abort")
            )

        expected_end_at = stimulation_result.get("planned_end_at")
        if expected_end_at is not None:
            stop_elapsed = max(0.0, expected_end_at - timeline_start)
            execution_log.append(_format_elapsed_event(stop_elapsed, "Expected PTD end"))
        elif stop_ack_at is not None:
            stop_elapsed = max(0.0, stop_ack_at - timeline_start)
            execution_log.append(_format_elapsed_event(stop_elapsed, "Mask stopped"))
        elif stop_command_at is not None:
            stop_elapsed = max(0.0, stop_command_at - timeline_start)
            execution_log.append(_format_elapsed_event(stop_elapsed, "Mask stopped"))

        # TUS finished normally — let the mask play through its full configured duration.
        if not stimulation_result.get("aborted") and not stimulation_result.get("aborted_before_start"):
            audio_engine.wait()

    finally:
        audio_engine.stop()
        mask_stopped_at = time.perf_counter()
        close_prepared_stimulation(prepared_stimulation)

    if mask_stopped_at is not None and timeline_start is not None:
        execution_log.append(
            _format_elapsed_event(
                max(0.0, mask_stopped_at - timeline_start),
                "Mask stopped"
            )
        )

    if stimulation_result is None:
        stimulation_result = {}
    stimulation_result["execution_log"] = execution_log
    return stimulation_result


def run_stimulation_mode(
    stim_mode: str,
    stimulation_params: dict[str, Any],
    audio_data=None,
    sample_rate: int | None = None,
    tus_start_ms: float = 0.0,
) -> dict[str, Any]:
    """Dispatch execution for the selected stimulation mode."""
    stop_event = stimulation_params.get("stop_event")

    if stim_mode == "TUS Only":
        return run_stimulation(stimulation_params)

    if stim_mode == "TUS + Mask":
        return _run_tus_plus_mask(
            audio_data=audio_data,
            sample_rate=sample_rate,
            stimulation_params=stimulation_params,
            tus_start_ms=tus_start_ms,
            stop_event=stop_event,
        )

    raise ValueError(f"Unsupported stimulation mode: {stim_mode}")
