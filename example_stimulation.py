"""
Reusable NeuroFUS stimulation module.

This module exposes `run_stimulation(params)` so the stimulation workflow can be
triggered by external callers such as `main_gui.py`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Event
from typing import Any

import serial
import serial.tools.list_ports

from neurofus_sdk import (
    nf_depth,
    nf_enforce_limits,
    nf_isppa,
    nf_open,
    nf_pulse_parameters,
    nf_ramp_dur,
    nf_ramp_mode,
    nf_start_timed,
    nf_stop_timed,
    nf_xdr_list,
    nf_xdr_select,
)


logger = logging.getLogger(__name__)


@dataclass
class PreparedStimulation:
    ser: serial.Serial
    connected_port: str
    firmware: str
    close_connection: bool
    stop_event: Event | None
    num_repetitions: int
    repetition_interval: float | None
    pulse_train_duration_s: float


def _find_neurofus_device() -> tuple[serial.Serial, str, str]:
    """Scan serial ports and return the first valid NeuroFUS connection."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        raise RuntimeError("No serial ports found. Check the NeuroFUS USB connection.")

    last_error: Exception | None = None
    for port_info in ports:
        try:
            ser, ok, firmware = nf_open(port_info.device)
            if ok:
                return ser, port_info.device, firmware
            ser.close()
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise RuntimeError(
            f"Unable to find a valid NeuroFUS device on available ports. Last error: {last_error}"
        ) from last_error
    raise RuntimeError("Unable to find a valid NeuroFUS device on available ports.")


def _require_param(params: dict[str, Any], key: str, expected_type: str) -> Any:
    """Fetch a required parameter and raise a clear error if it is missing."""
    if key not in params or params[key] is None:
        raise ValueError(f"Missing required parameter '{key}' ({expected_type}).")
    return params[key]


def _wait_until(deadline_seconds: float, stop_event: Event | None) -> bool:
    """Wait until a perf-counter deadline while remaining interruptible."""
    while True:
        if stop_event is not None and stop_event.is_set():
            return True

        remaining = deadline_seconds - time.perf_counter()
        if remaining <= 0:
            return stop_event is not None and stop_event.is_set()

        if remaining > 0.05:
            time.sleep(min(0.01, remaining - 0.02))
        elif remaining > 0.005:
            time.sleep(0.001)
        else:
            time.sleep(0)


def _abort_prepared_stimulation(prepared: PreparedStimulation) -> dict[str, Any]:
    """Abort sonication from the worker thread and return a standard status payload."""
    stop_result = nf_stop_timed(prepared.ser)
    return {
        "success": True,
        "message": f"Stimulation stopped by user on {prepared.connected_port}.",
        "aborted": True,
        "stop_command_at": stop_result.command_sent_at,
        "stop_ack_at": stop_result.response_received_at,
    }


def _total_stimulation_duration_s(prepared: PreparedStimulation) -> float:
    if prepared.num_repetitions <= 1:
        return prepared.pulse_train_duration_s
    return prepared.pulse_train_duration_s + (prepared.num_repetitions - 1) * (prepared.repetition_interval or 0.0)


def prepare_stimulation(params: dict[str, Any]) -> PreparedStimulation:
    """Open/configure the device so START can be issued at a precise later instant."""
    ser = params.get("ser")
    connected_port = params.get("connected_port")
    firmware = params.get("firmware", "")
    close_connection = params.get("close_connection", ser is None)
    using_existing_connection = ser is not None
    stop_event = params.get("stop_event")

    port = params.get("port")
    xdr_index = int(_require_param(params, "xdr_index", "int"))
    pd = float(_require_param(params, "pd", "float"))
    pri = float(_require_param(params, "pri", "float"))
    ptd = float(_require_param(params, "ptd", "float"))
    depth = float(_require_param(params, "depth", "float"))
    isppa = float(_require_param(params, "isppa", "float"))
    ramp_mode_value = int(_require_param(params, "ramp_mode", "int"))
    ramp_duration_us = float(_require_param(params, "ramp_duration_us", "float"))
    enforce_limits = bool(_require_param(params, "enforce_limits", "bool"))

    num_repetitions = int(params.get("num_repetitions", 1) or 1)
    repetition_interval = params.get("repetition_interval")

    if num_repetitions < 1:
        raise ValueError("num_repetitions must be at least 1.")
    if num_repetitions > 1 and repetition_interval is None:
        raise ValueError(
            "repetition_interval is required when num_repetitions is greater than 1."
        )
    if repetition_interval is not None:
        repetition_interval = float(repetition_interval)
        if repetition_interval <= 0:
            raise ValueError("repetition_interval must be greater than 0 seconds.")
        if repetition_interval < (ptd / 1000.0):
            raise ValueError(
                "repetition_interval must be greater than or equal to the pulse train "
                "duration (ptd / 1000)."
            )

    if not using_existing_connection:
        if port:
            ser, ok, firmware = nf_open(port)
            if not ok:
                raise RuntimeError(f"Failed to connect to NeuroFUS on port '{port}'.")
            connected_port = port
        else:
            ser, connected_port, firmware = _find_neurofus_device()
    elif connected_port is None:
        connected_port = "existing connection"

    try:
        print(f"Connected to NeuroFUS on {connected_port}. Firmware: {firmware}")

        xdr_list = nf_xdr_list(ser)
        print(f"Available transducers: {xdr_list}")
        selected_xdr = nf_xdr_select(ser, xdr_index)
        print(f"Selected transducer index: {selected_xdr}")

        confirmed_limits = nf_enforce_limits(ser, enforce_limits)
        print(f"Enforce limits set to: {confirmed_limits}")

        burst, confirmed_pri, duration = nf_pulse_parameters(ser, pd=pd, pri=pri, ptd=ptd)
        print(
            "Pulse parameters set: "
            f"PD={burst} ms, PRI={confirmed_pri} ms, PTD={duration} ms"
        )

        confirmed_depth = nf_depth(ser, depth)
        print(f"Depth set to: {confirmed_depth} mm")

        confirmed_isppa = nf_isppa(ser, isppa)
        print(f"ISPPA set to: {confirmed_isppa}")

        confirmed_ramp_mode = nf_ramp_mode(ser, ramp_mode_value)
        print(f"Ramp mode set to: {confirmed_ramp_mode}")

        if ramp_mode_value != 0 and ramp_duration_us > 0:
            # Converted from GUI ramp length in ms before this function is called.
            confirmed_ramp_duration = nf_ramp_dur(ser, ramp_duration_us)
            print(f"Ramp duration set to: {confirmed_ramp_duration} microseconds")
    except Exception:
        if ser is not None and close_connection:
            try:
                ser.close()
            except Exception as close_exc:
                print(f"Warning while closing serial connection: {close_exc}")
        raise

    return PreparedStimulation(
        ser=ser,
        connected_port=connected_port,
        firmware=firmware,
        close_connection=close_connection,
        stop_event=stop_event,
        num_repetitions=num_repetitions,
        repetition_interval=repetition_interval,
        pulse_train_duration_s=max(0.0, ptd / 1000.0),
    )


def execute_prepared_stimulation(
    prepared: PreparedStimulation,
    start_deadline: float | None = None,
) -> dict[str, Any]:
    """Issue START at the requested instant and wait through the planned duration."""
    first_start_command_at: float | None = None
    first_start_ack_at: float | None = None
    start_command_sent = False

    try:
        for index in range(prepared.num_repetitions):
            if prepared.stop_event is not None and prepared.stop_event.is_set():
                if first_start_command_at is None:
                    return {
                        "success": True,
                        "message": f"Stimulation stopped by user on {prepared.connected_port} before sonication started.",
                        "aborted_before_start": True,
                    }
                return _abort_prepared_stimulation(prepared)

            if index == 0:
                if start_deadline is not None and _wait_until(start_deadline, prepared.stop_event):
                    return {
                        "success": True,
                        "message": f"Stimulation stopped by user on {prepared.connected_port} before sonication started.",
                        "aborted_before_start": True,
                    }
            else:
                next_start_deadline = first_start_command_at + index * (prepared.repetition_interval or 0.0)
                if _wait_until(next_start_deadline, prepared.stop_event):
                    return _abort_prepared_stimulation(prepared)

            start_result = nf_start_timed(prepared.ser)
            start_command_sent = True
            if not start_result.success:
                raise RuntimeError(f"Device did not confirm stimulation start for repetition {index + 1}.")

            start_command_at = start_result.command_sent_at
            if first_start_command_at is None:
                first_start_command_at = start_command_at
            if first_start_ack_at is None:
                first_start_ack_at = start_result.response_received_at

            repetition_end_deadline = start_result.response_received_at + prepared.pulse_train_duration_s
            if _wait_until(repetition_end_deadline, prepared.stop_event):
                return _abort_prepared_stimulation(prepared)

        if first_start_command_at is None:
            raise RuntimeError("No stimulation repetitions were executed.")

        return {
            "success": True,
            "message": (
                f"Stimulation completed successfully on {prepared.connected_port} "
                f"with {prepared.num_repetitions} repetition(s)."
            ),
            "start_command_at": first_start_command_at,
            "start_ack_at": first_start_ack_at,
            "planned_end_at": first_start_ack_at + _total_stimulation_duration_s(prepared),
        }
    except Exception:
        if start_command_sent:
            try:
                nf_stop_timed(prepared.ser)
            except Exception as stop_exc:
                print(f"Warning while sending stop command: {stop_exc}")
        raise


def close_prepared_stimulation(prepared: PreparedStimulation | None) -> None:
    if prepared is None:
        return
    if prepared.ser is not None and prepared.close_connection:
        try:
            prepared.ser.close()
        except Exception as close_exc:
            print(f"Warning while closing serial connection: {close_exc}")


def run_stimulation(params: dict) -> dict[str, Any]:
    """
    Run a NeuroFUS stimulation session using GUI-provided parameters.

    Expected params keys:
        port (optional str)
        xdr_index (int)
        pd (float, ms)
        pri (float, ms)
        ptd (float, ms)
        depth (float, mm)
        isppa (float, W/cm^2)
        ramp_mode (int)
        ramp_duration_us (float, microseconds)
        enforce_limits (bool)
        num_repetitions (optional int)
        repetition_interval (optional float, seconds)
    """
    prepared: PreparedStimulation | None = None

    try:
        prepared = prepare_stimulation(params)
        return execute_prepared_stimulation(prepared)

    except Exception as exc:
        logger.exception("Stimulation failed")
        print(f"Error during stimulation: {exc}")
        return {
            "success": False,
            "message": str(exc),
        }

    finally:
        close_prepared_stimulation(prepared)
