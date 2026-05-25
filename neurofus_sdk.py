"""
neurofus_sdk.py
Python SDK for NeuroFUS TPO (Transducer Power Output) control via serial communication.

Translated from the original MATLAB NeuroFUS SDK (NeuroFUS/).

Functions translated from MATLAB:
    nf_open             <- NFOpen.m
    nf_accept_eula      <- NFAcceptEULA.m
    nf_xdr_list         <- NFXDRList.m
    nf_xdr_select       <- NFXDRSelect.m
    nf_pulse_parameters <- NFPulseParameters.m  (calls NFBurstLength, NFPulseRepPeriod, NFDuration)
    nf_depth            <- NFDepth.m            (calls NFFocusRange)
    nf_isppa            <- NFIsppa.m            (calls ReadNFUS* query helpers)
    nf_ramp_mode        <- NFRampMode.m
    nf_ramp_dur         <- NFRampDur.m
    nf_start            <- NFStart.m
    nf_stop             <- NFStop.m

Requirements:
    pip install pyserial

Basic usage:
    from neurofus_sdk import nf_open, nf_accept_eula, nf_xdr_list, nf_xdr_select
    from neurofus_sdk import nf_pulse_parameters, nf_depth, nf_isppa
    from neurofus_sdk import nf_ramp_mode, nf_ramp_dur, nf_start, nf_stop

    # Connect (Windows: 'COM3', macOS: '/dev/tty.usbmodemXXXX', Linux: '/dev/ttyACM0')
    ser, ok, firmware = nf_open('COM3')
    nf_accept_eula(ser)

    # Choose transducer
    transducers = nf_xdr_list(ser)
    nf_xdr_select(ser, 0)

    # Configure stimulation
    nf_pulse_parameters(ser, pd=5.0, pri=100.0, ptd=500.0)   # all in ms
    nf_depth(ser, 50.0)                                        # mm
    nf_isppa(ser, 3.0)                                         # W/cm²
    nf_ramp_mode(ser, 2)                                       # 2 = Tukey
    nf_ramp_dur(ser, 5 * 1000)                                 # ramp_length_ms * 1000 -> µs

    # Sonicate
    nf_start(ser)
    # ... (apply your own pulse-train repetition timing here if needed)
    nf_stop(ser)

    ser.close()
"""

import time
import logging
from dataclasses import dataclass
import serial

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NeuroFusCommandResult:
    success: bool
    command_sent_at: float
    response_received_at: float | None
    response: str

MAX_WAIT_TIME = 7.0    # seconds — timeout waiting for device response
POLL_INTERVAL = 0.01   # seconds — polling interval when waiting for data


# =============================================================================
# Low-level serial helpers
# =============================================================================

def _write(ser: serial.Serial, cmd: str) -> None:
    """Send a command string to the NeuroFUS device (CR/LF terminated)."""
    try:
        ser.write((cmd + '\r\n').encode('ascii'))
        logger.info("Sent to NeuroFUS: %s", cmd)
    except serial.SerialException as exc:
        logger.error("Could not write to serial: %s", exc)
        raise


def _read(ser: serial.Serial) -> str:
    """Read one response line from the NeuroFUS device, stripped of whitespace."""
    try:
        line = ser.readline().decode('ascii', errors='replace').strip()
        logger.info("Read from NeuroFUS: %s", line)
        return line
    except serial.SerialException as exc:
        logger.error("Exception reading from serial: %s", exc)
        raise


def _run_command_with_ack(
    ser: serial.Serial,
    command: str,
    expected_response_text: str,
    success_message: str,
    unexpected_message: str,
    error_message: str,
) -> NeuroFusCommandResult:
    ser.reset_input_buffer()
    command_sent_at = time.perf_counter()
    _write(ser, command)
    _wait_for_data(ser)
    try:
        response = _read(ser)
        response_received_at = time.perf_counter()
        success = expected_response_text in response
        if success:
            logger.info(success_message, response)
        else:
            logger.warning(unexpected_message, response)
        return NeuroFusCommandResult(
            success=success,
            command_sent_at=command_sent_at,
            response_received_at=response_received_at,
            response=response,
        )
    except Exception as exc:
        logger.error(error_message, exc)
        return NeuroFusCommandResult(
            success=False,
            command_sent_at=command_sent_at,
            response_received_at=None,
            response="",
        )


def _wait_for_data(ser: serial.Serial, timeout: float = MAX_WAIT_TIME) -> None:
    """Block until at least one byte is available in the receive buffer."""
    deadline = time.time() + timeout
    while ser.in_waiting == 0:
        if time.time() > deadline:
            raise TimeoutError("Timeout: No response received from the NeuroFUS device.")
        time.sleep(POLL_INTERVAL)


def _parse_first_number(response: str) -> float:
    """Return the first parseable float found in a space-delimited response string."""
    for part in response.split():
        try:
            return float(part)
        except ValueError:
            continue
    raise ValueError(f"No valid number found in response: {response!r}")


# =============================================================================
# Internal device queries  (ReadNFUS*.m equivalents)
# =============================================================================

def _read_nfus_burst(ser: serial.Serial) -> float:
    """Query the current burst length from the device (returns value in device units)."""
    ser.reset_input_buffer()
    _write(ser, 'BURST?')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Read BurstLength: %f", value)
    return value


def _read_nfus_period(ser: serial.Serial) -> float:
    """Query the current pulse repetition period from the device (returns value in device units)."""
    ser.reset_input_buffer()
    _write(ser, 'PERIOD?')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Read Period: %f", value)
    return value


def _read_nfus_enforce_limits(ser: serial.Serial) -> float:
    """Query whether safety limits are enforced. Returns > 0 when enforced."""
    ser.reset_input_buffer()
    _write(ser, 'ENFORCELIMITS?')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Read EnforceLimits: %f", value)
    return value


def _read_nfus_isppa_max(ser: serial.Serial) -> float:
    """Query the maximum allowed Isppa from the device (returns value in W/cm²)."""
    ser.reset_input_buffer()
    _write(ser, 'SPPALIMIT')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Read IsppaMax: %f", value)
    return value


def _read_nfus_ispta_max(ser: serial.Serial) -> float:
    """Query the maximum allowed Ispta from the device (returns value in W/cm²)."""
    ser.reset_input_buffer()
    _write(ser, 'SPTALIMIT')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Read IsptaMax: %f", value)
    return value


def _read_nfus_focus_range(ser: serial.Serial) -> tuple:
    """
    Query the focus steering range of the currently selected transducer.

    Returns:
        (min_mm, max_mm)
    """
    ser.reset_input_buffer()
    _write(ser, 'RANGE?')
    _wait_for_data(ser)
    response = _read(ser)
    parts = response.split(',')
    values = []
    for part in parts[:2]:
        try:
            values.append(float(part.strip()))
        except ValueError:
            values.append(float('nan'))
    if len(values) < 2 or any(v != v for v in values):  # nan check
        raise ValueError(f"Invalid focus range values in response: {response!r}")
    logger.info("Focus range: Min = %f mm, Max = %f mm", values[0], values[1])
    return values[0], values[1]


# =============================================================================
# Internal parameter setters  (NFBurstLength, NFPulseRepPeriod, NFDuration)
# =============================================================================

def _nf_burst_length(ser: serial.Serial, burst_ms: float) -> float:
    """
    Set the pulse (burst) duration on the device.

    Args:
        ser:      Open serial.Serial object.
        burst_ms: Pulse duration in milliseconds.

    Returns:
        Confirmed burst value from device.
    """
    burst_us = burst_ms * 1000  # ms -> µs
    if burst_us > 120_000_000:
        raise ValueError("Burst length too large. Enter a value less than 120,000,000 µs.")
    if burst_us < 10:
        raise ValueError("Burst length too small. Enter a value greater than 10 µs.")
    ser.reset_input_buffer()
    _write(ser, f'BURST={burst_us:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Pulse duration set to: %f µs", value)
    return value


def _nf_pulse_rep_period(ser: serial.Serial, prp_ms: float) -> float:
    """
    Set the pulse repetition period on the device.

    Args:
        ser:    Open serial.Serial object.
        prp_ms: Pulse repetition period in milliseconds.

    Returns:
        Confirmed PRP value from device.
    """
    prp_us = prp_ms * 1000  # ms -> µs
    if prp_us < 10:
        raise ValueError("PRP too low. Enter a value > 10 µs.")
    if prp_us > 1_000_000:
        raise ValueError("PRP too high. Enter a value < 1,000,000 µs (1000 ms).")
    ser.reset_input_buffer()
    _write(ser, f'PERIOD={prp_us:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Pulse repetition period set to: %f ms", value)
    return value


def _nf_duration(ser: serial.Serial, ptd_ms: float) -> float:
    """
    Set the pulse train duration on the device.

    Args:
        ser:    Open serial.Serial object.
        ptd_ms: Pulse train duration in milliseconds.

    Returns:
        Confirmed PTD value from device.
    """
    if ptd_ms > 600_000:
        raise ValueError("Duration too high. Must be <= 600,000 ms (600 s).")
    if ptd_ms < 1:
        raise ValueError("Duration too low. Must be >= 1 ms.")
    ptd_us = ptd_ms * 1000  # ms -> µs
    ser.reset_input_buffer()
    _write(ser, f'TIMER={ptd_us:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Pulse train duration set to: %f ms", value)
    return value


# =============================================================================
# Public API — NFOpen, NFAcceptEULA
# =============================================================================

def _nf_check_conn(ser: serial.Serial) -> tuple:
    """
    Check whether the device responded with its firmware banner.

    Returns:
        (ok, firmware): ok is True if device replied with 'TPO ...', firmware is version string.
    """
    response = _read(ser)
    if response.startswith('TPO'):
        parts = response.split(' Version_', 1)
        firmware = parts[1] if len(parts) > 1 else ''
        return True, firmware
    return False, ''


def nf_open(port: str, advanced: int = None) -> tuple:
    """
    Open a serial connection to the NeuroFUS TPO device.

    Equivalent to: [NFUS, NFOK, TPOFirm] = NFOpen('COM3')

    Args:
        port:     Serial port string.
                  Windows: 'COM3', 'COM5', etc.
                  macOS:   '/dev/tty.usbmodemXXXX'  or  '/dev/cu.usbmodemXXXX'
                  Linux:   '/dev/ttyACM0', '/dev/ttyUSB0', etc.
        advanced: Optional integer.
                  1 = enable advanced mode (independent element phase/power/frequency control).
                  0 = disable advanced mode.
                  None (default) = do not send LOCAL command.

    Returns:
        (ser, ok, firmware):
            ser      – open serial.Serial object; pass to all other SDK functions.
            ok       – True if the device responded correctly.
            firmware – firmware version string reported by the device.
    """
    ser = serial.Serial(
        port=port,
        baudrate=115200,
        bytesize=serial.EIGHTBITS,
        stopbits=serial.STOPBITS_ONE,
        timeout=7,
    )
    # Wait for the device to send its power-on banner
    _wait_for_data(ser)
    ok, firmware = _nf_check_conn(ser)

    if advanced is not None:
        cmd = 'LOCAL=0' if advanced == 1 else 'LOCAL=1'
        _write(ser, cmd)
        _wait_for_data(ser)
        _read(ser)
        if advanced == 1:
            logger.info(
                "Advanced remote control enabled. "
                "Phase, power, and frequency of each element can be independently configured."
            )

    return ser, ok, firmware


def nf_accept_eula(ser: serial.Serial) -> str:
    """
    Accept the EULA on the NeuroFUS device, enabling sonication.

    Equivalent to: NFAcceptEULA(NFUS)

    Args:
        ser: Open serial.Serial object (from nf_open).

    Returns:
        Response string from the device.
    """
    command = 'ACCEPTEULA'
    logger.info("Sending command: %s", command)
    _write(ser, command)
    _wait_for_data(ser)
    try:
        response = _read(ser)
    except Exception as exc:
        logger.error("Failed to read response: %s", exc)
        response = ''
    logger.info("Response received: %s", response)
    return response


# =============================================================================
# Public API — Transducer selection
# =============================================================================

def nf_xdr_list(ser: serial.Serial) -> str:
    """
    Retrieve the list of transducers available on the NeuroFUS device.

    Equivalent to: NFXDRList(NFUS)

    Args:
        ser: Open serial.Serial object.

    Returns:
        String containing the available transducer names/indices as reported by the device.
        Typically comma-separated.
    """
    ser.reset_input_buffer()
    _write(ser, 'XDRList?')
    _wait_for_data(ser)
    return _read(ser)


def nf_xdr_select(ser: serial.Serial, xdr_index: int) -> float:
    """
    Select a transducer on the NeuroFUS device.

    Equivalent to: NFXDRSelect(NFUS, selectedXDR)

    Args:
        ser:       Open serial.Serial object.
        xdr_index: Index of the transducer to select (integer, typically 0–7).

    Returns:
        Confirmed transducer index as acknowledged by the device.
    """
    ser.reset_input_buffer()
    _write(ser, f'XDRSELECT={xdr_index}')
    _wait_for_data(ser)
    response = _read(ser)
    index = _parse_first_number(response)
    logger.info("Successfully selected transducer with index: %d", index)
    return index


# =============================================================================
# Public API — Stimulation parameter setters
# =============================================================================

def nf_pulse_parameters(ser: serial.Serial, pd: float, pri: float, ptd: float) -> tuple:
    """
    Set all pulse timing parameters on the NeuroFUS device.

    Equivalent to: NFPulseParameters(NFUS, pd, pri, ptd)

    The device is first reset to safe minimal values to avoid ordering conflicts,
    then the requested parameters are applied in the order: PTD -> PRI -> PD.

    Args:
        ser: Open serial.Serial object.
        pd:  Pulse Duration in milliseconds (ms).
        pri: Pulse Repetition Interval in milliseconds (ms).
             (pass PRP directly, or derive from PRF: pri = 1000 / prf_hz)
        ptd: Pulse Train Duration in milliseconds (ms).

    Returns:
        (burst, pulse_rep_interval, duration) — values confirmed by the device.
    """
    # Reset to minimal values first (safe ordering to avoid conflicts)
    _nf_burst_length(ser, 0.01)
    _nf_pulse_rep_period(ser, 0.01)

    # Set the requested parameters
    duration = _nf_duration(ser, ptd)
    pulse_rep_interval = _nf_pulse_rep_period(ser, pri)
    burst = _nf_burst_length(ser, pd)

    return burst, pulse_rep_interval, duration


def nf_depth(ser: serial.Serial, depth_mm: float) -> float:
    """
    Set the focal depth on the NeuroFUS device.

    Equivalent to: NFDepth(NFUS, focus)

    The function queries the transducer's focus range and validates the requested
    depth before sending. Depth is converted from mm to µm before transmission.

    Args:
        ser:      Open serial.Serial object.
        depth_mm: Desired focal depth in millimeters (mm).

    Returns:
        Confirmed focus depth value as acknowledged by the device.
    """
    min_depth, max_depth = _read_nfus_focus_range(ser)
    if depth_mm < min_depth:
        raise ValueError(
            f"Depth {depth_mm} mm is below the minimum steering range ({min_depth} mm)."
        )
    if depth_mm > max_depth:
        raise ValueError(
            f"Depth {depth_mm} mm exceeds the maximum steering range ({max_depth} mm)."
        )
    depth_um = depth_mm * 1000  # mm -> µm
    _write(ser, f'FOCUS={depth_um:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    focus = _parse_first_number(response)
    logger.info("Focus depth set to: %f mm", focus)
    return focus


def nf_enforce_limits(ser: serial.Serial, state: bool) -> int:
    """
    Enable or disable the device safety power limits.

    Equivalent to: NFEnforceLimits(NFUS, state)

    When enabled (default), the device enforces Isppa and Ispta maximums.
    When disabled, those limits are bypassed — use with caution.

    Args:
        ser:   Open serial.Serial object.
        state: True (or 1) to enforce limits, False (or 0) to disable them.

    Returns:
        The confirmed enforce-limits state as reported by the device (1 or 0).
    """
    ser.reset_input_buffer()
    cmd = 'ENFORCELIMITS=1' if state else 'ENFORCELIMITS=0'
    _write(ser, cmd)
    _wait_for_data(ser)
    response = _read(ser)
    confirmed = int(_parse_first_number(response))
    logger.info("EnforceLimits set to: %d", confirmed)
    return confirmed


def nf_isppa(ser: serial.Serial, isppa_w_cm2: float) -> float:
    """
    Set the ISPPA (spatial peak pulse average intensity) on the NeuroFUS device.

    Equivalent to: NFIsppa(NFUS, isppa)

    The value is converted from W/cm² to mW/cm² internally before being sent.
    Safety limits are checked against device-reported maximums.

    Args:
        ser:          Open serial.Serial object.
        isppa_w_cm2:  Desired Isppa in W/cm².

    Returns:
        Confirmed Isppa value as acknowledged by the device.
    """
    ser.reset_input_buffer()

    isppa_mw = isppa_w_cm2 * 1000  # W/cm² -> mW/cm²

    if _read_nfus_enforce_limits(ser) > 0:
        isppa_max_mw = 30_000  # mW/cm²
        ispta_max_mw = 720     # mW/cm²
    else:
        isppa_max_mw = _read_nfus_isppa_max(ser) * 1000
        ispta_max_mw = _read_nfus_ispta_max(ser) * 1000

    ispta_mw = isppa_mw * _read_nfus_burst(ser) / _read_nfus_period(ser)

    if isppa_mw < 1:
        raise ValueError("Power too low. Enter a value > 1 mW/cm².")
    if isppa_mw > isppa_max_mw:
        raise ValueError(
            f"Power too high. Enter a value < {isppa_max_mw / 1000} W/cm² "
            f"({isppa_max_mw} mW/cm²)."
        )
    if ispta_mw > ispta_max_mw:
        raise ValueError(
            f"Ispta too high ({ispta_mw:.1f} mW/cm²). "
            f"Must be < {ispta_max_mw} mW/cm². "
            f"Reduce pulse duration or increase PRI."
        )

    _write(ser, f'ISPPA={isppa_mw:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    isppa = _parse_first_number(response)
    logger.info("Isppa set to: %f mW/cm²", isppa)
    return isppa


def nf_ramp_mode(ser: serial.Serial, ramp_mode: int) -> int:
    """
    Set the amplitude ramp mode for the acoustic pulse.

    Equivalent to: NFRampMode(NFUS, ramp_mode)

    Args:
        ser:       Open serial.Serial object.
        ramp_mode: Integer ramp mode:
                   0 = No ramp
                   1 = Linear ramp
                   2 = Tukey ramp
                   3 = Log ramp
                   4 = Exponential ramp
                   5 = Gaussian ramp

    Returns:
        Confirmed ramp mode as acknowledged by the device.
    """
    if not (0 <= ramp_mode <= 6):
        raise ValueError(f"Ramp mode must be between 0 and 5. Got: {ramp_mode}")

    ser.reset_input_buffer()
    _write(ser, f'RAMPMODE={ramp_mode}')
    _wait_for_data(ser)
    response = _read(ser)

    for part in response.split():
        try:
            val = int(float(part))
            if 0 <= val <= 6:
                logger.info("Ramp mode set to: %d", val)
                return val
        except ValueError:
            continue

    raise ValueError(f"Invalid response from device when setting ramp mode: {response!r}")


def nf_ramp_dur(ser: serial.Serial, ramp_dur_us: float) -> float:
    """
    Set the ramp duration for the acoustic pulse envelope.

    Equivalent to: NFRampDur(NFUS, ramp_duration)

    Note: per the GUI spec, convert Ramp Length (ms) to µs before calling:
          nf_ramp_dur(ser, ramp_length_ms * 1000)

    Args:
        ser:         Open serial.Serial object.
        ramp_dur_us: Ramp duration in microseconds (µs). Valid range: 10–100,000 µs.

    Returns:
        Confirmed ramp duration as acknowledged by the device.
    """
    if ramp_dur_us < 10:
        raise ValueError("Ramp duration must be >= 10 µs.")
    if ramp_dur_us > 100_000:
        raise ValueError("Ramp duration must be <= 100,000 µs.")

    ser.reset_input_buffer()
    _write(ser, f'RAMPLENGTH={ramp_dur_us:.0f}')
    _wait_for_data(ser)
    response = _read(ser)
    value = _parse_first_number(response)
    logger.info("Ramp duration set to: %f µs", value)
    return value


# =============================================================================
# Public API — Sonication control
# =============================================================================

def nf_start_timed(ser: serial.Serial) -> NeuroFusCommandResult:
    """
    Start sonication and return command/ack timing metadata.

    Returns:
        NeuroFusCommandResult containing the START send time, response time,
        raw response, and success status.
    """
    return _run_command_with_ack(
        ser=ser,
        command='START',
        expected_response_text='Sonication Started',
        success_message="Sonication started successfully. Response: %s",
        unexpected_message="START sent but unexpected response: %s",
        error_message="Error reading response after START: %s",
    )


def nf_start(ser: serial.Serial) -> bool:
    """
    Start sonication on the NeuroFUS device.

    Equivalent to: NFStart(NFUS)

    This function is non-blocking — it sends the START command and returns
    immediately. For pulse train repetitions, call nf_start() repeatedly
    according to your PTRF/PTRP/PTRD timing in the calling code.

    Args:
        ser: Open serial.Serial object.

    Returns:
        True if the device confirmed sonication started, False otherwise.
    """
    return nf_start_timed(ser).success


def nf_stop_timed(ser: serial.Serial) -> NeuroFusCommandResult:
    """
    Abort sonication and return command/ack timing metadata.

    Returns:
        NeuroFusCommandResult containing the ABORT send time, response time,
        raw response, and success status.
    """
    return _run_command_with_ack(
        ser=ser,
        command='ABORT',
        expected_response_text='Treatment Aborted',
        success_message="Treatment aborted successfully. Response: %s",
        unexpected_message="ABORT sent but unexpected response: %s",
        error_message="Error reading response after ABORT: %s",
    )


def nf_stop(ser: serial.Serial) -> bool:
    """
    Immediately stop (abort) sonication on the NeuroFUS device.

    Equivalent to: NFStop(NFUS)

    Args:
        ser: Open serial.Serial object.

    Returns:
        True if the device confirmed treatment aborted, False otherwise.
    """
    return nf_stop_timed(ser).success
