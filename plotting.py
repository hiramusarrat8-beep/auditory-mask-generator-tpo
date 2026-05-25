# amg_app/plotting.py
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton


def _max_pool_for_plot(values, target_points):
    if values is None:
        return None
    if target_points <= 0 or len(values) <= target_points:
        return values

    edges = np.linspace(0, len(values), target_points + 1, dtype=int)
    pooled = np.empty(target_points, dtype=float)
    for i in range(target_points):
        start = edges[i]
        end = max(edges[i + 1], start + 1)
        pooled[i] = np.max(values[start:end])
    return pooled


def _preview_signal(audio):
    if getattr(audio, "ndim", 1) == 1:
        return audio
    return np.mean(audio, axis=1)


class PlotPopupDialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 700)

        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        if parent is not None:
            parent_geom = parent.geometry()
            dialog_geom = self.frameGeometry()
            dialog_geom.moveCenter(parent_geom.center())
            self.move(dialog_geom.topLeft())

    def render_time_plot(self, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf, tus_pulses_ms=None):
        ax = self.figure.add_subplot(111)
        update_time_plot(ax, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf, tus_pulses_ms=tus_pulses_ms)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def render_right_plot(self, current_audio, current_fs, show_spectrogram, show_fft, prf):
        update_right_plot(self.figure, current_audio, current_fs, show_spectrogram, show_fft, prf)
        self.figure.tight_layout()
        self.canvas.draw_idle()


def open_time_plot_popup(parent, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf=1000.0, tus_pulses_ms=None):
    dialog = PlotPopupDialog(parent, "Time Plot")
    dialog.render_time_plot(current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf, tus_pulses_ms=tus_pulses_ms)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def open_right_plot_popup(parent, current_audio, current_fs, show_spectrogram, show_fft, prf=None):
    dialog = PlotPopupDialog(parent, "Spectral Plot")
    dialog.render_right_plot(current_audio, current_fs, show_spectrogram, show_fft, prf)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog

def update_time_plot(ax, current_time, current_audio, current_gate, current_bg_audio, zoom_view, ramp_len_text, current_fs, prf=1000.0, tus_pulses_ms=None):
    if zoom_view:
        if prf > 0:
            zoom_ms = 3 * (1000.0 / float(prf))
        else:
            zoom_ms = 10
        title = f"PRF Envelope Zoom (First 3 PRIs) – {zoom_ms:.3f} ms – Ramp = {float(ramp_len_text) / 1000:.6f} s" if ramp_len_text else f"PRF Envelope Zoom (First 3 PRIs) – {zoom_ms:.3f} ms"
    else:
        zoom_ms = len(current_audio) / current_fs * 1000
        title = f"Full Burst View – Ramp = {float(ramp_len_text) / 1000:.6f} s" if ramp_len_text else "Full Burst View"

    zoom_samples = int(zoom_ms * current_fs / 1000)
    zoom_samples = min(zoom_samples, len(current_audio))

    t_zoom = current_time[:zoom_samples] * 1000
    wave_zoom = _preview_signal(current_audio[:zoom_samples])  # Plot stereo preview as mono

    # Upsample plot resolution for smoother display on same x-span
    if zoom_samples > 2:
        upsample_factor = 10
        interp_points = min(int(zoom_samples * upsample_factor), 20000)
        t_interp = np.linspace(t_zoom[0], t_zoom[-1], interp_points)
        gate_source = current_gate[:zoom_samples] if current_gate is not None else None
        bg_source = current_bg_audio[:zoom_samples] if current_bg_audio is not None else None

        wave_zoom = np.interp(t_interp, t_zoom, wave_zoom)
        if gate_source is not None:
            if zoom_view:
                gate_zoom = np.interp(t_interp, t_zoom, gate_source)
            else:
                gate_zoom = _max_pool_for_plot(gate_source, interp_points)
        if bg_source is not None:
            bg_zoom = np.interp(t_interp, t_zoom, bg_source)

        t_zoom = t_interp
    else:
        if current_gate is not None:
            gate_zoom = current_gate[:zoom_samples]
        if current_bg_audio is not None:
            bg_zoom = current_bg_audio[:zoom_samples]

    # UPDATED: Always use single overlaid plot (no separate subplots)
    ax.clear()
    # Only draw the blue waveform line when there is a pulse/gate (Matching Only or Combined),
    # or when there is no background at all. In Background Only mode current_gate is None and
    # current_audio == current_bg_audio, so drawing both lines would duplicate the same signal.
    if current_gate is not None or current_bg_audio is None:
        ax.plot(t_zoom, wave_zoom, color='C0', lw=1.2, label='Waveform + noise')
    if current_gate is not None:
        ax.plot(t_zoom, gate_zoom * 0.5, color='C3', lw=2.5, alpha=0.8, label='Envelope (gate)')
    if current_bg_audio is not None:
        ax.plot(t_zoom, bg_zoom, color='C2', lw=1.2, alpha=0.7, label='Background')
    ax.set_title(title, fontsize=8)  # Smaller font
    ax.set_xlabel("Time (ms)", fontsize=6)
    ax.set_ylabel("Amplitude", fontsize=6)
    ax.set_ylim(-1.1, 1.1)
    ax.set_xlim(0, zoom_ms)
    ax.grid(True, alpha=0.3)

    if tus_pulses_ms:
        # Draw TUS pulses as a narrow bar strip at the bottom of the plot.
        # broken_barh uses data y-coords; axis goes -1.1 to 1.1, bar occupies bottom ~6%.
        bar_bottom = -1.1
        bar_height = 0.13  # ~6% of the 2.2-unit y range
        ax.broken_barh(tus_pulses_ms, (bar_bottom, bar_height),
                       facecolors='steelblue', alpha=0.75, label='TUS active')
        # Label at the left edge of the first pulse that falls in view
        first_visible = next(((s, w) for s, w in tus_pulses_ms if s + w > 0 and s < zoom_ms), None)
        if first_visible is not None:
            label_x = max(first_visible[0], 0)
            ax.text(label_x, bar_bottom + bar_height + 0.01, 'TUS',
                    fontsize=5, color='steelblue', va='bottom', ha='left', clip_on=True)

    ax.legend(loc='upper right', fontsize=6)  # Smaller legend
    ax.tick_params(labelsize=6)  # Smaller tick labels
    ax.text(0.01, 0.02, "Visual display only — waveform may appear aliased at high carrier frequencies",
            transform=ax.transAxes, fontsize=10, color='gray', alpha=0.7, va='bottom')

def update_right_plot(fig, current_audio, current_fs, show_spectrogram, show_fft, prf=None):
    signal = _preview_signal(current_audio)
    fs = current_fs

    fig.clear()
    if show_spectrogram:
        ax = fig.add_subplot(111)
        ax.specgram(signal, Fs=fs, cmap='viridis', NFFT=1024, noverlap=512)
        ax.set_title("Spectrogram Preview", fontsize=8)
        ax.set_xlabel("Time (s)", fontsize=6)
        ax.set_ylabel("Frequency (Hz)", fontsize=6)
        ax.tick_params(labelsize=6)
    elif show_fft:
        n = len(signal)
        fft = np.fft.fft(signal)
        freqs = np.fft.fftfreq(n, 1/fs)
        magnitude = np.abs(fft[:n//2]) / (n / 2)
        magnitude_db = 20 * np.log10(magnitude + 1e-10)

        harmonic_xlim = prf * 9 if prf else 5000

        min_freq = freqs[1] if len(freqs) > 1 else 1.0  # avoid log(0)

        ax1 = fig.add_subplot(211)
        ax1.plot(freqs[:n//2], magnitude_db)
        ax1.set_title(f"Spectral Preview — 0 to {harmonic_xlim:.0f} Hz", fontsize=7)
        ax1.set_xlabel("Frequency (Hz)", fontsize=6)
        ax1.set_ylabel("Magnitude (dBFS)", fontsize=6)
        ax1.set_xscale("log")
        ax1.set_xlim(min_freq, harmonic_xlim)
        ax1.set_ylim(-80, 0)
        ax1.grid(True, which="both")
        ax1.tick_params(labelsize=6)

        ax2 = fig.add_subplot(212)
        ax2.plot(freqs[:n//2], magnitude_db)
        ax2.set_title("Spectral Preview — 0 to 16 kHz", fontsize=7)
        ax2.set_xlabel("Frequency (Hz)", fontsize=6)
        ax2.set_ylabel("Magnitude (dBFS)", fontsize=6)
        ax2.set_xscale("log")
        ax2.set_xlim(min_freq, 16000)
        ax2.set_ylim(-80, 0)
        ax2.grid(True, which="both")
        ax2.tick_params(labelsize=6)


# ── Sonication timeline ────────────────────────────────────────────────────

_TIMELINE_EVENT_STYLES = [
    ("Mask started",                 "#4CAF50", "Mask\nstarted"),
    ("TUS START sent",               "#FF9800", "START\nsent"),
    ("TPO acknowledged sonication",  "#2196F3", "TPO\nack"),
    ("Expected PTD end",             "#27AE60", "PTD\nend"),
    ("Mask stopped",                 "#1565C0", "Mask\nstopped"),
    ("ABORT sent",                   "#E53935", "ABORT\nsent"),
    ("TPO acknowledged abort",       "#B71C1C", "Abort\nack"),
]


def _parse_execution_log(entries: list) -> list:
    """
    Parse execution_log strings into (elapsed_s, label, colour) tuples.
    Input format: "+0.500 s  TUS START sent"
    Returns list sorted by elapsed_s ascending.
    """
    parsed = []
    for entry in entries:
        try:
            elapsed_s = float(entry.split("s")[0].replace("+", "").strip())
        except (ValueError, IndexError):
            continue
        for key, colour, label in _TIMELINE_EVENT_STYLES:
            if key in entry:
                parsed.append((elapsed_s, label, colour))
                break
    parsed.sort(key=lambda x: x[0])
    return parsed


def draw_sonication_timeline(fig, execution_log: list) -> None:
    """
    Draw the TUS+Mask execution timeline onto a matplotlib Figure.
    Called by SonicationTimelineDialog. Clears the figure before drawing.
    """
    import matplotlib.colors as mcolors

    fig.clear()
    fig.patch.set_facecolor("#1e1e1e")
    ax = fig.add_subplot(111)
    ax.set_facecolor("#1e1e1e")

    events = _parse_execution_log(execution_log)

    if not events:
        ax.text(0.5, 0.5, "No timeline data available",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color="gray")
        ax.axis("off")
        return

    times   = [e[0] for e in events]
    total_s = max(times) if times else 1.0
    pad     = max(total_s * 0.10, 0.05)

    ax.set_xlim(-pad, total_s + pad)
    ax.set_ylim(-0.75, 0.75)

    # Spine line
    ax.hlines(0, -pad, total_s + pad,
              colors="#555555", linewidths=1.5, zorder=1)

    # Coloured spans between consecutive events
    for i in range(len(events) - 1):
        t0, _, c = events[i]
        t1       = events[i + 1][0]
        rgb      = mcolors.to_rgba(c, alpha=0.10)
        ax.axvspan(t0, t1, ymin=0.40, ymax=0.60, color=rgb, zorder=1)

    # Event markers
    for i, (t, label, colour) in enumerate(events):
        above  = (i % 2 == 0)
        y_text = 0.38 if above else -0.38
        va     = "bottom" if above else "top"

        # Vertical tick
        ax.vlines(t, -0.20, 0.20,
                  colors=colour, linewidths=1.2, zorder=2)

        # Dot on spine
        ax.plot(t, 0.0, "o",
                color=colour, markersize=9, zorder=3,
                markeredgecolor="white", markeredgewidth=0.8)

        # Elapsed time stamp close to spine
        ax.text(t, 0.26 if above else -0.26,
                f"+{t:.3f}s",
                ha="center",
                va="bottom" if above else "top",
                fontsize=7.5, color=colour, fontweight="bold")

        # Labelled badge
        ax.text(t, y_text, label,
                ha="center", va=va,
                fontsize=8, color="white",
                multialignment="center",
                bbox=dict(boxstyle="round,pad=0.28",
                          facecolor=colour,
                          edgecolor="none",
                          alpha=0.88))

    # Axes styling
    ax.set_xlabel("Elapsed time (s)", color="#aaaaaa", fontsize=9)
    ax.tick_params(axis="x", colors="#aaaaaa", labelsize=8)
    ax.tick_params(axis="y", left=False, labelleft=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color("#444444")
    ax.set_title("TUS + Mask execution timeline",
                 color="white", fontsize=10, pad=8)
    fig.tight_layout(pad=0.9)


class SonicationTimelineDialog(QDialog):
    """
    Non-modal popup that draws the TUS+Mask execution timeline.
    Opened via open_sonication_timeline_popup() only.
    All drawing is delegated to draw_sonication_timeline().
    """

    def __init__(self, parent, execution_log: list):
        super().__init__(parent)
        self.setWindowTitle("Sonication Timeline")
        self.setModal(False)
        self.resize(860, 300)

        # Position next to parent (offset right)
        if parent is not None:
            pg = parent.geometry()
            self.move(pg.x() + pg.width() + 10, pg.y())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._fig    = Figure(figsize=(9, 2.4), dpi=100)
        self._canvas = FigureCanvas(self._fig)
        layout.addWidget(self._canvas)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(26)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        draw_sonication_timeline(self._fig, execution_log)
        self._canvas.draw_idle()


def open_sonication_timeline_popup(parent, execution_log: list):
    """
    Create, show, and return a SonicationTimelineDialog.
    Call pattern mirrors open_time_plot_popup / open_right_plot_popup.
    """
    dialog = SonicationTimelineDialog(parent, execution_log)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
