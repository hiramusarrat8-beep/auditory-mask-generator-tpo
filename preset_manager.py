import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMenu, QMessageBox


class PresetManager:
    """Owns preset save/load behavior for the main GUI."""

    def __init__(self, gui):
        self.gui = gui
        self.default_full_state = None
        self.default_audio_state = None
        self.default_ultrasound_state = None

    def show_menu(self, button):
        menu = QMenu(self.gui)
        save_action = menu.addAction("Save Preset")
        load_action = menu.addAction("Load Preset")

        selected_action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if selected_action == save_action:
            self.save_preset()
        elif selected_action == load_action:
            self.load_preset()

    def show_reset_menu(self, button):
        menu = QMenu(self.gui)
        reset_audio_action = menu.addAction("Reset Audio Settings")
        reset_ultrasound_action = menu.addAction("Reset Ultrasound Settings")
        reset_all_action = menu.addAction("Reset Everything")

        selected_action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if selected_action == reset_audio_action:
            self.reset_audio_settings()
        elif selected_action == reset_ultrasound_action:
            self.reset_ultrasound_settings()
        elif selected_action == reset_all_action:
            self.reset_all_settings()

    def _widget_names(self):
        return {
            "line_edits": [
                "ptd_input", "prp_input", "prf_input", "pd_input", "carrier_input", "ramp_len_input",
                "snr_input", "ptrp_input", "ptrf_input", "ptrd_input", "num_trains_input",
                "narrowband_center_input", "narrowband_bandwidth_input",
                "bg_time_input", "hybrid_prf_input", "hybrid_harmonics_input", "hybrid_bandwidth_input",
                "hybrid_density_input", "hybrid_tone_duration_input", "mondrian_density_input",
                "mondrian_tone_duration_input", "mondrian_pf_min_input", "mondrian_pf_max_input",
                "mondrian_prf_min_input", "mondrian_prf_max_input", "mondrian_duty_cycle_input",
                "pulse_start_input", "tus_start_input", "focal_depth_input",
                "isppa_input", "ultra_ptd_input", "ultra_prp_input", "ultra_prf_input", "ultra_pd_input",
                "ultra_ramp_len_input", "ultra_ptrp_input", "ultra_ptrf_input", "ultra_ptrd_input",
                "ultra_num_trains_input",
            ],
            "combos": [
                "ramp_shape_combo", "bg_type_combo", "bg_ramp_shape", "stim_mode_combo",
                "ultra_ramp_shape_combo", "playback_mode_combo", "transducer_combo", "colored_noise_combo",
            ],
            "checkboxes": [
                "enable_carrier_checkbox", "snr_checkbox", "enable_ptr_checkbox", "enable_dual_checkbox",
                "enforce_limits_checkbox", "ultra_enable_ptr_checkbox", "show_fft_checkbox",
                "show_spectrogram_checkbox",
            ],
            "sliders": [
                "matching_volume_slider", "bg_volume_slider", "pulse_volume_slider", "pan_slider",
                "hybrid_prf_weight_slider", "hybrid_mondrian_weight_slider", "hybrid_broadband_weight_slider",
            ],
            "spinboxes": ["bg_ramp_length"],
            "radio_buttons": ["hybrid_auto_radio", "hybrid_manual_radio"],
        }

    def _section_widget_names(self):
        return {
            "audio": {
                "line_edits": [
                    "ptd_input", "prp_input", "prf_input", "pd_input", "carrier_input", "ramp_len_input",
                    "snr_input", "ptrp_input", "ptrf_input", "ptrd_input", "num_trains_input",
                    "narrowband_center_input", "narrowband_bandwidth_input", "bg_time_input",
                    "hybrid_prf_input", "hybrid_harmonics_input", "hybrid_bandwidth_input",
                    "hybrid_density_input", "hybrid_tone_duration_input", "mondrian_density_input",
                    "mondrian_tone_duration_input", "mondrian_pf_min_input", "mondrian_pf_max_input",
                    "mondrian_prf_min_input", "mondrian_prf_max_input", "mondrian_duty_cycle_input",
                    "pulse_start_input", "tus_start_input",
                ],
                "combos": [
                    "ramp_shape_combo", "bg_type_combo", "bg_ramp_shape", "stim_mode_combo",
                    "playback_mode_combo", "colored_noise_combo",
                ],
                "checkboxes": [
                    "enable_carrier_checkbox", "snr_checkbox", "enable_ptr_checkbox", "enable_dual_checkbox",
                    "show_fft_checkbox", "show_spectrogram_checkbox",
                ],
                "sliders": [
                    "matching_volume_slider", "bg_volume_slider", "pulse_volume_slider", "pan_slider",
                    "hybrid_prf_weight_slider", "hybrid_mondrian_weight_slider", "hybrid_broadband_weight_slider",
                ],
                "spinboxes": ["bg_ramp_length"],
                "radio_buttons": ["hybrid_auto_radio", "hybrid_manual_radio"],
            },
            "ultrasound": {
                "line_edits": [
                    "focal_depth_input", "isppa_input", "ultra_ptd_input", "ultra_prp_input",
                    "ultra_prf_input", "ultra_pd_input", "ultra_ramp_len_input", "ultra_ptrp_input",
                    "ultra_ptrf_input", "ultra_ptrd_input", "ultra_num_trains_input",
                ],
                "combos": ["transducer_combo", "ultra_ramp_shape_combo"],
                "checkboxes": ["enforce_limits_checkbox", "ultra_enable_ptr_checkbox"],
                "sliders": [],
                "spinboxes": [],
                "radio_buttons": [],
            },
        }

    def collect_preset_data(self):
        widget_names = self._widget_names()
        return {
            "preset_version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "ui_state": {
                "line_edits": {
                    name: getattr(self.gui, name).text()
                    for name in widget_names["line_edits"]
                },
                "combos": {
                    name: getattr(self.gui, name).currentText()
                    for name in widget_names["combos"]
                },
                "checkboxes": {
                    name: getattr(self.gui, name).isChecked()
                    for name in widget_names["checkboxes"]
                },
                "sliders": {
                    name: getattr(self.gui, name).value()
                    for name in widget_names["sliders"]
                },
                "spinboxes": {
                    name: getattr(self.gui, name).value()
                    for name in widget_names["spinboxes"]
                },
                "radio_buttons": {
                    name: getattr(self.gui, name).isChecked()
                    for name in widget_names["radio_buttons"]
                },
            },
        }

    def _collect_subset_state(self, section_name):
        widget_names = self._section_widget_names()[section_name]
        return {
            "preset_version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "ui_state": {
                "line_edits": {
                    name: getattr(self.gui, name).text()
                    for name in widget_names["line_edits"]
                },
                "combos": {
                    name: getattr(self.gui, name).currentText()
                    for name in widget_names["combos"]
                },
                "checkboxes": {
                    name: getattr(self.gui, name).isChecked()
                    for name in widget_names["checkboxes"]
                },
                "sliders": {
                    name: getattr(self.gui, name).value()
                    for name in widget_names["sliders"]
                },
                "spinboxes": {
                    name: getattr(self.gui, name).value()
                    for name in widget_names["spinboxes"]
                },
                "radio_buttons": {
                    name: getattr(self.gui, name).isChecked()
                    for name in widget_names["radio_buttons"]
                },
            },
        }

    def capture_default_states(self):
        self.default_full_state = self.collect_preset_data()
        self.default_audio_state = self._collect_subset_state("audio")
        self.default_ultrasound_state = self._collect_subset_state("ultrasound")

    def _save_json(self, filepath, data):
        target_path = Path(filepath)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with target_path.open("w", encoding="utf-8") as output_file:
            json.dump(data, output_file, indent=2)
            output_file.write("\n")

        return target_path

    def _load_json(self, filepath):
        target_path = Path(filepath)

        with target_path.open("r", encoding="utf-8") as input_file:
            loaded = json.load(input_file)

        if not isinstance(loaded, dict):
            raise ValueError("Expected JSON object at the top level.")

        return loaded

    def _set_combo_text(self, combo, value):
        if value is None:
            return
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def apply_preset_data(self, preset_data):
        ui_state = preset_data.get("ui_state")
        if not isinstance(ui_state, dict):
            raise ValueError("Preset file is missing a valid 'ui_state' section.")

        combo_values = ui_state.get("combos", {})
        for combo_name in [
            "bg_type_combo",
            "ramp_shape_combo",
            "bg_ramp_shape",
            "stim_mode_combo",
            "ultra_ramp_shape_combo",
            "transducer_combo",
            "playback_mode_combo",
            "colored_noise_combo",
        ]:
            widget = getattr(self.gui, combo_name, None)
            if widget is not None:
                self._set_combo_text(widget, combo_values.get(combo_name))

        for name, checked in ui_state.get("radio_buttons", {}).items():
            widget = getattr(self.gui, name, None)
            if widget is not None:
                widget.setChecked(bool(checked))

        for name, checked in ui_state.get("checkboxes", {}).items():
            widget = getattr(self.gui, name, None)
            if widget is not None:
                widget.setChecked(bool(checked))

        for name, text in ui_state.get("line_edits", {}).items():
            widget = getattr(self.gui, name, None)
            if widget is not None:
                widget.setText("" if text is None else str(text))

        for name, value in ui_state.get("sliders", {}).items():
            widget = getattr(self.gui, name, None)
            if widget is not None:
                widget.setValue(int(value))

        for name, value in ui_state.get("spinboxes", {}).items():
            widget = getattr(self.gui, name, None)
            if widget is not None:
                widget.setValue(float(value))

        self.gui.update_background_ramp_visibility()
        self.gui.update_derived()
        self.gui.validate_generate_button()
        self.gui.on_settings_changed()

    def _confirm_reset(self, title, text):
        result = QMessageBox.question(
            self.gui,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def reset_audio_settings(self):
        if self.default_audio_state is None:
            return
        if not self._confirm_reset("Reset Audio Settings", "Reset audio settings to their default values?"):
            return
        self.apply_preset_data(self.default_audio_state)
        self.gui.clear_generated_output()

    def reset_ultrasound_settings(self):
        if self.default_ultrasound_state is None:
            return
        if not self._confirm_reset("Reset Ultrasound Settings", "Reset ultrasound settings to their default values?"):
            return
        self.apply_preset_data(self.default_ultrasound_state)

    def reset_all_settings(self):
        if self.default_full_state is None:
            return
        if not self._confirm_reset("Reset Everything", "Reset all settings to their default values?"):
            return
        self.apply_preset_data(self.default_full_state)
        self.gui.clear_generated_output()

    def save_preset(self):
        default_path = Path.cwd() / "presets" / "preset.json"
        filepath, _ = QFileDialog.getSaveFileName(
            self.gui,
            "Save preset",
            str(default_path),
            "JSON files (*.json)",
        )
        if not filepath:
            return

        target_path = Path(filepath)
        if target_path.suffix.lower() != ".json":
            target_path = target_path.with_suffix(".json")

        try:
            self._save_json(target_path, self.collect_preset_data())
            QMessageBox.information(self.gui, "Preset saved", f"Preset saved to:\n{target_path}")
        except Exception as exc:
            QMessageBox.critical(self.gui, "Preset save error", str(exc))

    def load_preset(self):
        default_dir = Path.cwd() / "presets"
        filepath, _ = QFileDialog.getOpenFileName(
            self.gui,
            "Load preset",
            str(default_dir),
            "JSON files (*.json)",
        )
        if not filepath:
            return

        try:
            preset_data = self._load_json(filepath)
            self.apply_preset_data(preset_data)
            QMessageBox.information(self.gui, "Preset loaded", f"Preset loaded from:\n{filepath}")
        except Exception as exc:
            QMessageBox.critical(self.gui, "Preset load error", str(exc))
