# amg_app/main_gui.py

# top of main_gui.py, before any Qt imports
def _check_qt_conflicts():
    import importlib.util
    if importlib.util.find_spec("PyQt5") is not None:
        raise SystemExit(
            "ERROR: PyQt5 is installed alongside PyQt6. "
            "Run 'pip uninstall PyQt5 PyQt5-sip PyQtWebEngine' and try again."
        )

_check_qt_conflicts()

import os
import pathlib

def _fix_qt_plugin_path():
    try:
        import PyQt6.QtCore
        plugins_path = pathlib.Path(PyQt6.QtCore.__file__).parent / "Qt6" / "plugins" / "platforms"
        if plugins_path.exists():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins_path)
    except Exception:
        pass

_fix_qt_plugin_path()

import sys
import copy
import time
from threading import Event
from datetime import datetime
from pathlib import Path
import serial.tools.list_ports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QRadioButton, QButtonGroup, QCheckBox,
    QSlider, QTextEdit, QDialog, QDoubleSpinBox, QAbstractSpinBox,
    QScrollArea, QToolTip
)
from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QDoubleValidator, QColor, QIntValidator

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import numpy as np

from session_controller import SessionController
from neurofus_sdk import nf_open, nf_stop, nf_xdr_list, nf_accept_eula
from stimulation_mode import run_stimulation_mode, maybe_show_tus_mask_notice
import logger as session_logger
import audio_engine
import plotting
import signal_generator
from preset_manager import PresetManager

EXPECTED_FIRMWARE = "6.06.1"

class BasicMaskGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auditory Mask Generator")
        self.resize(900, 550)

        self.current_audio = None
        self.current_time = None
        self.current_gate = None
        self.current_fs = None
        self.zoom_view = True
        # NEW: Dual mode variables
        self.current_pulse_audio = None
        self.current_bg_audio = None
        self.last_generated_params = None
        self.last_generated_mode = None
        self.tpo_ser = None
        self.connected_port = None
        self.connected_firmware = None
        self.active_sonication_window = None
        self.stimulation_stop_event = None
        self._countdown_timer = None
        self._countdown_remaining = 0
        self._pending_stim_request = None
        self._plot_popups = []
        self.last_execution_log = []
        # ADDED: Dedicated manager keeps preset save/load logic out of this GUI file.
        self.preset_manager = PresetManager(self)

        self.updating_prp_prf = False
        self.updating_ptrp_ptrf = False
        self.updating_ptrd_num = False

        self.updating_ultra_prp_prf = False
        self.updating_ultra_ptrp_ptrf = False
        self.updating_ultra_ptrd_num = False
        self.syncing_hybrid_prf = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 1)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        main_layout.addWidget(top_widget)

        params_hbox = QHBoxLayout()
        top_layout.addLayout(params_hbox)

        # Stimulation Matching (unchanged)
        stimulation_group = QGroupBox("Stimulation Matching")
        stimulation_layout = QVBoxLayout(stimulation_group)

        main_form = QFormLayout()
        main_form.setVerticalSpacing(0)  # Reduce vertical spacing
        stimulation_layout.addLayout(main_form)

        self.ptd_input = QLineEdit("")
        self.ptd_input.setValidator(QDoubleValidator(0.001, 600000.0, 3))
        self.ptd_input.textChanged.connect(lambda _: self.validate_input(self.ptd_input))
        self.ptd_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow("Pulse Train Duration (ms):", self.ptd_input)

        self.prp_input = QLineEdit("")
        self.prp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.prp_input.textChanged.connect(lambda _: self.validate_input(self.prp_input))
        self.prp_input.textChanged.connect(self.on_prp_changed)
        main_form.addRow("PRI (ms):", self.prp_input)

        self.prf_input = QLineEdit("")
        self.prf_input.setValidator(QDoubleValidator(1, 10000, 2))  # Allow 2 decimals
        self.prf_input.textChanged.connect(lambda _: self.validate_input(self.prf_input))
        self.prf_input.textChanged.connect(self.on_prf_changed)
        self.prf_input.textChanged.connect(self.sync_hybrid_prf_from_main)
        main_form.addRow("PRF (Hz):", self.prf_input)

        self.pd_input = QLineEdit("")
        self.pd_input.setValidator(QDoubleValidator(0.001, 1000.0, 3))
        self.pd_input.textChanged.connect(lambda _: self.validate_input(self.pd_input))
        self.pd_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow("Pulse Duration (ms):", self.pd_input)

        self.carrier_input = QLineEdit("")
        self.carrier_input.setValidator(QDoubleValidator(1, 20000, 0))
        self.carrier_input.setPlaceholderText("Enable Carrier Wave")
        self.carrier_input.textChanged.connect(lambda _: self.validate_input(self.carrier_input))
        self.carrier_input.textChanged.connect(self.validate_generate_button)
        self.carrier_input.setEnabled(False)

        self.enable_carrier_checkbox = QCheckBox("")
        self.enable_carrier_checkbox.setChecked(False)
        self.enable_carrier_checkbox.toggled.connect(self.update_derived)
        self.enable_carrier_checkbox.toggled.connect(self._on_enable_carrier_toggled)

        carrier_widget = QWidget()
        carrier_layout = QHBoxLayout(carrier_widget)
        carrier_layout.setContentsMargins(0, 0, 0, 0)
        carrier_layout.addWidget(self.enable_carrier_checkbox)
        carrier_layout.addWidget(self.carrier_input)

        main_form.addRow("Carrier Frequency (Hz):", carrier_widget)

        self.ramp_shape_combo = QComboBox()
        self.ramp_shape_combo.addItems(["None", "Linear", "Tukey"])
        self.ramp_shape_combo.currentTextChanged.connect(self.on_ramp_shape_changed)
        main_form.addRow("Ramp Shape:", self.ramp_shape_combo)

        self.ramp_len_label = QLabel("Ramp Length (ms):")
        self.ramp_len_input = QLineEdit("")
        self.ramp_len_input.setValidator(QDoubleValidator(0.0, 1000.0, 3))
        self.ramp_len_input.textChanged.connect(lambda _: self.validate_input(self.ramp_len_input))
        self.ramp_len_input.textChanged.connect(lambda _: self.update_derived())
        main_form.addRow(self.ramp_len_label, self.ramp_len_input)

        self.snr_checkbox = QCheckBox("Add noise")
        self.snr_input = QLineEdit("")
        self.snr_input.setValidator(QDoubleValidator(0, 100, 2))
        self.snr_input.setEnabled(False)
        self.snr_input.setPlaceholderText("SNR ratio")
        self.snr_input.textChanged.connect(lambda _: self.validate_input(self.snr_input))
        self.snr_checkbox.toggled.connect(self.snr_input.setEnabled)
        self.snr_checkbox.toggled.connect(lambda checked: self.snr_input.setText("1") if checked and not self.snr_input.text() else None)
        snr_widget = QWidget()
        snr_layout = QHBoxLayout(snr_widget)
        snr_layout.setContentsMargins(0, 0, 0, 0)
        snr_layout.addWidget(self.snr_checkbox)
        snr_layout.addWidget(self.snr_input)
        main_form.addRow("Signal-to-Noise Ratio:", snr_widget)

        self.duty_label = QLabel("")
        main_form.addRow("Duty Cycle (%):", self.duty_label)

        self.matching_volume_widget = QWidget()
        matching_volume_layout = QHBoxLayout(self.matching_volume_widget)
        self.matching_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.matching_volume_slider.setRange(0, 100)
        self.matching_volume_slider.setValue(50)
        matching_volume_layout.addWidget(self.matching_volume_slider)
        self.matching_volume_label = QLabel("50")
        self.matching_volume_slider.valueChanged.connect(lambda v: self.matching_volume_label.setText(str(v)))
        matching_volume_layout.addWidget(self.matching_volume_label)
        main_form.addRow("Matching Volume (%):", self.matching_volume_widget)

        self.enable_ptr_checkbox = QCheckBox("Enable Pulse Train Repetition")
        self.enable_ptr_checkbox.toggled.connect(self.on_toggle_ptr)
        stimulation_layout.addWidget(self.enable_ptr_checkbox)

        self.ptr_sub_widget = QWidget()
        ptr_sub_layout = QFormLayout()
        ptr_sub_layout.setVerticalSpacing(0)  # Reduce vertical spacing
        self.ptr_sub_widget.setLayout(ptr_sub_layout)
        stimulation_layout.addWidget(self.ptr_sub_widget)

        self.ptrp_input = QLineEdit("")
        self.ptrp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.ptrp_input.textChanged.connect(lambda _: self.validate_input(self.ptrp_input))
        self.ptrp_input.textChanged.connect(self.on_ptrp_changed)
        ptr_sub_layout.addRow("PTRI (s):", self.ptrp_input)

        self.ptrf_input = QLineEdit("")
        self.ptrf_input.setValidator(QDoubleValidator(0.0001, 1000.0, 4))
        self.ptrf_input.textChanged.connect(lambda _: self.validate_input(self.ptrf_input))
        self.ptrf_input.textChanged.connect(self.on_ptrf_changed)
        ptr_sub_layout.addRow("PTRF (Hz):", self.ptrf_input)

        self.ptrd_input = QLineEdit("")
        self.ptrd_input.setValidator(QDoubleValidator(0.1, 10000.0, 3))
        self.ptrd_input.textChanged.connect(lambda _: self.validate_input(self.ptrd_input))
        self.ptrd_input.textChanged.connect(self.on_ptrd_changed)
        ptr_sub_layout.addRow("PTRD (s):", self.ptrd_input)

        self.num_trains_input = QLineEdit("")
        self.num_trains_input.setValidator(QDoubleValidator(1, 100000, 0))
        self.num_trains_input.textChanged.connect(lambda _: self.validate_input(self.num_trains_input))
        self.num_trains_input.textChanged.connect(self.on_num_trains_changed)
        ptr_sub_layout.addRow("Number of Trains:", self.num_trains_input)

        self.ptr_sub_widget.setVisible(False)

        params_hbox.addWidget(stimulation_group, stretch=1)

        # Background and Layering (unchanged)
        dual_group = QGroupBox("Background and Layering")
        dual_layout = QFormLayout(dual_group)
        dual_layout.setContentsMargins(6, 6, 6, 6)
        dual_layout.setVerticalSpacing(2)
        dual_layout.setHorizontalSpacing(6)
        params_hbox.addWidget(dual_group, stretch=1)

        bg_label = QLabel("Continuous Background Controls")
        dual_layout.addRow(bg_label)

        self.bg_type_combo = QComboBox()
        self.bg_type_combo.addItems(["White Noise", "Narrowband Noise", "Colored Noise", "Hybrid Ultrasound Mask", "Auditory Mondrian"])
        self.bg_type_combo.currentTextChanged.connect(self.on_background_type_changed)
        dual_layout.addRow("Background Type:", self.bg_type_combo)

        self.bg_ramp_shape = QComboBox()
        self.bg_ramp_shape.addItems(["None", "Linear", "Tukey"])
        dual_layout.addRow("Ramp Shape:", self.bg_ramp_shape)

        self.bg_ramp_length_label = QLabel("Ramp Length (ms):")
        self.bg_ramp_length = QDoubleSpinBox()
        self.bg_ramp_length.setRange(0.0, 1000.0)
        self.bg_ramp_length.setDecimals(3)
        self.bg_ramp_length.setSingleStep(1.0)
        self.bg_ramp_length.setValue(10.0)
        self.bg_ramp_length.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        dual_layout.addRow(self.bg_ramp_length_label, self.bg_ramp_length)

        self.bg_ramp_shape.currentTextChanged.connect(self.on_background_ramp_changed)
        self.bg_ramp_length.valueChanged.connect(self.on_background_ramp_changed)

        self.bg_time_input = QLineEdit("5")
        self.bg_time_input.setValidator(QDoubleValidator(0.001, 100000.0, 3))
        self.bg_time_input.textChanged.connect(lambda _: self.validate_input(self.bg_time_input))
        self.bg_time_input.textChanged.connect(lambda _: self.update_derived())
        dual_layout.addRow("Background Time (s):", self.bg_time_input)

        # ADDED: Dedicated narrowband controls independent from the matching-signal carrier.
        self.narrowband_center_label = QLabel("Center Frequency (Hz):")
        self.narrowband_center_input = QLineEdit("1000")
        self.narrowband_center_input.setValidator(QDoubleValidator(1.0, 20000.0, 1))
        self.narrowband_center_input.textChanged.connect(lambda _: self.validate_input(self.narrowband_center_input))
        self.narrowband_center_input.textChanged.connect(self.validate_generate_button)
        dual_layout.addRow(self.narrowband_center_label, self.narrowband_center_input)

        self.narrowband_bandwidth_label = QLabel("Bandwidth (Hz):")
        self.narrowband_bandwidth_input = QLineEdit("100")
        self.narrowband_bandwidth_input.setValidator(QDoubleValidator(1.0, 20000.0, 1))
        self.narrowband_bandwidth_input.textChanged.connect(lambda _: self.validate_input(self.narrowband_bandwidth_input))
        self.narrowband_bandwidth_input.textChanged.connect(self.validate_generate_button)
        dual_layout.addRow(self.narrowband_bandwidth_label, self.narrowband_bandwidth_input)

        # ADDED: Simple named colored-noise selector.
        self.colored_noise_label = QLabel("Color:")
        self.colored_noise_combo = QComboBox()
        self.colored_noise_combo.addItems(["Pink", "Brown", "Blue", "Violet"])
        self.colored_noise_combo.currentTextChanged.connect(self.on_settings_changed)
        dual_layout.addRow(self.colored_noise_label, self.colored_noise_combo)

        self.bg_volume_widget = QWidget()
        bg_volume_layout = QHBoxLayout(self.bg_volume_widget)
        bg_volume_layout.setContentsMargins(0, 0, 0, 0)
        bg_volume_layout.setSpacing(4)
        self.bg_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_volume_slider.setRange(0, 100)
        self.bg_volume_slider.setValue(50)
        bg_volume_layout.addWidget(self.bg_volume_slider)
        self.bg_volume_label = QLabel("50")
        self.bg_volume_slider.valueChanged.connect(lambda v: self.bg_volume_label.setText(str(v)))
        bg_volume_layout.addWidget(self.bg_volume_label)
        dual_layout.addRow("Background Volume (%):", self.bg_volume_widget)

        self.enable_dual_checkbox = QCheckBox("Enable Dual Sound Mode")
        self.enable_dual_checkbox.toggled.connect(self.on_toggle_dual)
        dual_layout.addRow(self.enable_dual_checkbox)

        self.hybrid_mask_group = QGroupBox("Hybrid Mask Settings")
        hybrid_layout = QVBoxLayout(self.hybrid_mask_group)
        hybrid_layout.setContentsMargins(4, 4, 4, 4)
        hybrid_layout.setSpacing(2)

        hybrid_mode_row = QHBoxLayout()
        hybrid_mode_row.setContentsMargins(0, 0, 0, 0)
        hybrid_mode_row.setSpacing(4)
        self.hybrid_auto_radio = QRadioButton("Auto (recommended)")
        self.hybrid_manual_radio = QRadioButton("Manual tuning")
        self.hybrid_auto_radio.setChecked(True)
        self.hybrid_mode_group = QButtonGroup(self)
        self.hybrid_mode_group.addButton(self.hybrid_auto_radio)
        self.hybrid_mode_group.addButton(self.hybrid_manual_radio)
        self.hybrid_auto_radio.toggled.connect(self.on_hybrid_mode_changed)
        self.hybrid_manual_radio.toggled.connect(self.on_hybrid_mode_changed)
        hybrid_mode_row.addWidget(self.hybrid_auto_radio)
        hybrid_mode_row.addWidget(self.hybrid_manual_radio)
        hybrid_mode_row.addStretch(1)
        hybrid_layout.addLayout(hybrid_mode_row)

        self.hybrid_manual_widget = QWidget()
        hybrid_form = QFormLayout(self.hybrid_manual_widget)
        hybrid_form.setContentsMargins(0, 0, 0, 0)
        hybrid_form.setVerticalSpacing(2)
        hybrid_form.setHorizontalSpacing(4)

        self.hybrid_prf_input = QLineEdit("")
        self.hybrid_prf_input.setPlaceholderText("1000")
        self.hybrid_prf_input.setValidator(QDoubleValidator(1, 10000, 2))
        self.hybrid_prf_input.textChanged.connect(self.on_hybrid_prf_changed)
        hybrid_form.addRow("PRF (Hz):", self.hybrid_prf_input)

        self.hybrid_harmonics_input = QLineEdit("10")
        self.hybrid_harmonics_input.setValidator(QIntValidator(1, 1000))
        self.hybrid_harmonics_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_harmonics_input))
        hybrid_form.addRow("PRF Harmonics:", self.hybrid_harmonics_input)

        self.hybrid_bandwidth_input = QLineEdit("200")
        self.hybrid_bandwidth_input.setValidator(QDoubleValidator(1.0, 20000.0, 2))
        self.hybrid_bandwidth_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_bandwidth_input))
        hybrid_form.addRow("Harmonic Bandwidth (Hz):", self.hybrid_bandwidth_input)

        self.hybrid_density_input = QLineEdit("4")
        self.hybrid_density_input.setValidator(QDoubleValidator(0.1, 100.0, 2))
        self.hybrid_density_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_density_input))
        hybrid_form.addRow("Mondrian Density (tones/s):", self.hybrid_density_input)

        self.hybrid_tone_duration_input = QLineEdit("500")
        self.hybrid_tone_duration_input.setValidator(QDoubleValidator(10.0, 10000.0, 1))
        self.hybrid_tone_duration_input.textChanged.connect(lambda _: self.validate_input(self.hybrid_tone_duration_input))
        hybrid_form.addRow("Mondrian Tone Duration (ms):", self.hybrid_tone_duration_input)

        self.hybrid_prf_weight_widget, self.hybrid_prf_weight_slider, self.hybrid_prf_weight_label = self._create_labeled_slider(0, 100, 50)
        hybrid_form.addRow("PRF Mask Weight:", self.hybrid_prf_weight_widget)

        self.hybrid_mondrian_weight_widget, self.hybrid_mondrian_weight_slider, self.hybrid_mondrian_weight_label = self._create_labeled_slider(0, 100, 30)
        hybrid_form.addRow("Mondrian Weight:", self.hybrid_mondrian_weight_widget)

        self.hybrid_broadband_weight_widget, self.hybrid_broadband_weight_slider, self.hybrid_broadband_weight_label = self._create_labeled_slider(0, 100, 20)
        hybrid_form.addRow("Broadband Weight:", self.hybrid_broadband_weight_widget)

        self.hybrid_manual_scroll = QScrollArea()
        self.hybrid_manual_scroll.setWidgetResizable(True)
        self.hybrid_manual_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.hybrid_manual_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hybrid_manual_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hybrid_manual_scroll.setWidget(self.hybrid_manual_widget)
        self.hybrid_manual_scroll.setFixedHeight(162)
        hybrid_layout.addWidget(self.hybrid_manual_scroll)
        dual_layout.addRow(self.hybrid_mask_group)
        self.hybrid_mask_group.setVisible(False)
        self.hybrid_manual_scroll.setVisible(False)

        self.mondrian_mask_group = QGroupBox("Mondrian Mask Settings")
        mondrian_layout = QFormLayout(self.mondrian_mask_group)
        mondrian_layout.setContentsMargins(4, 4, 4, 4)
        mondrian_layout.setVerticalSpacing(2)
        mondrian_layout.setHorizontalSpacing(4)

        self.mondrian_density_input = QLineEdit("8")
        self.mondrian_density_input.setValidator(QDoubleValidator(0.1, 100.0, 2))
        self.mondrian_density_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_density_input))
        mondrian_layout.addRow("Mondrian Density (tones/s):", self.mondrian_density_input)

        self.mondrian_tone_duration_input = QLineEdit("500")
        self.mondrian_tone_duration_input.setValidator(QDoubleValidator(10.0, 10000.0, 1))
        self.mondrian_tone_duration_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_tone_duration_input))
        mondrian_layout.addRow("Tone Duration (ms):", self.mondrian_tone_duration_input)

        self.mondrian_pf_min_input = QLineEdit()
        self.mondrian_pf_min_input.setPlaceholderText("optional (default: 20 Hz)")
        self.mondrian_pf_min_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_pf_min_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_pf_min_input))
        mondrian_layout.addRow("PF Min (Hz):", self.mondrian_pf_min_input)

        self.mondrian_pf_max_input = QLineEdit("15000")
        self.mondrian_pf_max_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_pf_max_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_pf_max_input))
        mondrian_layout.addRow("PF max (Hz):", self.mondrian_pf_max_input)

        self.mondrian_prf_min_input = QLineEdit("1000")
        self.mondrian_prf_min_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_prf_min_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_prf_min_input))
        mondrian_layout.addRow("PRF Min (Hz):", self.mondrian_prf_min_input)

        self.mondrian_prf_max_input = QLineEdit("15000")
        self.mondrian_prf_max_input.setValidator(QDoubleValidator(1.0, 50000.0, 1))
        self.mondrian_prf_max_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_prf_max_input))
        mondrian_layout.addRow("PRF Max (Hz):", self.mondrian_prf_max_input)

        self.mondrian_duty_cycle_input = QLineEdit("50")
        self.mondrian_duty_cycle_input.setValidator(QDoubleValidator(1.0, 99.0, 1))
        self.mondrian_duty_cycle_input.textChanged.connect(lambda _: self.validate_input(self.mondrian_duty_cycle_input))
        mondrian_layout.addRow("Duty Cycle (%):", self.mondrian_duty_cycle_input)

        dual_layout.addRow(self.mondrian_mask_group)
        self.mondrian_mask_group.setVisible(False)

        self.pulse_controls_widget = QWidget()
        pulse_controls_layout = QFormLayout(self.pulse_controls_widget)
        pulse_controls_layout.setContentsMargins(0, 0, 0, 0)
        pulse_controls_layout.setVerticalSpacing(2)
        pulse_controls_layout.setHorizontalSpacing(6)
        pulse_label = QLabel("Pulse Mask Timing Controls")
        pulse_controls_layout.addRow(pulse_label)

        self.pulse_start_input = QLineEdit("0")
        self.pulse_start_input.setValidator(QDoubleValidator(0.0, 100000.0, 3))
        self.pulse_start_input.textChanged.connect(lambda _: self.validate_input(self.pulse_start_input))
        self.pulse_start_input.textChanged.connect(lambda _: self.update_derived())
        pulse_controls_layout.addRow("Pulse Start Time (ms):", self.pulse_start_input)

        self.pulse_volume_widget = QWidget()
        pulse_volume_layout = QHBoxLayout(self.pulse_volume_widget)
        pulse_volume_layout.setContentsMargins(0, 0, 0, 0)
        pulse_volume_layout.setSpacing(4)
        self.pulse_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.pulse_volume_slider.setRange(0, 100)
        self.pulse_volume_slider.setValue(100)
        pulse_volume_layout.addWidget(self.pulse_volume_slider)
        self.pulse_volume_label = QLabel("100")
        self.pulse_volume_slider.valueChanged.connect(lambda v: self.pulse_volume_label.setText(str(v)))
        pulse_volume_layout.addWidget(self.pulse_volume_label)
        pulse_controls_layout.addRow("Pulse Volume (%):", self.pulse_volume_widget)

        dual_layout.addRow(self.pulse_controls_widget)
        self.pulse_controls_widget.setVisible(False)

        # Panel 3: Execution Control
        execution_control_group = QGroupBox("Execution Control")
        execution_layout = QVBoxLayout(execution_control_group)

        # Lateralization Mode
        spatial_mode_group = QGroupBox("Lateralization Mode")
        spatial_mode_layout = QFormLayout(spatial_mode_group)

        self.pan_widget = QWidget()
        pan_layout = QHBoxLayout(self.pan_widget)
        self.pan_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_slider.setRange(-100, 100)
        self.pan_slider.setValue(0)
        self.pan_slider.valueChanged.connect(self.on_pan_changed)
        pan_layout.addWidget(self.pan_slider)
        self.pan_value_label = QLabel("0")
        pan_layout.addWidget(self.pan_value_label)
        spatial_mode_layout.addRow("Pan (0 = Center):", self.pan_widget)

        self.pan_levels_label = QLabel("Left: 100%  Right: 100%")
        spatial_mode_layout.addRow("Channel Volumes:", self.pan_levels_label)

        execution_layout.addWidget(spatial_mode_group)

        # TPO Connection
        tpo_group = QGroupBox("TPO Connection")
        tpo_layout = QFormLayout(tpo_group)

        self.port_combo = QComboBox()
        tpo_layout.addRow("Port:", self.port_combo)

        self.status_label = QLabel("Disconnected")
        tpo_layout.addRow("Status:", self.status_label)

        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.clicked.connect(self.refresh_tpo_ports)
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.on_connect)
        self.connect_btn = connect_btn
        disconnect_btn = QPushButton("Disconnect")
        disconnect_btn.clicked.connect(self.on_disconnect)
        self.disconnect_btn = disconnect_btn
        tpo_btn_hbox = QHBoxLayout()
        tpo_btn_hbox.addWidget(self.refresh_ports_btn)
        tpo_btn_hbox.addWidget(connect_btn)
        tpo_btn_hbox.addWidget(disconnect_btn)
        tpo_layout.addRow(tpo_btn_hbox)

        execution_layout.addWidget(tpo_group)

        # Stimulation Mode
        stim_mode_group = QGroupBox("Stimulation Mode")
        stim_mode_layout = QFormLayout(stim_mode_group)

        self.stim_mode_combo = QComboBox()
        self.stim_mode_combo.addItems(["TUS Only", "TUS + Mask"])
        stim_mode_layout.addRow("Mode:", self.stim_mode_combo)

        self.tus_start_input = QLineEdit("0")
        self.tus_start_input.setValidator(QDoubleValidator(-100000.0, 100000.0, 3))
        self.tus_start_input.setVisible(False)
        self.tus_start_input.setPlaceholderText("0  (− = TUS before mask, + = TUS after mask)")
        stim_mode_layout.addRow("TUS Start re. Mask (ms):", self.tus_start_input)

        self.execution_log_label = QLabel("Execution Log:")
        self.execution_log_label.setVisible(False)
        self.execution_log_combo = QComboBox()
        self.execution_log_combo.setVisible(False)
        stim_mode_layout.addRow(self.execution_log_label, self.execution_log_combo)

        self.stim_mode_combo.currentTextChanged.connect(self.on_stim_mode_changed)

        execution_layout.addWidget(stim_mode_group)

        params_hbox.addWidget(execution_control_group, stretch=1)

        # Panel 4: Ultrasound Parameters
        ultrasound_group = QGroupBox("Ultrasound Parameters")
        ultrasound_layout = QVBoxLayout(ultrasound_group)

        ultra_form = QFormLayout()
        ultra_form.setVerticalSpacing(0)  # Reduce vertical spacing
        ultrasound_layout.addLayout(ultra_form)

        self.transducer_combo = QComboBox()
        self.transducer_combo.addItems([])
        ultra_form.addRow("Transducer:", self.transducer_combo)

        self.focal_depth_input = QLineEdit("")
        self.focal_depth_input.setValidator(QDoubleValidator(0.0, 100.0, 1))
        ultra_form.addRow("Focal Depth (mm):", self.focal_depth_input)

        self.isppa_input = QLineEdit("")
        self.isppa_input.setValidator(QDoubleValidator(0.0, 1000.0, 2))
        ultra_form.addRow("ISPPA (W/cm²):", self.isppa_input)

        self.enforce_limits_checkbox = QCheckBox("Enforce safety limits")
        self.enforce_limits_checkbox.setChecked(True)
        self.enforce_limits_checkbox.toggled.connect(self._on_enforce_limits_toggled)
        ultrasound_layout.addWidget(self.enforce_limits_checkbox)

        self.ultra_ptd_input = QLineEdit("")
        self.ultra_ptd_input.setValidator(QDoubleValidator(0.001, 600000.0, 3))
        ultra_form.addRow("Pulse Train Duration (ms):", self.ultra_ptd_input)

        self.ultra_prp_input = QLineEdit("")
        self.ultra_prp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.ultra_prp_input.textChanged.connect(self.on_ultra_prp_changed)
        ultra_form.addRow("PRI (ms):", self.ultra_prp_input)

        self.ultra_prf_input = QLineEdit("")
        self.ultra_prf_input.setValidator(QDoubleValidator(1, 10000, 2))
        self.ultra_prf_input.textChanged.connect(self.on_ultra_prf_changed)
        ultra_form.addRow("PRF (Hz):", self.ultra_prf_input)

        self.ultra_pd_input = QLineEdit("")
        self.ultra_pd_input.setValidator(QDoubleValidator(0.001, 1000.0, 3))
        ultra_form.addRow("Pulse Duration (ms):", self.ultra_pd_input)

        self.ultra_ramp_shape_combo = QComboBox()
        self.ultra_ramp_shape_combo.addItems(["None", "Linear", "Tukey"])
        self.ultra_ramp_shape_combo.currentTextChanged.connect(self.on_ultra_ramp_shape_changed)
        ultra_form.addRow("Ramp Shape:", self.ultra_ramp_shape_combo)

        self.ultra_ramp_len_label = QLabel("Ramp Length (ms):")
        self.ultra_ramp_len_input = QLineEdit("")
        self.ultra_ramp_len_input.setValidator(QDoubleValidator(0.0, 1000.0, 3))
        ultra_form.addRow(self.ultra_ramp_len_label, self.ultra_ramp_len_input)

        self.ultra_enable_ptr_checkbox = QCheckBox("Enable Pulse Train Repetition")
        self.ultra_enable_ptr_checkbox.toggled.connect(self.on_ultra_toggle_ptr)
        ultrasound_layout.addWidget(self.ultra_enable_ptr_checkbox)

        self.ultra_ptr_sub_widget = QWidget()
        ultra_ptr_sub_layout = QFormLayout()
        ultra_ptr_sub_layout.setVerticalSpacing(0)  # Reduce vertical spacing
        self.ultra_ptr_sub_widget.setLayout(ultra_ptr_sub_layout)
        ultrasound_layout.addWidget(self.ultra_ptr_sub_widget)

        self.ultra_ptrp_input = QLineEdit("")
        self.ultra_ptrp_input.setValidator(QDoubleValidator(0.001, 10000.0, 3))
        self.ultra_ptrp_input.textChanged.connect(self.on_ultra_ptrp_changed)
        ultra_ptr_sub_layout.addRow("PTRI (s):", self.ultra_ptrp_input)

        self.ultra_ptrf_input = QLineEdit("")
        self.ultra_ptrf_input.setValidator(QDoubleValidator(0.0001, 1000.0, 4))
        self.ultra_ptrf_input.textChanged.connect(self.on_ultra_ptrf_changed)
        ultra_ptr_sub_layout.addRow("PTRF (Hz):", self.ultra_ptrf_input)

        self.ultra_ptrd_input = QLineEdit("")
        self.ultra_ptrd_input.setValidator(QDoubleValidator(0.1, 10000.0, 3))
        self.ultra_ptrd_input.textChanged.connect(self.on_ultra_ptrd_changed)
        ultra_ptr_sub_layout.addRow("PTRD (s):", self.ultra_ptrd_input)

        self.ultra_num_trains_input = QLineEdit("")
        self.ultra_num_trains_input.setValidator(QDoubleValidator(1, 100000, 0))
        self.ultra_num_trains_input.textChanged.connect(self.on_ultra_num_trains_changed)
        ultra_ptr_sub_layout.addRow("Number of Trains:", self.ultra_num_trains_input)

        self.ultra_ptr_sub_widget.setVisible(False)

        params_hbox.addWidget(ultrasound_group, stretch=1)

        # Buttons - UPDATED: Added Calibration button
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)

        playback_controls = QWidget()
        playback_controls_layout = QHBoxLayout(playback_controls)
        playback_controls_layout.setContentsMargins(0, 0, 0, 0)
        playback_controls_layout.setSpacing(6)

        playback_label = QLabel("Playback Mode:")
        playback_controls_layout.addWidget(playback_label)

        self.playback_mode_combo = QComboBox()
        self.playback_mode_combo.setCurrentIndex(-1)  # No selection initially
        self.playback_mode_combo.currentTextChanged.connect(self.validate_generate_button)
        self.playback_mode_combo.currentTextChanged.connect(self.on_playback_mode_changed)
        self.playback_mode_combo.setFixedWidth(180)
        playback_controls_layout.addWidget(self.playback_mode_combo)

        button_layout.addWidget(playback_controls)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.on_generate)
        button_layout.addWidget(self.generate_btn)

        self.play_btn = QPushButton("Play Audio")
        self.play_btn.clicked.connect(self.on_play)
        self.play_btn.setEnabled(False)
        button_layout.addWidget(self.play_btn)

        self.stop_wav_btn = QPushButton("Stop Audio")
        self.stop_wav_btn.clicked.connect(self.on_stop)
        self.stop_wav_btn.setEnabled(False)
        button_layout.addWidget(self.stop_wav_btn)

        self.sonicate_btn = QPushButton("Start Sonication")
        self.sonicate_btn.clicked.connect(self.on_sonicate)
        self.sonicate_btn.setEnabled(False)
        button_layout.addWidget(self.sonicate_btn)

        self.stop_sonication_btn = QPushButton("Stop Sonication")
        self.stop_sonication_btn.clicked.connect(self.on_stop_sonication)
        self.stop_sonication_btn.setEnabled(False)
        button_layout.addWidget(self.stop_sonication_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)

        # ADDED: Single presets button beside Save for save/load preset actions.
        self.presets_btn = QPushButton("Presets")
        self.presets_btn.clicked.connect(lambda: self.preset_manager.show_menu(self.presets_btn))
        button_layout.addWidget(self.presets_btn)

        # ADDED: Single reset button with scoped reset options.
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(lambda: self.preset_manager.show_reset_menu(self.reset_btn))
        button_layout.addWidget(self.reset_btn)

        top_layout.addLayout(button_layout)

        self.refresh_tpo_ports()
        self._set_tpo_connected_state(False)

        # Bottom visualization - UPDATED: Added spectral toggle
        bottom_hbox = QHBoxLayout()
        main_layout.addLayout(bottom_hbox)

        left_widget = QWidget()
        self.left_layout = QVBoxLayout(left_widget)  # NEW: Made attribute for dynamic updates
        bottom_hbox.addWidget(left_widget, stretch=1)

        toggle_group = QButtonGroup(self)
        zoom_radio = QRadioButton("PRF Envelope Zoom (First 3 PRIs)")
        full_radio = QRadioButton("Full Burst View")
        toggle_group.addButton(zoom_radio)
        toggle_group.addButton(full_radio)
        zoom_radio.setChecked(True)

        toggle_hbox = QHBoxLayout()
        toggle_hbox.addWidget(zoom_radio)
        toggle_hbox.addWidget(full_radio)

        # UPDATED: Add spectral toggle checkbox
        self.show_fft_checkbox = QCheckBox("Show FFT View")
        self.show_fft_checkbox.setChecked(True)
        self.show_fft_checkbox.toggled.connect(self.on_toggle_fft)
        toggle_hbox.addStretch(1)  # Push to right for spacing
        toggle_hbox.addWidget(self.show_fft_checkbox)

        self.show_spectrogram_checkbox = QCheckBox("Show Spectrogram View")
        self.show_spectrogram_checkbox.setChecked(False)
        self.show_spectrogram_checkbox.toggled.connect(self.on_toggle_spectrogram)
        toggle_hbox.addWidget(self.show_spectrogram_checkbox)

        self.show_timeline_btn = QPushButton("Show Timeline View")
        self.show_timeline_btn.setEnabled(False)
        self.show_timeline_btn.setVisible(False)
        self.show_timeline_btn.clicked.connect(self._on_show_timeline)
        toggle_hbox.addWidget(self.show_timeline_btn)

        self.left_layout.addLayout(toggle_hbox, stretch=0)

        toggle_group.buttonToggled.connect(self.on_toggle_view)

        self.time_fig = Figure(figsize=(4, 4), dpi=100)
        self.time_canvas = FigureCanvas(self.time_fig)
        self.time_canvas.mpl_connect("button_press_event", self._on_time_canvas_click)
        self.time_ax = self.time_fig.add_subplot(111)
        self.left_layout.addWidget(self.time_canvas, stretch=1)

        self.right_widget = QWidget()  # UPDATED: Made attribute for visibility control
        right_layout = QVBoxLayout(self.right_widget)
        bottom_hbox.addWidget(self.right_widget, stretch=1)

        spacer_label = QLabel("")
        spacer_label.setFixedHeight(zoom_radio.sizeHint().height())
        right_layout.addWidget(spacer_label, stretch=0)

        self.right_fig = Figure(figsize=(4, 4), dpi=100)
        self.right_canvas = FigureCanvas(self.right_fig)
        self.right_canvas.mpl_connect("button_press_event", self._on_right_canvas_click)
        right_layout.addWidget(self.right_canvas, stretch=1)

        self.on_ramp_shape_changed(self.ramp_shape_combo.currentText())
        self.update_background_ramp_visibility()
        self.on_background_type_changed(self.bg_type_combo.currentText())
        self.update_derived()
        self.on_toggle_dual(False)  # Initial state
        self.on_pan_changed(self.pan_slider.value())  # Initial state
        self._connect_dirty_state_tracking()
        self._connect_tus_plot_refresh()
        # ADDED: Capture the startup defaults so reset returns to the initial app state.
        self.preset_manager.capture_default_states()

    # UPDATED: Toggle Dual Mode (removed separate graphs)
    def on_toggle_dual(self, checked):
        self.pulse_controls_widget.setVisible(checked)
        self.matching_volume_widget.setEnabled(not checked)
        self.playback_mode_combo.clear()
        self.playback_mode_combo.addItems(["Background Only", "Matching Only"])
        if checked:
            self.playback_mode_combo.addItems(["Combined"])
        self.playback_mode_combo.setCurrentText("Combined" if checked else "Matching Only")
        self.validate_generate_button()
        if self.current_audio is not None:
            self._update_time_plot()

    def on_playback_mode_changed(self, text):
        if text == "Matching Only" and self.enable_dual_checkbox.isChecked():
            self.enable_dual_checkbox.setChecked(False)

    def _create_labeled_slider(self, minimum, maximum, value):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        label = QLabel(f"{value / 100:.2f}")
        label.setMinimumWidth(28)
        slider.valueChanged.connect(lambda v, out=label: out.setText(f"{v / 100:.2f}"))
        layout.addWidget(slider)
        layout.addWidget(label)
        return widget, slider, label

    def _resolve_prf_value(self, show_notice=False):
        prf_text = self.prf_input.text().strip()
        if prf_text:
            return float(prf_text)

        if show_notice and self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask":
            self.statusBar().showMessage(
                "PRF not specified — using default 1000 Hz for hybrid mask",
                5000,
            )
        return 1000.0

    def on_background_type_changed(self, text):
        is_narrowband = text == "Narrowband Noise"
        is_colored_noise = text == "Colored Noise"
        is_hybrid = text == "Hybrid Ultrasound Mask"
        is_mondrian = text == "Auditory Mondrian"
        # White Noise has no additional controls
        self.narrowband_center_label.setVisible(is_narrowband)
        self.narrowband_center_input.setVisible(is_narrowband)
        self.narrowband_bandwidth_label.setVisible(is_narrowband)
        self.narrowband_bandwidth_input.setVisible(is_narrowband)
        self.colored_noise_label.setVisible(is_colored_noise)
        self.colored_noise_combo.setVisible(is_colored_noise)
        self.hybrid_mask_group.setVisible(is_hybrid)
        self.mondrian_mask_group.setVisible(is_mondrian)
        self._update_carrier_input_state()

        if is_hybrid or is_mondrian:
            self.enable_dual_checkbox.setChecked(False)
            self.enable_dual_checkbox.setEnabled(False)
            if is_hybrid:
                self.enable_dual_checkbox.setToolTip("Hybrid mask already contains multiple masking layers")
            else:
                self.enable_dual_checkbox.setToolTip("Auditory Mondrian is a standalone masking background")
        else:
            self.enable_dual_checkbox.setEnabled(True)
            self.enable_dual_checkbox.setToolTip("")

        self.update_background_ramp_visibility()
        self.on_hybrid_mode_changed()
        self.validate_generate_button()

    def on_hybrid_mode_changed(self, *_):
        is_hybrid = self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask"
        manual = is_hybrid and self.hybrid_manual_radio.isChecked()
        if is_hybrid and self.hybrid_auto_radio.isChecked():
            self.reset_hybrid_defaults()
        self.hybrid_manual_scroll.setVisible(manual)
        self.validate_generate_button()

    def _set_prf_fields(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.prf_input.text() != text:
                self.prf_input.setText(text)
            if self.hybrid_prf_input.text() != text:
                self.hybrid_prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False

    def on_hybrid_prf_changed(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.prf_input.text() != text:
                self.prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False
        self.validate_generate_button()

    def sync_hybrid_prf_from_main(self, text):
        if self.syncing_hybrid_prf:
            return
        self.syncing_hybrid_prf = True
        try:
            if self.hybrid_prf_input.text() != text:
                self.hybrid_prf_input.setText(text)
        finally:
            self.syncing_hybrid_prf = False

    def _compute_pan_gains(self, pan_norm):
        pan_norm = max(-1.0, min(1.0, pan_norm))
        if pan_norm <= 0:
            left_gain = 1.0
            right_gain = 1.0 + pan_norm
        else:
            left_gain = 1.0 - pan_norm
            right_gain = 1.0
        return left_gain, right_gain

    def reset_hybrid_defaults(self):
        self.hybrid_harmonics_input.setText("10")
        self.hybrid_bandwidth_input.setText("200")
        self.hybrid_density_input.setText("4")
        self.hybrid_tone_duration_input.setText("500")
        self.hybrid_prf_weight_slider.setValue(50)
        self.hybrid_mondrian_weight_slider.setValue(30)
        self.hybrid_broadband_weight_slider.setValue(20)

    def _resolve_prf_value(self, show_notice=False):
        prf_text = self.hybrid_prf_input.text().strip() or self.prf_input.text().strip()
        if prf_text:
            return float(prf_text)

        if show_notice and self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask":
            self._set_prf_fields("1000")
            message = "PRF not specified \u2014 using default 1000 Hz for hybrid mask"
            self.statusBar().showMessage(message, 5000)
            tooltip_pos = self.generate_btn.mapToGlobal(self.generate_btn.rect().center())
            QToolTip.showText(tooltip_pos, message, self.generate_btn, self.generate_btn.rect(), 5000)
        return 1000.0

    def on_pan_changed(self, value):
        self.pan_value_label.setText(str(value))
        pan_norm = value / 100.0
        left_gain, right_gain = self._compute_pan_gains(pan_norm)
        self.pan_levels_label.setText(f"Left: {round(left_gain * 100):.0f}%  Right: {round(right_gain * 100):.0f}%")

    def on_toggle_view(self, button, checked):
        if checked:
            self.zoom_view = button.text() == "PRF Envelope Zoom (First 3 PRIs)"
            if self.current_audio is not None:
                self._update_time_plot()

    # UPDATED: New method for FFT toggle
    def on_toggle_fft(self, checked):
        self.right_widget.setVisible(checked or self.show_spectrogram_checkbox.isChecked())
        if self.current_audio is not None:
            self._update_right_plot()

    # NEW: Method for spectrogram toggle
    def on_toggle_spectrogram(self, checked):
        self.right_widget.setVisible(checked or self.show_fft_checkbox.isChecked())
        if self.current_audio is not None:
            self._update_right_plot()

    def on_ramp_shape_changed(self, text):
        visible = text != "None"
        self.ramp_len_label.setVisible(visible)
        self.ramp_len_input.setVisible(visible)
        if not visible:
            self.ramp_len_input.setText("")
        self.validate_generate_button()
        self.update_derived()

    def on_ultra_ramp_shape_changed(self, text):
        visible = text != "None"
        self.ultra_ramp_len_label.setVisible(visible)
        self.ultra_ramp_len_input.setVisible(visible)
        if not visible:
            self.ultra_ramp_len_input.setText("")

    def update_background_ramp_visibility(self):
        visible = self.bg_ramp_shape.currentText() != "None"
        self.bg_ramp_length_label.setVisible(visible)
        self.bg_ramp_length.setVisible(visible)

    def _is_input_acceptable(self, input_widget):
        text = input_widget.text()
        if not text:
            return False
        validator = input_widget.validator()
        if validator is None:
            return True
        state, _, _ = validator.validate(text, 0)
        return state == validator.State.Acceptable

    def on_background_ramp_changed(self, *_):
        self.update_background_ramp_visibility()

        if self.current_audio is None or self.current_fs is None:
            return

        mode = self.playback_mode_combo.currentText()
        if mode not in ["Background Only", "Combined"]:
            return

        params = self._gather_params()
        duration = len(self.current_bg_audio) / self.current_fs if self.current_bg_audio is not None else len(self.current_audio) / self.current_fs

        bg_audio = signal_generator.generate_continuous_background(
            duration=duration,
            fs=self.current_fs,
            bg_type=params["bg_type"],
            carrier_freq=params["carrier_freq"],
            bg_ramp_shape=params["bg_ramp_shape"],
            bg_ramp_length=params["bg_ramp_length"],
            prf=params["prf"],
            hybrid_settings=params.get("hybrid_mask_settings"),
            mondrian_settings=params.get("mondrian_mask_settings"),
            narrowband_settings={
                "center_freq": params.get("bg_center_freq"),
                "bandwidth": params.get("bg_bandwidth"),
            },
            colored_noise_settings={
                "color": params.get("bg_noise_color"),
            },
        )
        bg_audio = signal_generator.apply_timing_gate(bg_audio, self.current_fs, params["bg_start_ms"], params["bg_end_ms"], duration)
        bg_audio *= params["bg_volume"]

        if mode == "Background Only":
            combined = bg_audio.copy()
            pulse_audio = None
            gate = None
        else:
            pulse_audio = self.current_pulse_audio if self.current_pulse_audio is not None else np.zeros_like(bg_audio)
            combined = 0.5 * (pulse_audio + bg_audio)
            gate = self.current_gate

        max_abs = np.max(np.abs(combined))
        if max_abs > 1.0:
            combined = combined / max_abs
            if pulse_audio is not None:
                pulse_audio = pulse_audio / max_abs
            bg_audio = bg_audio / max_abs

        pan = float(params.get("pan", 0.0))
        pan = max(-1.0, min(1.0, pan))
        if pan <= 0:
            left_gain = 1.0
            right_gain = 1.0 + pan
        else:
            left_gain = 1.0 - pan
            right_gain = 1.0
        stereo_audio = np.column_stack((combined * left_gain, combined * right_gain))

        self.current_audio = stereo_audio
        self.current_bg_audio = bg_audio
        self.current_pulse_audio = pulse_audio
        self.current_gate = gate
        if self.current_time is None or len(self.current_time) != len(combined):
            self.current_time = np.arange(0, len(combined)) / self.current_fs

        self._update_time_plot()
        self._update_right_plot()

    def on_toggle_ptr(self, checked):
        self.ptr_sub_widget.setVisible(checked)
        self.validate_generate_button()
        self.update_derived()

    def on_ultra_toggle_ptr(self, checked):
        self.ultra_ptr_sub_widget.setVisible(checked)

    def on_prp_changed(self, text):
        if self.updating_prp_prf:
            return
        self.updating_prp_prf = True
        try:
            prp = float(text)
            if prp > 0:
                prf = 1000 / prp
                self.prf_input.setText(f"{prf:g}")  # Use g to remove trailing zeros
        except ValueError:
            pass
        self.updating_prp_prf = False
        self.update_derived()

    def on_prf_changed(self, text):
        if self.updating_prp_prf:
            return
        self.updating_prp_prf = True
        try:
            prf = float(text)
            if prf > 0:
                prp = 1000 / prf
                self.prp_input.setText(f"{prp:g}")
        except ValueError:
            pass
        self.updating_prp_prf = False
        self.update_derived()

    def _sync_num_trains_from_ptrd(self):
        if self.updating_ptrd_num:
            return

        ptrd_text = self.ptrd_input.text()
        ptrp_text = self.ptrp_input.text()
        if not ptrd_text or not ptrp_text:
            return

        self.updating_ptrd_num = True
        try:
            ptrd = float(ptrd_text)
            ptrp = float(ptrp_text)
            if ptrd > 0 and ptrp > 0:
                num = ptrd / ptrp
                self.num_trains_input.setText(f"{num:g}")
        except ValueError:
            pass
        finally:
            self.updating_ptrd_num = False

    def on_ptrp_changed(self, text):
        if self.updating_ptrp_ptrf:
            return
        self.updating_ptrp_ptrf = True
        try:
            ptrp = float(text)
            if ptrp > 0:
                ptrf = 1 / ptrp
                self.ptrf_input.setText(f"{ptrf:g}")
        except ValueError:
            pass
        self.updating_ptrp_ptrf = False
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_ptrf_changed(self, text):
        if self.updating_ptrp_ptrf:
            return
        self.updating_ptrp_ptrf = True
        try:
            ptrf = float(text)
            if ptrf > 0:
                ptrp = 1 / ptrf
                self.ptrp_input.setText(f"{ptrp:g}")
        except ValueError:
            pass
        self.updating_ptrp_ptrf = False
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_ptrd_changed(self, text):
        self._sync_num_trains_from_ptrd()
        self.update_derived()

    def on_num_trains_changed(self, text):
        if self.updating_ptrd_num:
            return
        self.updating_ptrd_num = True
        try:
            num = float(text)
            ptrp_text = self.ptrp_input.text()
            if ptrp_text:
                ptrp = float(ptrp_text)
                ptrd = num * ptrp
                self.ptrd_input.setText(f"{ptrd:g}")
        except ValueError:
            pass
        self.updating_ptrd_num = False
        self.update_derived()

    def on_ultra_prp_changed(self, text):
        if self.updating_ultra_prp_prf:
            return
        self.updating_ultra_prp_prf = True
        try:
            prp = float(text)
            if prp > 0:
                prf = 1000 / prp
                self.ultra_prf_input.setText(f"{prf:g}")
        except ValueError:
            pass
        self.updating_ultra_prp_prf = False
        self._sync_ultra_num_trains_from_ptrd()

    def on_ultra_prf_changed(self, text):
        if self.updating_ultra_prp_prf:
            return
        self.updating_ultra_prp_prf = True
        try:
            prf = float(text)
            if prf > 0:
                prp = 1000 / prf
                self.ultra_prp_input.setText(f"{prp:g}")
        except ValueError:
            pass
        self.updating_ultra_prp_prf = False

        self._sync_ultra_num_trains_from_ptrd()

    def _sync_ultra_num_trains_from_ptrd(self):
        if self.updating_ultra_ptrd_num:
            return

        ptrd_text = self.ultra_ptrd_input.text()
        ptrp_text = self.ultra_ptrp_input.text()
        if not ptrd_text or not ptrp_text:
            return

        self.updating_ultra_ptrd_num = True
        try:
            ptrd = float(ptrd_text)
            ptrp = float(ptrp_text)
            if ptrd > 0 and ptrp > 0:
                num = ptrd / ptrp
                self.ultra_num_trains_input.setText(f"{num:g}")
        except ValueError:
            pass
        finally:
            self.updating_ultra_ptrd_num = False

    def on_ultra_ptrp_changed(self, text):
        if self.updating_ultra_ptrp_ptrf:
            return
        self.updating_ultra_ptrp_ptrf = True
        try:
            ptrp = float(text)
            if ptrp > 0:
                ptrf = 1 / ptrp
                self.ultra_ptrf_input.setText(f"{ptrf:g}")
        except ValueError:
            pass
        self.updating_ultra_ptrp_ptrf = False

    def on_ultra_ptrf_changed(self, text):
        if self.updating_ultra_ptrp_ptrf:
            return
        self.updating_ultra_ptrp_ptrf = True
        try:
            ptrf = float(text)
            if ptrf > 0:
                ptrp = 1 / ptrf
                self.ultra_ptrp_input.setText(f"{ptrp:g}")
        except ValueError:
            pass
        self.updating_ultra_ptrp_ptrf = False

    def on_ultra_ptrd_changed(self, text):
        self._sync_ultra_num_trains_from_ptrd()

    def on_ultra_num_trains_changed(self, text):
        if self.updating_ultra_ptrd_num:
            return
        self.updating_ultra_ptrd_num = True
        try:
            num = float(text)
            ptrp_text = self.ultra_ptrp_input.text()
            if ptrp_text:
                ptrp = float(ptrp_text)
                ptrd = num * ptrp
                self.ultra_ptrd_input.setText(f"{ptrd:g}")
        except ValueError:
            pass
        self.updating_ultra_ptrd_num = False

    def validate_input(self, sender):
        validator = sender.validator()
        if validator is None:
            return
        state = validator.validate(sender.text(), 0)[0]
        if state == QDoubleValidator.State.Acceptable:
            sender.setStyleSheet("")
        elif state == QDoubleValidator.State.Intermediate:
            sender.setStyleSheet("border: 1px solid yellow;")
        else:
            sender.setStyleSheet("border: 1px solid red;")

    def update_derived(self):
        try:
            prf_str = self.prf_input.text()
            pd_str = self.pd_input.text()
            ramp_str = self.ramp_len_input.text()
            ptd_str = self.ptd_input.text()

            if not prf_str or not pd_str:
                self.duty_label.setText("N/A")
                self.validate_generate_button()
                return

            prf = float(prf_str)
            pd_ms = float(pd_str)
            ramp_ms = float(ramp_str) if ramp_str and self.ramp_shape_combo.currentText() != "None" else 0
            prp_ms = 1000 / prf if prf > 0 else 0

            if prf <= 0:
                raise ValueError("PRF must be positive")

            duty = (pd_ms / prp_ms) * 100 if prp_ms > 0 else 0
            self.duty_label.setText(f"{duty:.2f}")

            if pd_ms > prp_ms:
                self.pd_input.setStyleSheet("border: 1px solid red;")
            else:
                self.validate_input(self.pd_input)

            if ramp_ms > pd_ms / 2:
                self.ramp_len_input.setStyleSheet("border: 1px solid red;")
            else:
                self.validate_input(self.ramp_len_input)

            if ptd_str:
                ptd_ms = float(ptd_str)
                if ptd_ms < pd_ms:
                    self.ptd_input.setStyleSheet("border: 1px solid red;")
                else:
                    self.validate_input(self.ptd_input)
                if prp_ms > ptd_ms:
                    self.prp_input.setStyleSheet("border: 1px solid red;")
                    self.prf_input.setStyleSheet("border: 1px solid red;")
                else:
                    self.validate_input(self.prp_input)
                    self.validate_input(self.prf_input)

            if self.enable_ptr_checkbox.isChecked():
                ptrp_str = self.ptrp_input.text()
                if ptrp_str:
                    ptrp_s = float(ptrp_str)
                    if ptd_str and ptrp_s * 1000 < float(ptd_str):
                        self.ptrp_input.setStyleSheet("border: 1px solid red;")
                        self.ptrf_input.setStyleSheet("border: 1px solid red;")
                    else:
                        self.validate_input(self.ptrp_input)
                        self.validate_input(self.ptrf_input)

            self.validate_generate_button()

        except ValueError:
            self.duty_label.setText("Invalid")

    def validate_generate_button(self):
        mode = self.playback_mode_combo.currentText()
        if not mode:
            self.generate_btn.setEnabled(False)
            return

        core_inputs = []
        if mode in ["Matching Only", "Combined"]:
            core_inputs += [self.ptd_input, self.prf_input, self.pd_input]
            if self.ramp_shape_combo.currentText() != "None":
                core_inputs += [self.ramp_len_input]
        if mode in ["Background Only", "Combined"] and self.bg_type_combo.currentText() == "Narrowband Noise":
            core_inputs += [self.narrowband_center_input, self.narrowband_bandwidth_input]

        valid = all(self._is_input_acceptable(input) for input in core_inputs)

        if self.enable_carrier_checkbox.isChecked():
            valid &= self._is_input_acceptable(self.carrier_input)

        if self.bg_type_combo.currentText() == "Hybrid Ultrasound Mask":
            valid &= bool(self.bg_time_input.text())
            if self.hybrid_manual_radio.isChecked():
                hybrid_inputs = [
                    self.hybrid_harmonics_input,
                    self.hybrid_bandwidth_input,
                    self.hybrid_density_input,
                    self.hybrid_tone_duration_input,
                ]
                valid &= all(self._is_input_acceptable(input) for input in hybrid_inputs)
                weight_sum = (
                    self.hybrid_prf_weight_slider.value()
                    + self.hybrid_mondrian_weight_slider.value()
                    + self.hybrid_broadband_weight_slider.value()
                )
                valid &= weight_sum > 0
        elif self.bg_type_combo.currentText() == "Auditory Mondrian":
            mondrian_inputs = [
                self.mondrian_density_input,
                self.mondrian_tone_duration_input,
                self.mondrian_pf_max_input,
                self.mondrian_prf_min_input,
                self.mondrian_prf_max_input,
                self.mondrian_duty_cycle_input,
            ]
            valid &= bool(self.bg_time_input.text())
            valid &= all(self._is_input_acceptable(input) for input in mondrian_inputs)
            if all(self._is_input_acceptable(input) for input in mondrian_inputs[3:5]):
                valid &= float(self.mondrian_prf_min_input.text()) < float(self.mondrian_prf_max_input.text())
        elif self.bg_type_combo.currentText() == "Narrowband Noise":
            if all(self._is_input_acceptable(input) for input in [self.narrowband_center_input, self.narrowband_bandwidth_input]):
                center = float(self.narrowband_center_input.text())
                bandwidth = float(self.narrowband_bandwidth_input.text())
                valid &= bandwidth < 2 * center

        if self.enable_ptr_checkbox.isChecked():
            train_inputs = [self.ptrp_input, self.num_trains_input]
            valid &= all(self._is_input_acceptable(input) for input in train_inputs)
            if self._is_input_acceptable(self.ptrp_input) and self.ptd_input.text():
                try:
                    if float(self.ptrp_input.text()) * 1000 < float(self.ptd_input.text()):
                        valid = False
                except ValueError:
                    pass

        if self.ultra_enable_ptr_checkbox.isChecked():
            ultra_train_inputs = [self.ultra_ptrp_input, self.ultra_num_trains_input]
            valid &= all(self._is_input_acceptable(input) for input in ultra_train_inputs)
            if self._is_input_acceptable(self.ultra_ptrp_input) and self.ultra_ptd_input.text():
                try:
                    if float(self.ultra_ptrp_input.text()) * 1000 < float(self.ultra_ptd_input.text()):
                        valid = False
                except ValueError:
                    pass

        if self.bg_time_input.text():
            valid &= self._is_input_acceptable(self.bg_time_input)

        if self.enable_dual_checkbox.isChecked():
            valid &= self.pulse_start_input.validator().validate(self.pulse_start_input.text() or "0", 0)[0] == self.pulse_start_input.validator().State.Acceptable

        self.generate_btn.setEnabled(valid)

    def _gather_params(self, show_hybrid_prf_notice=False):
        prf_value = self._resolve_prf_value(show_notice=show_hybrid_prf_notice)
        params = {
            "enable_carrier": self.enable_carrier_checkbox.isChecked(),
            "carrier_freq": float(self.carrier_input.text()) if self.carrier_input.text() else 1000,
            "prf": prf_value,
            "pulse_width": float(self.pd_input.text()) / 1000 if self.pd_input.text() else 0.0003,
            "snr": float(self.snr_input.text()) if self.snr_checkbox.isChecked() and self.snr_input.text() else None,
            "fs": audio_engine.get_default_sample_rate(),
            "ramp_len": float(self.ramp_len_input.text()) / 1000 if self.ramp_len_input.text() and self.ramp_shape_combo.currentText() != "None" else 0,  # Set to 0 if "None"
            "ramp_shape": self.ramp_shape_combo.currentText(),
            "bg_type": self.bg_type_combo.currentText(),
            "bg_volume": self.bg_volume_slider.value() / 100.0,
            "bg_ramp_shape": self.bg_ramp_shape.currentText(),
            "bg_ramp_length": self.bg_ramp_length.value() / 1000 if self.bg_ramp_shape.currentText() != "None" else 0.0,
            "bg_center_freq": float(self.narrowband_center_input.text()) if self.narrowband_center_input.text() else 1000.0,
            "bg_bandwidth": float(self.narrowband_bandwidth_input.text()) if self.narrowband_bandwidth_input.text() else 100.0,
            "bg_noise_color": self.colored_noise_combo.currentText(),
        }
        params["hybrid_mask_mode"] = "manual" if self.hybrid_manual_radio.isChecked() else "auto"
        params["hybrid_mask_settings"] = {
            "prf_harmonics": int(self.hybrid_harmonics_input.text()) if self.hybrid_harmonics_input.text() else 10,
            "harmonic_bandwidth": float(self.hybrid_bandwidth_input.text()) if self.hybrid_bandwidth_input.text() else 200.0,
            "mondrian_density": float(self.hybrid_density_input.text()) if self.hybrid_density_input.text() else 4.0,
            "mondrian_tone_duration_ms": float(self.hybrid_tone_duration_input.text()) if self.hybrid_tone_duration_input.text() else 500.0,
            "prf_mask_weight": self.hybrid_prf_weight_slider.value() / 100.0,
            "mondrian_weight": self.hybrid_mondrian_weight_slider.value() / 100.0,
            "broadband_weight": self.hybrid_broadband_weight_slider.value() / 100.0,
        }
        params["mondrian_mask_settings"] = {
            "density": float(self.mondrian_density_input.text()) if self.mondrian_density_input.text() else 8.0,
            "tone_duration_ms": float(self.mondrian_tone_duration_input.text()) if self.mondrian_tone_duration_input.text() else 500.0,
            "pf_min": float(self.mondrian_pf_min_input.text()) if self.mondrian_pf_min_input.text() else 20.0,
            "pf_max": float(self.mondrian_pf_max_input.text()) if self.mondrian_pf_max_input.text() else 15000.0,
            "prf_min": float(self.mondrian_prf_min_input.text()) if self.mondrian_prf_min_input.text() else 1000.0,
            "prf_max": float(self.mondrian_prf_max_input.text()) if self.mondrian_prf_max_input.text() else 15000.0,
            "duty_cycle": float(self.mondrian_duty_cycle_input.text()) if self.mondrian_duty_cycle_input.text() else 50.0,
        }
        if self.ptd_input.text():
            params["train_duration"] = float(self.ptd_input.text())
        if self.enable_ptr_checkbox.isChecked():
            params["num_trains"] = float(self.num_trains_input.text()) if self.num_trains_input.text() else 1
            if self.ptrp_input.text():
                ptrp_s = float(self.ptrp_input.text())
                train_dur_ms = params.get("train_duration", 0)
                interval_ms = ptrp_s * 1000 - train_dur_ms
                if interval_ms < 0:
                    raise ValueError("PTRI too small for Pulse Train Duration")
                params["train_interval"] = interval_ms
        else:
            if "train_duration" in params:
                params["num_trains"] = 1
                params["train_interval"] = 0
        params["bg_start_ms"] = 0
        params["bg_end_ms"] = float(self.bg_time_input.text()) * 1000 if self.bg_time_input.text() else -1
        params["pulse_start_ms"] = float(self.pulse_start_input.text()) if self.pulse_start_input.text() else 0
        params["pulse_end_ms"] = -1  # Computed in on_generate for Combined; defaults to audio end for Matching Only
        if self.enable_dual_checkbox.isChecked():
            params["pulse_volume"] = self.pulse_volume_slider.value() / 100.0
        else:
            params["pulse_volume"] = self.matching_volume_slider.value() / 100.0
        params["pan"] = self.pan_slider.value() / 100.0
        return params

    def on_generate(self):
        try:
            mode = self.playback_mode_combo.currentText()
            if not mode:
                return

            params = self._gather_params(show_hybrid_prf_notice=True)

            if mode in ["Matching Only", "Combined"] and not self.ptd_input.text():
                raise ValueError("Pulse Train Duration required for matching modes")
            params["duration"] = 0.5  # Default fallback

            if mode == "Combined":
                # Pulse runs from pulse_start_ms for PTD ms; background runs from 0 for bg_end_ms.
                # Total duration is whichever ends later.
                ptd_ms = float(self.ptd_input.text()) if self.ptd_input.text() else 0
                pulse_start_ms = params["pulse_start_ms"]
                pulse_end_ms = pulse_start_ms + ptd_ms
                bg_end_ms = params.get("bg_end_ms", 0)
                params["pulse_end_ms"] = pulse_end_ms
                params["duration"] = max(pulse_end_ms, bg_end_ms) / 1000

            controller = SessionController()
            self.current_audio, self.current_time, self.current_gate, self.current_fs, self.current_pulse_audio, self.current_bg_audio = controller.generate(params, mode)
            self.last_generated_params = copy.deepcopy(params)
            self.last_generated_mode = mode

            self._update_time_plot()
            self._update_right_plot()
            self.play_btn.setEnabled(True)
            self.stop_wav_btn.setEnabled(True)
            self.save_btn.setEnabled(True)

        except ValueError as e:
            QMessageBox.critical(self, "Validation Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _get_tus_pulses_ms(self):
        """Return list of (start_ms, width_ms) pulse intervals for TUS+Mask mode, else None.
        Falls back to PTD blocks if pulse-level params are missing."""
        if self.stim_mode_combo.currentText() != "TUS + Mask":
            return None
        try:
            tus_start_ms = float(self.tus_start_input.text()) if self.tus_start_input.text() else 0.0
            ptd_ms = float(self.ultra_ptd_input.text()) if self.ultra_ptd_input.text() else 0.0
            if ptd_ms <= 0:
                return None

            pd_ms = float(self.ultra_pd_input.text()) if self.ultra_pd_input.text() else 0.0
            prf_hz = float(self.ultra_prf_input.text()) if self.ultra_prf_input.text() else 0.0
            use_pulses = pd_ms > 0 and prf_hz > 0

            if self.ultra_enable_ptr_checkbox.isChecked() and self.ultra_num_trains_input.text() and self.ultra_ptrp_input.text():
                num_trains = max(1, int(float(self.ultra_num_trains_input.text())))
                ptrp_ms = float(self.ultra_ptrp_input.text()) * 1000
            else:
                num_trains = 1
                ptrp_ms = 0.0

            xranges = []
            MAX_BARS = 2000
            if use_pulses:
                period_ms = 1000.0 / prf_hz
                for i in range(num_trains):
                    train_start = tus_start_ms + i * ptrp_ms
                    t = train_start
                    while t - train_start < ptd_ms:
                        xranges.append((t, pd_ms))
                        t += period_ms
                        if len(xranges) >= MAX_BARS:
                            break
                    if len(xranges) >= MAX_BARS:
                        break
            else:
                for i in range(num_trains):
                    train_start = tus_start_ms + i * ptrp_ms
                    xranges.append((train_start, ptd_ms))

            return xranges if xranges else None
        except (ValueError, TypeError):
            return None

    def _update_time_plot(self):
        if self.current_audio is None:
            return

        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else 1000.0
        plotting.update_time_plot(self.time_ax, self.current_time, self.current_audio, self.current_gate, self.current_bg_audio, self.zoom_view, self.ramp_len_input.text(), self.current_fs, prf, tus_pulses_ms=self._get_tus_pulses_ms())

        self.time_fig.tight_layout()
        self.time_canvas.draw_idle()

    def _update_right_plot(self):
        if self.current_audio is None:
            return

        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else None
        plotting.update_right_plot(self.right_fig, self.current_audio, self.current_fs, self.show_spectrogram_checkbox.isChecked(), self.show_fft_checkbox.isChecked(), prf)

        self.right_fig.tight_layout()
        self.right_canvas.draw_idle()

    def clear_generated_output(self):
        self.current_audio = None
        self.current_time = None
        self.current_gate = None
        self.current_fs = None
        self.current_pulse_audio = None
        self.current_bg_audio = None
        self.last_generated_params = None
        self.last_generated_mode = None

        self.time_ax.clear()
        self.time_canvas.draw_idle()

        self.right_fig.clear()
        self.right_canvas.draw_idle()

        self.play_btn.setEnabled(False)
        self.stop_wav_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def _track_plot_popup(self, dialog):
        self._plot_popups.append(dialog)
        dialog.finished.connect(lambda *_: self._plot_popups.remove(dialog) if dialog in self._plot_popups else None)

    def _on_show_timeline(self):
        if not self.last_execution_log:
            return
        dialog = plotting.open_sonication_timeline_popup(self, self.last_execution_log)
        self._track_plot_popup(dialog)

    def _on_time_canvas_click(self, event):
        if not getattr(event, "dblclick", False) or self.current_audio is None:
            return
        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else 1000.0
        dialog = plotting.open_time_plot_popup(
            self,
            self.current_time,
            self.current_audio,
            self.current_gate,
            self.current_bg_audio,
            self.zoom_view,
            self.ramp_len_input.text(),
            self.current_fs,
            prf,
            tus_pulses_ms=self._get_tus_pulses_ms(),
        )
        self._track_plot_popup(dialog)

    def _on_right_canvas_click(self, event):
        if not getattr(event, "dblclick", False) or self.current_audio is None:
            return
        prf = self.last_generated_params.get("prf") if self.last_generated_params else None
        if prf is None:
            prf = float(self.prf_input.text()) if self.prf_input.text() else None
        dialog = plotting.open_right_plot_popup(
            self,
            self.current_audio,
            self.current_fs,
            self.show_spectrogram_checkbox.isChecked(),
            self.show_fft_checkbox.isChecked(),
            prf,
        )
        self._track_plot_popup(dialog)

    def on_play(self):
        if self.current_audio is None:
            QMessageBox.warning(self, "No audio", "Generate first.")
            return
        try:
            self.stop_wav_btn.setEnabled(True)
            audio_engine.play(self.current_audio, self.current_fs)
        except Exception as e:
            QMessageBox.critical(self, "Playback error", str(e))

    def on_stop(self):
        audio_engine.stop()

    def on_stop_sonication(self):
        if self._countdown_timer is not None:
            self._abort_sonication_countdown()
            return
        if self.tpo_ser is None or self.stimulation_stop_event is None:
            QMessageBox.information(self, "No Sonication", "No active sonication is running.")
            return

        self.stimulation_stop_event.set()
        try:
            self.tpo_ser.reset_input_buffer()
        except Exception:
            pass

        try:
            nf_stop(self.tpo_ser)
        except Exception as exc:
            QMessageBox.warning(self, "Stop Sonication", f"Stop command sent, but the device reply was not clean:\n{exc}")

        self.stop_sonication_btn.setEnabled(False)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Stop requested. Waiting for device confirmation...")

    def _default_save_basename(self):
        mode = self.last_generated_mode or self.playback_mode_combo.currentText() or "audio"
        slug = mode.lower().replace(" + ", "_").replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{slug}_{timestamp}"

    def _audio_channel_count(self, audio):
        if audio is None:
            return 0
        if getattr(audio, "ndim", 1) == 1:
            return 1
        return int(audio.shape[1])

    def _build_save_metadata(self, saved_files):
        duration_seconds = 0.0
        if self.current_audio is not None and self.current_fs:
            duration_seconds = len(self.current_audio) / float(self.current_fs)

        is_connected = self.tpo_ser is not None

        metadata = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "playback_mode": self.last_generated_mode or self.playback_mode_combo.currentText(),
            "sample_rate_hz": int(self.current_fs) if self.current_fs is not None else None,
            "duration_seconds": duration_seconds,
            "channels": self._audio_channel_count(self.current_audio),
            "generated_files": saved_files,
            "generation_params": self._filtered_generation_params(self.last_generated_params),
        }

        if is_connected:
            metadata["stimulation_mode"] = self.stim_mode_combo.currentText()
            metadata["execution_log"] = list(self.last_execution_log)
            ultra_ptr_enabled = self.ultra_enable_ptr_checkbox.isChecked()
            ultrasound_params = {
                "connected_port": self.connected_port,
                "firmware": self.connected_firmware,
                "transducer_index": self.transducer_combo.currentData(),
                "transducer_label": self.transducer_combo.currentText(),
                "focal_depth_mm": float(self.focal_depth_input.text()) if self.focal_depth_input.text() else None,
                "isppa_w_cm2": float(self.isppa_input.text()) if self.isppa_input.text() else None,
                "pulse_duration_ms": float(self.ultra_pd_input.text()) if self.ultra_pd_input.text() else None,
                "pri_ms": float(self.ultra_prp_input.text()) if self.ultra_prp_input.text() else None,
                "pulse_train_duration_ms": float(self.ultra_ptd_input.text()) if self.ultra_ptd_input.text() else None,
                "ramp_shape": self.ultra_ramp_shape_combo.currentText(),
                "ramp_length_ms": float(self.ultra_ramp_len_input.text()) if self.ultra_ramp_len_input.text() else 0.0,
                "enforce_limits": self.enforce_limits_checkbox.isChecked(),
                "pulse_train_repetition_enabled": ultra_ptr_enabled,
            }
            if ultra_ptr_enabled:
                ultrasound_params["num_trains"] = float(self.ultra_num_trains_input.text()) if self.ultra_num_trains_input.text() else None
                ultrasound_params["ptri_seconds"] = float(self.ultra_ptrp_input.text()) if self.ultra_ptrp_input.text() else None
            metadata["ultrasound_params"] = ultrasound_params

        return metadata

    def _filtered_generation_params(self, params):
        if not params:
            return None

        raw = copy.deepcopy(params)
        mode = self.last_generated_mode or self.playback_mode_combo.currentText()
        bg_type = raw.get("bg_type")
        ptr_enabled = self.enable_ptr_checkbox.isChecked()

        is_pulse = mode in ("Matching Only", "Combined")
        is_background = mode in ("Background Only", "Combined")
        is_combined = mode == "Combined"

        # Compute PTR timing up-front so both pulse and combined sections can use them
        ptri_seconds = ptrd_seconds = active_train_span_seconds = None
        if ptr_enabled and raw.get("train_duration") is not None and raw.get("train_interval") is not None:
            ptri_seconds = (raw["train_duration"] + raw["train_interval"]) / 1000
            if raw.get("num_trains") is not None:
                ptrd_seconds = raw["num_trains"] * ptri_seconds
                active_train_span_seconds = (
                    raw["num_trains"] * (raw["train_duration"] / 1000)
                    + max(raw["num_trains"] - 1, 0) * (raw["train_interval"] / 1000)
                )

        formatted = {}

        # ── Pulse params (Matching Only + Combined) ───────────────
        if is_pulse:
            formatted["pulse_train_duration_ms"] = raw.get("train_duration")
            formatted["prf_hz"] = raw.get("prf")
            formatted["pri_ms"] = 1000 / raw["prf"] if raw.get("prf") not in (None, 0) else None
            formatted["pulse_width_ms"] = raw["pulse_width"] * 1000 if raw.get("pulse_width") is not None else None
            formatted["carrier_frequency_hz"] = raw.get("carrier_freq") if raw.get("enable_carrier") else None
            formatted["ramp_shape"] = raw.get("ramp_shape")
            formatted["ramp_length_ms"] = (
                raw["ramp_len"] * 1000
                if raw.get("ramp_len") is not None and raw.get("ramp_shape") != "None"
                else None
            )
            formatted["signal_to_noise_ratio"] = raw.get("snr")
            formatted["pulse_train_repetition_enabled"] = ptr_enabled
            if ptr_enabled:
                formatted["pulse_train_repetition_interval_seconds"] = ptri_seconds
                formatted["pulse_train_repetition_duration_seconds"] = ptrd_seconds
                formatted["number_of_trains"] = raw.get("num_trains")

        # ── Background params (Background Only + Combined) ────────
        if is_background:
            formatted["background_type"] = bg_type
            formatted["background_time_seconds"] = (
                None if raw.get("bg_end_ms") in (None, -1) else raw["bg_end_ms"] / 1000
            )
            formatted["background_volume_percent"] = (
                raw["bg_volume"] * 100 if raw.get("bg_volume") is not None else None
            )
            formatted["background_ramp_shape"] = raw.get("bg_ramp_shape")
            formatted["background_ramp_length_ms"] = (
                raw["bg_ramp_length"] * 1000
                if raw.get("bg_ramp_length") is not None and raw.get("bg_ramp_shape") != "None"
                else None
            )

            if bg_type == "Narrowband Noise":
                formatted["background_center_frequency_hz"] = raw.get("bg_center_freq")
                formatted["background_bandwidth_hz"] = raw.get("bg_bandwidth")
            elif bg_type == "Colored Noise":
                formatted["background_noise_color"] = raw.get("bg_noise_color")
            elif bg_type == "Hybrid Ultrasound Mask":
                hybrid = raw.get("hybrid_mask_settings", {})
                formatted["hybrid_mask_mode"] = raw.get("hybrid_mask_mode")
                formatted["hybrid_mask_settings"] = {
                    "prf_harmonics": hybrid.get("prf_harmonics"),
                    "harmonic_bandwidth_hz": hybrid.get("harmonic_bandwidth"),
                    "mondrian_density_tones_per_second": hybrid.get("mondrian_density"),
                    "mondrian_tone_duration_ms": hybrid.get("mondrian_tone_duration_ms"),
                    "prf_mask_weight_percent": hybrid.get("prf_mask_weight", 0) * 100 if hybrid.get("prf_mask_weight") is not None else None,
                    "mondrian_weight_percent": hybrid.get("mondrian_weight", 0) * 100 if hybrid.get("mondrian_weight") is not None else None,
                    "broadband_weight_percent": hybrid.get("broadband_weight", 0) * 100 if hybrid.get("broadband_weight") is not None else None,
                }
            elif bg_type == "Auditory Mondrian":
                mondrian = raw.get("mondrian_mask_settings", {})
                formatted["mondrian_mask_settings"] = {
                    "density_tones_per_second": mondrian.get("density"),
                    "tone_duration_ms": mondrian.get("tone_duration_ms"),
                    "pf_min_hz": mondrian.get("pf_min"),
                    "pf_max_hz": mondrian.get("pf_max"),
                    "prf_min_hz": mondrian.get("prf_min"),
                    "prf_max_hz": mondrian.get("prf_max"),
                    "duty_cycle_percent": mondrian.get("duty_cycle"),
                }

        # ── Volume + timing ───────────────────────────────────────
        if is_combined:
            pulse_start_s = raw["pulse_start_ms"] / 1000 if raw.get("pulse_start_ms") is not None else None
            formatted["pulse_start_seconds"] = pulse_start_s
            formatted["pulse_end_seconds"] = (
                None if raw.get("pulse_end_ms") in (None, -1) else raw["pulse_end_ms"] / 1000
            )
            if ptr_enabled and pulse_start_s is not None:
                if ptrd_seconds is not None:
                    formatted["pulse_train_window_end_seconds"] = pulse_start_s + ptrd_seconds
                if active_train_span_seconds is not None:
                    formatted["pulse_train_active_end_seconds"] = pulse_start_s + active_train_span_seconds
            formatted["pulse_volume_percent"] = (
                raw["pulse_volume"] * 100 if raw.get("pulse_volume") is not None else None
            )
        elif is_pulse:
            formatted["matching_volume_percent"] = (
                raw["pulse_volume"] * 100 if raw.get("pulse_volume") is not None else None
            )

        # ── Pan ───────────────────────────────────────────────────
        pan_value = raw.get("pan")
        if pan_value is not None:
            left_gain, right_gain = self._compute_pan_gains(float(pan_value))
            formatted["pan"] = {
                "normalized": pan_value,
                "left_channel_volume_percent": round(left_gain * 100, 2),
                "right_channel_volume_percent": round(right_gain * 100, 2),
            }

        formatted["sample_rate_hz"] = raw.get("fs")
        return formatted

    def on_save(self):
        if self.current_audio is None:
            QMessageBox.warning(self, "No audio", "Generate first.")
            return

        default_name = self._default_save_basename()
        filepath, _ = QFileDialog.getSaveFileName(self, "Save session", default_name, "WAV files (*.wav)")
        if not filepath:
            return

        target_path = Path(filepath)
        if target_path.suffix.lower() != ".wav":
            target_path = target_path.with_suffix(".wav")

        saved_files = {}

        try:
            audio_engine.save_wav(self.current_audio, self.current_fs, str(target_path))
            saved_files["main_wav"] = target_path.name

            if self.last_generated_mode == "Combined" and self.current_bg_audio is not None:
                bg_path = target_path.with_name(f"{target_path.stem}_background.wav")
                audio_engine.save_wav(self.current_bg_audio, self.current_fs, str(bg_path))
                saved_files["background_wav"] = bg_path.name

            if self.last_generated_mode == "Combined" and self.current_pulse_audio is not None:
                pulse_path = target_path.with_name(f"{target_path.stem}_pulse.wav")
                audio_engine.save_wav(self.current_pulse_audio, self.current_fs, str(pulse_path))
                saved_files["pulse_wav"] = pulse_path.name

            metadata_path = target_path.with_suffix(".json")
            metadata = self._build_save_metadata(saved_files)
            metadata["generated_files"]["metadata_json"] = metadata_path.name
            session_logger.save_session_data(metadata_path, metadata)

            saved_summary = "\n".join(str(target_path.parent / name) for name in saved_files.values())
            QMessageBox.information(self, "Saved", f"Saved files:\n{saved_summary}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def on_sonicate(self):
        if self.tpo_ser is None:
            QMessageBox.warning(self, "TPO Not Connected", "Connect to the NeuroFUS device before sonication.")
            return
        try:
            self._pending_stim_request = self._build_stimulation_request()
        except ValueError as exc:
            QMessageBox.critical(self, "Validation Error", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        if not self._confirm_sonication():
            self._pending_stim_request = None
            return
        self._start_sonication_countdown()

    def _start_sonication_countdown(self):
        self._countdown_remaining = 5
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._tick_sonication_countdown)
        self.sonicate_btn.setText(f"Starting in {self._countdown_remaining}s…")
        self.sonicate_btn.setEnabled(False)
        self._update_sonicate_btn_style()
        self.stop_sonication_btn.setEnabled(True)
        self.stop_sonication_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
        )
        self._countdown_timer.start(1000)

    def _tick_sonication_countdown(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self._countdown_timer = None
            self.sonicate_btn.setText("Start Sonication")
            self.sonicate_btn.setEnabled(True)
            self._update_sonicate_btn_style()
            self._launch_sonication()
        else:
            self.sonicate_btn.setText(f"Starting in {self._countdown_remaining}s…")

    def _abort_sonication_countdown(self):
        self._countdown_timer.stop()
        self._countdown_timer = None
        self._countdown_remaining = 0
        self._pending_stim_request = None
        self.sonicate_btn.setText("Start Sonication")
        self.sonicate_btn.setEnabled(True)
        self._update_sonicate_btn_style()
        self.stop_sonication_btn.setEnabled(False)
        self.stop_sonication_btn.setStyleSheet("")

    def _launch_sonication(self):
        try:
            self.set_sonication_running(True)
            params = self._pending_stim_request
            self._pending_stim_request = None
            params["stimulation_params"]["stop_event"] = self.stimulation_stop_event
            self._sono_thread = QThread(self)
            self._sono_worker = StimulationWorker(params)
            self._sono_worker.moveToThread(self._sono_thread)
            self._sono_thread.started.connect(self._sono_worker.run)
            self._sono_worker.finished.connect(self._on_sonication_success)
            self._sono_worker.failed.connect(self._on_sonication_failed)
            self._sono_worker.finished.connect(self._sono_thread.quit)
            self._sono_worker.failed.connect(self._sono_thread.quit)
            self._sono_thread.finished.connect(self._cleanup_sono_worker)
            self._sono_thread.start()
        except Exception as exc:
            self.set_sonication_running(False)
            QMessageBox.critical(self, "Sonication Error", str(exc))

    def _on_sonication_success(self, result):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sonication complete: {result['message']}")
        self.set_sonication_running(False)
        self._update_execution_log(result.get("execution_log"))

    def _on_sonication_failed(self, message):
        self.set_sonication_running(False)
        self._update_execution_log([])
        QMessageBox.critical(self, "Sonication Failed", message)

    def _cleanup_sono_worker(self):
        self.set_sonication_running(False)
        if hasattr(self, '_sono_worker') and self._sono_worker is not None:
            self._sono_worker.deleteLater()
            self._sono_worker = None
        if hasattr(self, '_sono_thread') and self._sono_thread is not None:
            self._sono_thread.deleteLater()
            self._sono_thread = None

    def _available_port_entries(self):
        entries = []
        for port in serial.tools.list_ports.comports():
            label = port.device
            if port.description and port.description != "n/a":
                label = f"{port.device} - {port.description}"
            entries.append((label, port.device))
        entries.sort(key=lambda item: item[1])
        return entries

    def refresh_tpo_ports(self):
        current_value = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        self.port_combo.addItem("Auto", None)
        for label, device in self._available_port_entries():
            self.port_combo.addItem(label, device)

        if current_value is not None:
            index = self.port_combo.findData(current_value)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setCurrentIndex(0)
        else:
            self.port_combo.setCurrentIndex(0)
        self.port_combo.blockSignals(False)

    def _update_sonicate_btn_style(self):
        if not self.sonicate_btn.isEnabled():
            self.sonicate_btn.setStyleSheet("")
        elif not self.enforce_limits_checkbox.isChecked():
            self.sonicate_btn.setStyleSheet(
                "QPushButton { background-color: #e67e22; color: white; font-weight: bold; }"
            )
        else:
            self.sonicate_btn.setStyleSheet(
                "QPushButton { background-color: #27ae60; color: white; font-weight: bold; }"
            )

    def _on_enforce_limits_toggled(self, checked):
        if not checked and not self._confirm_disable_limits():
            self.enforce_limits_checkbox.blockSignals(True)
            self.enforce_limits_checkbox.setChecked(True)
            self.enforce_limits_checkbox.blockSignals(False)
        self._update_sonicate_btn_style()

    def _confirm_disable_limits(self) -> bool:
        dlg = QDialog(self)
        dlg.setWindowTitle("Disable safety limits")
        dlg.setModal(True)
        dlg.setMinimumWidth(460)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(14)

        msg = QLabel(
            "<b style='font-size:13px;'>&#9888;&nbsp; You are disabling hardware safety limits.</b>"
            "<br><br>"
            "The device will <b>no longer enforce</b> maximum Isppa / Ispta thresholds. "
            "There will be no automatic safety checks."
            "<br><br>"
            "<b>By proceeding, you personally confirm that:</b>"
            "<ul style='margin-top:4px; margin-bottom:4px;'>"
            "<li>All parameters fall within your IRB-approved protocol.</li>"
            "<li>Operation follows the ITRUSST consortium recommendations on biophysical safety "
            "and device operation "
            "(<a href='https://doi.org/10.1016/j.brs.2025.10.007'>Safety Recommendations</a>; "
            "<a href='https://doi.org/10.1016/j.clinph.2025.01.004'>Practical Guide</a>).</li>"
            "<li>You have independently validated these parameters with a qualified expert.</li>"
            "</ul>"
            "<b style='color:#c0392b;'>The developers accept no liability whatsoever for any "
            "outcomes.</b>"
        )
        msg.setWordWrap(True)
        msg.setOpenExternalLinks(True)
        msg.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        keep_btn = QPushButton("Keep limits ON")
        keep_btn.setDefault(True)
        keep_btn.clicked.connect(dlg.reject)
        disable_btn = QPushButton("Disable limits")
        disable_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
        )
        disable_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(keep_btn)
        btn_row.addWidget(disable_btn)
        layout.addLayout(btn_row)

        return dlg.exec() == QDialog.DialogCode.Accepted

    def _confirm_sonication(self) -> bool:
        stim_mode = self.stim_mode_combo.currentText()
        limits_on = self.enforce_limits_checkbox.isChecked()

        lines = [f"<b>Sonication mode:</b> {stim_mode}", "<hr>"]
        lines.append(f"• Transducer: {self.transducer_combo.currentText() or '—'}")
        lines.append(f"• Focal depth: {self.focal_depth_input.text() or '—'} mm")
        lines.append(f"• ISPPA: {self.isppa_input.text() or '—'} W/cm²")
        lines.append(f"• Pulse duration: {self.ultra_pd_input.text() or '—'} ms")
        lines.append(f"• PRI: {self.ultra_prp_input.text() or '—'} ms")
        lines.append(f"• Pulse train duration: {self.ultra_ptd_input.text() or '—'} ms")

        ramp_shape = self.ultra_ramp_shape_combo.currentText()
        if ramp_shape == "None":
            lines.append("• Ramp: None")
        else:
            lines.append(f"• Ramp: {ramp_shape} / {self.ultra_ramp_len_input.text() or '—'} ms")

        limits_text = (
            "On"
            if limits_on
            else "<span style='color:#e74c3c;'><b>OFF — limits not enforced</b></span>"
        )
        lines.append(f"• Enforce safety limits: {limits_text}")

        if self.ultra_enable_ptr_checkbox.isChecked():
            num_trains = self.ultra_num_trains_input.text() or "—"
            ptri = self.ultra_ptrp_input.text() or "—"
            lines.append(f"• PTR: {num_trains} trains at {ptri} s interval")

        if stim_mode == "TUS + Mask":
            lines.append("<hr>")
            tus_start = self.tus_start_input.text() or "0"
            lines.append(f"• TUS start: {tus_start} ms after mask start")

        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm sonication parameters")
        dlg.setModal(True)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        lbl = QLabel("<br>".join(lines))
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        confirm_btn = QPushButton("Confirm")
        confirm_btn.setDefault(True)
        if not limits_on:
            confirm_btn.setStyleSheet(
                "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
            )
        confirm_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

        return dlg.exec() == QDialog.DialogCode.Accepted

    def _set_tpo_connected_state(self, connected):
        self.port_combo.setEnabled(not connected)
        self.refresh_ports_btn.setEnabled(not connected)
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.sonicate_btn.setEnabled(connected)
        self._update_sonicate_btn_style()

    def _find_neurofus_connection(self):
        last_error = None
        for _, device in self._available_port_entries():
            try:
                ser, ok, firmware = nf_open(device)
                if ok:
                    return ser, device, firmware
                ser.close()
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise RuntimeError(f"No valid NeuroFUS device found. Last error: {last_error}")
        raise RuntimeError("No valid NeuroFUS device found.")

    def _populate_transducers(self):
        self.transducer_combo.clear()
        if self.tpo_ser is None:
            return

        try:
            raw_list = nf_xdr_list(self.tpo_ser)
            items = [item.strip() for item in raw_list.split(",") if item.strip()]
            if not items:
                self.transducer_combo.addItem("No transducers reported")
                return

            for index, item in enumerate(items):
                self.transducer_combo.addItem(f"{index}: {item}", index)
        except Exception as exc:
            self.transducer_combo.addItem("Unable to read transducers")
            QMessageBox.warning(self, "Transducers", f"Connected, but failed to read transducer list:\n{exc}")

    def _show_eula_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("End User License Agreement")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        title_label = QLabel("Do you accept the End User License Agreement (EULA)?")
        title_label.setWordWrap(True)
        font = title_label.font()
        font.setBold(True)
        title_label.setFont(font)
        layout.addWidget(title_label)

        body_label = QLabel(
            "<p>By clicking Accept, you acknowledge and agree to the following terms:</p>"
            "<p>&#8226; <b>Authorized Use:</b> This software is intended solely for use by "
            "qualified researchers and clinicians operating within applicable ethical, regulatory, "
            "and institutional frameworks. It is your sole and exclusive responsibility to ensure "
            "that all stimulation parameters are safe, appropriate for each subject, and compliant "
            "with all applicable guidelines, regulations, and institutional requirements.</p>"
            "<p>&#8226; <b>License:</b> This software is made available for non-commercial "
            "research and academic use only. You are free to use, copy, modify, and redistribute "
            "this software for non-commercial purposes, provided that the copyright notice and "
            "this permission notice are included in all copies or substantial portions of the "
            "software. Commercial use of any kind — including selling, sublicensing for "
            "commercial gain, or incorporation into commercial products or services — is strictly "
            "prohibited without prior written permission from the developers. The citation "
            "requirements below are an additional condition of this license.</p>"
            "<p>&#8226; <b>Citation Requirements:</b> Any use of this software that contributes "
            "to or informs a published work, conference presentation, poster, grant application, "
            "or any other public dissemination must include a citation to this software as "
            "specified in the citation guidance on the GitHub repository from which this software "
            "was downloaded. Once a peer-reviewed publication describing this software has been "
            "published, that publication must additionally be cited in all such works. Compliance "
            "with these citation requirements is a condition of use, and failure to comply "
            "constitutes a breach of this agreement.</p>"
            "<p>&#8226; <b>Device Safety and Regulatory Compliance:</b> All use of the NeuroFUS "
            "device must operate within parameters approved by an independent Institutional Review "
            "Board (IRB) or equivalent ethics authority, comply with all applicable regulatory "
            "requirements, and follow the recommendations of the ITRUSST consortium with regard "
            "to biophysical safety and general device operation "
            "(<a href='https://doi.org/10.1016/j.brs.2025.10.007'>Safety Recommendations</a>; "
            "<a href='https://doi.org/10.1016/j.clinph.2025.01.004'>Practical Guide</a>). "
            "When the NeuroFUS device is connected, it is your sole responsibility to prevent "
            "harm to subjects and damage to the device, including ensuring the device never "
            "sonicates directly in air.</p>"
            "<p>&#8226; <b>Disclaimer of Warranties:</b> THIS SOFTWARE IS PROVIDED “AS "
            "IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT "
            "LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, "
            "ACCURACY, OR NON-INFRINGEMENT. THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE "
            "OF THE SOFTWARE IS WITH YOU.</p>"
            "<p>&#8226; <b>Limitation of Liability:</b> UNDER NO CIRCUMSTANCES AND FOR NO "
            "REASON WHATSOEVER SHALL THE DEVELOPERS, AUTHORS, AND CONTRIBUTORS OF THIS SOFTWARE "
            "ACCEPT ANY LIABILITY WHATSOEVER FOR ANY DAMAGES, LOSSES, INJURIES, HARM, OR ADVERSE "
            "OUTCOMES OF ANY KIND ARISING FROM OR IN CONNECTION WITH THE USE, MISUSE, "
            "MODIFICATION, OR DISTRIBUTION OF THIS SOFTWARE OR THE INABILITY TO USE IT, "
            "INCLUDING BUT NOT LIMITED TO DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, "
            "OR PUNITIVE DAMAGES, PERSONAL INJURY, PROPERTY DAMAGE, LOSS OF DATA, OR FINANCIAL "
            "LOSS, REGARDLESS OF CAUSE, WHETHER IN CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, "
            "OR ANY OTHER LEGAL THEORY. THIS EXCLUSION IS ABSOLUTE AND APPLIES WITHOUT ANY "
            "EXCEPTION WHATSOEVER — INCLUDING WHEN THE SOFTWARE IS USED IN FULL ACCORDANCE WITH "
            "ALL APPLICABLE GUIDELINES AND REGULATIONS, WHEN SAFETY LIMITS ARE ENFORCED, WHEN "
            "ALL IRB REQUIREMENTS HAVE BEEN MET, AND REGARDLESS OF WHETHER THE DEVELOPERS HAVE "
            "BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.</p>"
            "<p>&#8226; <b>Indemnification:</b> You agree to indemnify, defend, and hold harmless "
            "the developers, authors, and contributors of this software from and against any and "
            "all claims, liabilities, damages, losses, and expenses (including reasonable legal "
            "costs) arising from or related to your use of this software or any breach of any "
            "term of this agreement.</p>"
            "<p>&#8226; <b>Third-Party Terms:</b> By clicking Accept, you also confirm that you "
            "have read and accept the NeuroFUS End User License Agreement.</p>"
            "<p><i>If you do not accept these terms, click Decline and do not proceed.</i></p>"
        )
        body_label.setWordWrap(True)
        body_label.setOpenExternalLinks(True)
        body_label.setTextFormat(Qt.TextFormat.RichText)

        scroll = QScrollArea()
        scroll.setWidget(body_label)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(420)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        decline_btn = QPushButton("Decline")
        accept_btn = QPushButton("Accept")
        accept_btn.setDefault(True)
        decline_btn.clicked.connect(dialog.reject)
        accept_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(decline_btn)
        btn_layout.addWidget(accept_btn)
        layout.addLayout(btn_layout)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def on_connect(self):
        if self.tpo_ser is not None:
            return

        if not self._show_eula_dialog():
            return

        selected_port = self.port_combo.currentData()  # None = Auto

        self._connect_countdown_timer = QTimer(self)
        self._connect_countdown_timer.timeout.connect(self._tick_connect_countdown)

        self.status_label.setText("Connecting... (may take ~15s)")

        self._connect_thread = QThread(self)
        self._connect_worker = ConnectWorker(selected_port)
        self._connect_worker.moveToThread(self._connect_thread)
        self._connect_thread.started.connect(self._connect_worker.run)
        self._connect_worker.device_opened.connect(self._on_device_opened)
        self._connect_worker.finished.connect(self._on_connect_success)
        self._connect_worker.failed.connect(self._on_connect_failed)
        self._connect_worker.finished.connect(self._connect_thread.quit)
        self._connect_worker.failed.connect(self._connect_thread.quit)
        self._connect_thread.start()

    def _on_device_opened(self):
        self._connect_countdown_remaining = 10
        self.status_label.setText(f"Initialising... ({self._connect_countdown_remaining}s)")
        self._connect_countdown_timer.start(1000)

    def _tick_connect_countdown(self):
        self._connect_countdown_remaining -= 1
        if self._connect_countdown_remaining <= 0:
            self._connect_countdown_timer.stop()
            self.status_label.setText("Initialising...")
        else:
            self.status_label.setText(f"Initialising... ({self._connect_countdown_remaining}s)")

    def _on_connect_success(self, ser, connected_port, firmware):
        self._connect_countdown_timer.stop()
        self.tpo_ser = ser
        self.connected_port = connected_port
        self.connected_firmware = firmware
        self.status_label.setText(f"Connected: {connected_port} (Firmware {firmware})")
        self._set_tpo_connected_state(True)
        self._populate_transducers()
        if firmware != EXPECTED_FIRMWARE:
            QMessageBox.warning(
                self,
                "WARNING",
                f"!WARNING!\n\n"
                f"This GUI was developed specifically for NeuroFUS Firmware Version {EXPECTED_FIRMWARE}\n\n"
                f"Your firmware version is {firmware}.\n\n"
                f"Operating a system not using firmware version {EXPECTED_FIRMWARE} "
                f"may lead to errors or unexpected output.\n\n"
                f"If you choose to proceed, proceed with caution.",
            )

    def _on_connect_failed(self, message):
        self._connect_countdown_timer.stop()
        self.tpo_ser = None
        self.connected_port = None
        self.connected_firmware = None
        self.status_label.setText("Disconnected")
        QMessageBox.critical(self, "TPO Connection Error", message)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.tpo_ser is not None:
            self._escape_emergency_stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def _escape_emergency_stop(self):
        if self._countdown_timer is not None:
            self._abort_sonication_countdown()

        if self.stimulation_stop_event is not None:
            self.stimulation_stop_event.set()
            try:
                self.tpo_ser.reset_input_buffer()
            except Exception:
                pass
            try:
                nf_stop(self.tpo_ser)
            except Exception:
                pass
            self.set_sonication_running(False)

        try:
            self.tpo_ser.close()
        except Exception:
            pass
        finally:
            self.tpo_ser = None
            self.connected_port = None
            self.connected_firmware = None

        self.transducer_combo.clear()
        self.status_label.setText("Disconnected")
        self._set_tpo_connected_state(False)
        self.stop_sonication_btn.setEnabled(False)
        self.active_sonication_window = None
        self.refresh_tpo_ports()

    def on_disconnect(self):
        if self.stimulation_stop_event is not None:
            QMessageBox.warning(self, "TPO Busy", "Stop the active sonication before disconnecting the device.")
            return

        if self.tpo_ser is not None:
            try:
                self.tpo_ser.close()
            except Exception as exc:
                QMessageBox.warning(self, "TPO Disconnect", f"Error while closing port:\n{exc}")
            finally:
                self.tpo_ser = None
                self.connected_port = None
                self.connected_firmware = None

        self.transducer_combo.clear()
        self.status_label.setText("Disconnected")
        self._set_tpo_connected_state(False)
        self.stop_sonication_btn.setEnabled(False)
        self.stimulation_stop_event = None
        self.active_sonication_window = None
        self.refresh_tpo_ports()

    def on_stim_mode_changed(self, text):
        visible = text == "TUS + Mask"
        if hasattr(self, "show_timeline_btn"):
            self.show_timeline_btn.setVisible(visible)
            if not visible:
                self.show_timeline_btn.setEnabled(False)
        self.tus_start_input.setVisible(visible)
        self.execution_log_label.setVisible(visible)
        self.execution_log_combo.setVisible(visible)
        if visible:
            self._update_execution_log([])
        else:
            self.last_execution_log = []
        if visible:
            playback_mode = self.last_generated_mode or self.playback_mode_combo.currentText()
            maybe_show_tus_mask_notice(self, playback_mode)

    def _update_execution_log(self, entries):
        if not hasattr(self, "execution_log_combo"):
            return
        self.last_execution_log = list(entries or [])
        if hasattr(self, "show_timeline_btn"):
            self.show_timeline_btn.setEnabled(bool(entries))
        self.execution_log_combo.clear()
        if not entries:
            self.execution_log_combo.addItem("No execution events yet")
            return
        self.execution_log_combo.addItems(entries)

    def _connect_tus_plot_refresh(self):
        """Refresh the time plot whenever TUS+Mask timing parameters change."""
        def _refresh(*_):
            if self.current_audio is not None:
                self._update_time_plot()

        self.stim_mode_combo.currentTextChanged.connect(_refresh)
        self.tus_start_input.textChanged.connect(_refresh)
        self.ultra_ptd_input.textChanged.connect(_refresh)
        self.ultra_prf_input.textChanged.connect(_refresh)
        self.ultra_pd_input.textChanged.connect(_refresh)
        self.ultra_enable_ptr_checkbox.toggled.connect(_refresh)
        self.ultra_num_trains_input.textChanged.connect(_refresh)
        self.ultra_ptrp_input.textChanged.connect(_refresh)

    def _connect_dirty_state_tracking(self):
        for widget in self.findChildren(QLineEdit):
            widget.textChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QComboBox):
            widget.currentTextChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QSlider):
            widget.valueChanged.connect(self.on_settings_changed)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self.on_settings_changed)
        for widget in self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(self.on_settings_changed)

    def _on_enable_carrier_toggled(self, checked):
        if checked and not self.carrier_input.text():
            self.carrier_input.setText("14000")
        self._update_carrier_input_state()

    def _update_carrier_input_state(self):
        self.carrier_input.setEnabled(self.enable_carrier_checkbox.isChecked())

    def on_settings_changed(self, *_):
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(False)
        if hasattr(self, "stop_wav_btn"):
            self.stop_wav_btn.setEnabled(False)
        if hasattr(self, "save_btn"):
            self.save_btn.setEnabled(False)

    def _build_stimulation_params(self):
        if self.tpo_ser is None:
            raise ValueError("NeuroFUS device is not connected.")

        xdr_index = self.transducer_combo.currentData()
        if xdr_index is None:
            raise ValueError("Select a valid transducer before sonication.")

        if not self.ultra_pd_input.text():
            raise ValueError("Pulse Duration is required.")
        if not self.ultra_prp_input.text():
            raise ValueError("PRI is required.")
        if not self.ultra_ptd_input.text():
            raise ValueError("Pulse Train Duration is required.")
        if not self.focal_depth_input.text():
            raise ValueError("Focal Depth is required.")
        if not self.isppa_input.text():
            raise ValueError("ISPPA is required.")

        # --- Pre-validate all parameters before countdown starts ---
        pd_ms = float(self.ultra_pd_input.text())
        pri_ms = float(self.ultra_prp_input.text())
        ptd_ms = float(self.ultra_ptd_input.text())
        depth_mm = float(self.focal_depth_input.text())
        isppa_w = float(self.isppa_input.text())
        isppa_mw = isppa_w * 1000.0

        if pd_ms * 1000 < 10:
            raise ValueError("Pulse Duration too small. Enter a value ≥ 0.01 ms (10 µs).")
        if pd_ms * 1000 > 120_000_000:
            raise ValueError("Pulse Duration too large. Enter a value < 120,000 ms.")
        if pri_ms * 1000 < 10:
            raise ValueError("PRI too low. Enter a value ≥ 0.01 ms (10 µs).")
        if pri_ms * 1000 > 1_000_000:
            raise ValueError("PRI too high. Enter a value ≤ 1,000 ms.")
        if pri_ms < pd_ms:
            raise ValueError("PRI must be ≥ Pulse Duration.")
        if ptd_ms < 1:
            raise ValueError("Pulse Train Duration too low. Must be ≥ 1 ms.")
        if ptd_ms > 600_000:
            raise ValueError("Pulse Train Duration too high. Must be ≤ 600,000 ms (600 s).")

        if isppa_mw < 1:
            raise ValueError("Power too low. Enter a value > 0.001 W/cm² (1 mW/cm²).")
        if self.enforce_limits_checkbox.isChecked():
            if isppa_mw > 30_000:
                raise ValueError(
                    "Power too high. Enter a value < 30 W/cm² (30,000 mW/cm²)."
                )
            ispta_mw = isppa_mw * pd_ms / pri_ms
            if ispta_mw > 720:
                raise ValueError(
                    f"Ispta too high ({ispta_mw:.1f} mW/cm²). "
                    f"Must be < 720 mW/cm². "
                    f"Reduce pulse duration or increase PRI."
                )

        try:
            from neurofus_sdk import _read_nfus_focus_range
            min_depth, max_depth = _read_nfus_focus_range(self.tpo_ser)
            if depth_mm < min_depth:
                raise ValueError(
                    f"Depth {depth_mm} mm is below the minimum steering range ({min_depth} mm)."
                )
            if depth_mm > max_depth:
                raise ValueError(
                    f"Depth {depth_mm} mm exceeds the maximum steering range ({max_depth} mm)."
                )
        except ValueError:
            raise
        except Exception:
            pass  # If device query fails, depth will be validated at runtime

        ramp_mode_map = {
            "None": 0,
            "Linear": 1,
            "Tukey": 2,
        }
        ramp_shape = self.ultra_ramp_shape_combo.currentText()
        ramp_mode = ramp_mode_map.get(ramp_shape, 0)

        ramp_duration_us = 0.0
        if ramp_mode != 0:
            if not self.ultra_ramp_len_input.text():
                raise ValueError("Ramp Length is required when a ramp shape is selected.")
            ramp_duration_us = float(self.ultra_ramp_len_input.text()) * 1000.0
            if ramp_duration_us < 10:
                raise ValueError("Ramp Duration too small. Enter a value ≥ 0.01 ms (10 µs).")
            if ramp_duration_us > 100_000:
                raise ValueError("Ramp Duration too large. Enter a value ≤ 100 ms.")

        params = {
            "ser": self.tpo_ser,
            "connected_port": self.connected_port,
            "firmware": self.connected_firmware,
            "close_connection": False,
            "port": self.connected_port,
            "xdr_index": int(xdr_index),
            "pd": float(self.ultra_pd_input.text()),
            "pri": float(self.ultra_prp_input.text()),
            "ptd": float(self.ultra_ptd_input.text()),
            "depth": float(self.focal_depth_input.text()),
            "isppa": float(self.isppa_input.text()),
            "ramp_mode": ramp_mode,
            "ramp_duration_us": ramp_duration_us,
            "enforce_limits": self.enforce_limits_checkbox.isChecked(),
            "stop_event": self.stimulation_stop_event,
        }

        if self.ultra_enable_ptr_checkbox.isChecked():
            if not self.ultra_num_trains_input.text():
                raise ValueError("Number of Trains is required when repetition is enabled.")
            if not self.ultra_ptrp_input.text():
                raise ValueError("PTRI is required when repetition is enabled.")
            ultra_ptrp_s = float(self.ultra_ptrp_input.text())
            if ultra_ptrp_s * 1000 < ptd_ms:
                raise ValueError(
                    "Pulse Train Repetition Interval must be ≥ Pulse Train Duration."
                )
            params["num_repetitions"] = int(float(self.ultra_num_trains_input.text()))
            params["repetition_interval"] = ultra_ptrp_s

        return params

    def _build_stimulation_request(self):
        stim_mode = self.stim_mode_combo.currentText()
        request = {
            "stim_mode": stim_mode,
            "stimulation_params": self._build_stimulation_params(),
        }

        if stim_mode == "TUS + Mask":
            if self.current_audio is None or self.current_fs is None:
                raise ValueError("Generate masking audio before using TUS + Mask mode.")

            request["audio_data"] = np.array(self.current_audio, copy=True)
            request["sample_rate"] = int(self.current_fs)
            request["tus_start_ms"] = float(self.tus_start_input.text()) if self.tus_start_input.text() else 0.0

        return request

    def set_sonication_running(self, running, window=None):
        if running:
            self.stimulation_stop_event = Event()
            self.active_sonication_window = window
        else:
            self.stimulation_stop_event = None
            self.active_sonication_window = None

        active = running and self.tpo_ser is not None
        self.stop_sonication_btn.setEnabled(active)
        self.stop_sonication_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
            if active else ""
        )


class ConnectWorker(QObject):
    finished = pyqtSignal(object, str, str)  # ser, port, firmware
    failed = pyqtSignal(str)
    device_opened = pyqtSignal()  # fires after nf_open, just before the initialisation wait

    def __init__(self, port):
        super().__init__()
        self.port = port  # None = auto-detect

    def run(self):
        try:
            if self.port:
                ser, ok, firmware = nf_open(self.port)
                if not ok:
                    ser.close()
                    self.failed.emit(f"Device did not respond correctly on {self.port}.")
                    return
                connected_port = self.port
            else:
                # Auto-detect: sweep available ports
                ser, connected_port, firmware = None, None, None
                last_error = None
                for port in serial.tools.list_ports.comports():
                    try:
                        s, ok, fw = nf_open(port.device)
                        if ok:
                            ser, connected_port, firmware = s, port.device, fw
                            break
                        s.close()
                    except Exception as exc:
                        last_error = exc
                if ser is None:
                    msg = f"No valid NeuroFUS device found. Last error: {last_error}" if last_error else "No valid NeuroFUS device found."
                    self.failed.emit(msg)
                    return

            self.device_opened.emit()
            time.sleep(10.0)
            nf_accept_eula(ser)
            self.finished.emit(ser, connected_port, firmware)
        except Exception as exc:
            self.failed.emit(str(exc))


class StimulationWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        try:
            result = run_stimulation_mode(**self.params)
            if result.get("success"):
                self.finished.emit(result)
            else:
                self.failed.emit(result.get("message", "Stimulation failed."))
        except Exception as exc:
            self.failed.emit(str(exc))


class SonicateWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Sonicate Parameters")
        self.resize(600, 400)
        self.worker_thread = None
        self.worker = None

        main_layout = QVBoxLayout(self)
        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout)

        pulse_group = QGroupBox("Ultrasound Parameters")
        pulse_layout = QFormLayout(pulse_group)

        self.port_label = QLabel(self.parent.connected_port or "Auto")
        pulse_layout.addRow("Connected Port:", self.port_label)

        self.mode_label = QLabel(self.parent.stim_mode_combo.currentText())
        pulse_layout.addRow("Stimulation Mode:", self.mode_label)

        self.transducer_label = QLabel(self.parent.transducer_combo.currentText())
        pulse_layout.addRow("Transducer:", self.transducer_label)

        self.pri_label = QLabel(self.parent.ultra_prp_input.text())
        pulse_layout.addRow("PRI (ms):", self.pri_label)

        self.pulse_width_label = QLabel(self.parent.ultra_pd_input.text())
        pulse_layout.addRow("Pulse Duration (ms):", self.pulse_width_label)

        self.train_duration_label = QLabel(self.parent.ultra_ptd_input.text())
        pulse_layout.addRow("Pulse Train Duration (ms):", self.train_duration_label)

        self.depth_label = QLabel(self.parent.focal_depth_input.text())
        pulse_layout.addRow("Focal Depth (mm):", self.depth_label)

        self.isppa_label = QLabel(self.parent.isppa_input.text())
        pulse_layout.addRow("ISPPA (W/cm^2):", self.isppa_label)

        self.ramp_len_label = QLabel(self.parent.ultra_ramp_len_input.text())
        pulse_layout.addRow("Ramp length (ms):", self.ramp_len_label)

        self.ramp_shape_label = QLabel(self.parent.ultra_ramp_shape_combo.currentText())
        pulse_layout.addRow("Ramp shape:", self.ramp_shape_label)

        self.enforce_limits_label = QLabel("On" if self.parent.enforce_limits_checkbox.isChecked() else "Off")
        pulse_layout.addRow("Enforce limits:", self.enforce_limits_label)

        content_layout.addWidget(pulse_group)

        train_group = QGroupBox("Repetition Parameters")
        train_layout = QFormLayout(train_group)

        repetition_enabled = self.parent.ultra_enable_ptr_checkbox.isChecked()
        self.repetition_label = QLabel("Yes" if repetition_enabled else "No")
        train_layout.addRow("Pulse Train Repetition:", self.repetition_label)

        if self.parent.stim_mode_combo.currentText() == "TUS + Mask":
            self.tus_start_label = QLabel(self.parent.tus_start_input.text() or "0")
            train_layout.addRow("TUS Start re. Mask (ms):", self.tus_start_label)

        self.ptri_label = QLabel(self.parent.ultra_ptrp_input.text() if repetition_enabled else "Single run")
        train_layout.addRow("PTRI (s):", self.ptri_label)

        self.num_trains_label = QLabel(self.parent.ultra_num_trains_input.text() if repetition_enabled else "1")
        train_layout.addRow("Number of Pulse Trains:", self.num_trains_label)

        content_layout.addWidget(train_group)

        self.status_label = QLabel("Ready to send parameters to NeuroFUS.")
        main_layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        self.start_button = QPushButton("Start Sonication")
        self.start_button.clicked.connect(self.start_sonication)
        self.cancel_button = QPushButton("Close")
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.cancel_button)
        main_layout.addLayout(buttons_layout)

    def _start_device_countdown(self, seconds=5):
        self._countdown_remaining = seconds
        self.status_label.setText(f"Device initialising... ({self._countdown_remaining}s)")
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._countdown_timer.start(1000)

    def _tick_countdown(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self.status_label.setText("Sending parameters to NeuroFUS...")
        else:
            self.status_label.setText(f"Device initialising... ({self._countdown_remaining}s)")

    def start_sonication(self):
        try:
            self.start_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self._start_device_countdown(5)
            self.parent.set_sonication_running(True, self)
            params = self.parent._build_stimulation_request()
            self.worker_thread = QThread(self)
            self.worker = StimulationWorker(params)
            self.worker.moveToThread(self.worker_thread)

            self.worker_thread.started.connect(self.worker.run)
            self.worker.finished.connect(self._handle_success)
            self.worker.failed.connect(self._handle_failure)
            self.worker.finished.connect(self.worker_thread.quit)
            self.worker.failed.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(self._cleanup_worker)

            self.worker_thread.start()
        except Exception as exc:
            self.parent.set_sonication_running(False)
            self.status_label.setText(str(exc))
            QMessageBox.critical(self, "Sonication Error", str(exc))

    def _handle_success(self, result):
        self.status_label.setText(result["message"])
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sonication complete: {result['message']}")
        self.accept()

    def _handle_failure(self, message):
        self.status_label.setText(message)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        QMessageBox.critical(self, "Sonication Failed", message)

    def _cleanup_worker(self):
        self.parent.set_sonication_running(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
            self.worker_thread = None

    def reject(self):
        if self.worker_thread is not None and self.worker_thread.isRunning():
            QMessageBox.information(self, "Sonication Running", "Wait for the current sonication to finish.")
            return
        super().reject()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BasicMaskGUI()
    window.show()
    sys.exit(app.exec())
