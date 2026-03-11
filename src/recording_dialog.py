"""
Recording dialog — view and play asciicast v2 session recordings.
Uses xterm.js for accurate ANSI rendering during playback.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QLabel, QComboBox, QFileDialog, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage

_ASSETS_DIR = (
    Path(sys._MEIPASS) / "src" / "assets"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "assets"
)


class _SilentPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceId):
        pass


class RecordingDialog(QDialog):
    """View and play asciicast recordings using xterm.js for ANSI rendering."""

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Session Recordings")
        self.setMinimumSize(960, 620)

        self._config = config or {}
        self._recording_dir = Path(
            self._config.get("recording_dir", str(Path.home() / "Documents" / "SSHClientManager-Recordings"))
            if hasattr(self._config, "get") else
            str(Path.home() / "Documents" / "SSHClientManager-Recordings")
        )

        self._events: list[tuple[float, str]] = []
        self._event_idx: int = 0
        self._playing: bool = False
        self._speed: float = 1.0
        self._start_wall: float = 0.0
        self._start_rec: float = 0.0
        self._slider_dragging: bool = False
        self._terminal_ready: bool = False
        self._rec_cols: int = 220   # updated from recording header
        self._rec_rows: int = 50

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self._build_ui()
        self._load_recordings_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel — recordings list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Recordings"))
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_recording_selected)
        left_layout.addWidget(self._list)
        left.setMinimumWidth(200)
        splitter.addWidget(left)

        # Right panel — player
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        self._btn_play = QPushButton("▶ Play")
        self._btn_play.setEnabled(False)
        self._btn_stop = QPushButton("⏹ Stop")
        self._btn_stop.setEnabled(False)
        self._btn_restart = QPushButton("↺ Restart")
        self._btn_restart.setEnabled(False)
        self._combo_speed = QComboBox()
        for s in ["0.5x", "1x", "2x", "4x", "8x"]:
            self._combo_speed.addItem(s)
        self._combo_speed.setCurrentText("1x")
        self._combo_speed.currentTextChanged.connect(self._on_speed_changed)
        self._time_label = QLabel("0:00 / 0:00")

        toolbar.addWidget(self._btn_play)
        toolbar.addWidget(self._btn_stop)
        toolbar.addWidget(self._btn_restart)
        toolbar.addWidget(QLabel("Speed:"))
        toolbar.addWidget(self._combo_speed)
        toolbar.addStretch()
        toolbar.addWidget(self._time_label)
        right_layout.addLayout(toolbar)

        # xterm.js terminal view
        self._view = QWebEngineView()
        page = _SilentPage(self._view)
        self._view.setPage(page)
        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        player_html = _ASSETS_DIR / "player.html"
        self._view.load(QUrl(f"file:///{player_html.as_posix()}"))
        self._view.loadFinished.connect(self._on_terminal_ready)
        right_layout.addWidget(self._view)

        # Progress slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        right_layout.addWidget(self._slider)

        splitter.addWidget(right)
        splitter.setSizes([220, 740])
        outer.addWidget(splitter)

        # Bottom buttons
        bottom = QHBoxLayout()
        self._btn_open = QPushButton("Open .cast File…")
        self._btn_close = QPushButton("Close")
        bottom.addWidget(self._btn_open)
        bottom.addStretch()
        bottom.addWidget(self._btn_close)
        outer.addLayout(bottom)

        self._btn_play.clicked.connect(self._on_play_pause)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_restart.clicked.connect(self._on_restart)
        self._btn_open.clicked.connect(self._on_open_file)
        self._btn_close.clicked.connect(self.accept)

    def _on_terminal_ready(self, ok: bool):
        self._terminal_ready = ok
        if ok:
            self._view.page().runJavaScript(
                f"termSetSize({self._rec_cols}, {self._rec_rows})"
            )

    # ------------------------------------------------------------------
    # List / file loading
    # ------------------------------------------------------------------

    def _load_recordings_list(self):
        self._list.clear()
        if not self._recording_dir.exists():
            return
        cast_files = sorted(
            self._recording_dir.glob("*.cast"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in cast_files:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            item = QListWidgetItem(f"{f.name}\n{mtime}")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self._list.addItem(item)

    def _on_recording_selected(self, current: QListWidgetItem, _previous):
        if current is None:
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        self._load_cast(path)

    def _load_cast(self, path: str):
        self._stop_playback()
        self._events = []
        self._event_idx = 0
        self._slider.setValue(0)
        self._update_time_label(0.0)

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            self._term_reset()
            self._term_write(f"Error opening file: {e}\r\n")
            return

        if not lines:
            return

        # Parse header (line 0): extract recorded cols/rows
        try:
            header = json.loads(lines[0])
            self._rec_cols = int(header.get("width", 220))
            self._rec_rows = int(header.get("height", 50))
        except (json.JSONDecodeError, IndexError, ValueError):
            self._rec_cols = 220
            self._rec_rows = 50

        # Reset terminal then apply recorded dimensions
        self._term_reset()

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if len(event) >= 3 and event[1] == "o":
                    self._events.append((float(event[0]), str(event[2])))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        self._btn_play.setEnabled(bool(self._events))
        self._btn_stop.setEnabled(False)
        self._btn_restart.setEnabled(bool(self._events))

    # ------------------------------------------------------------------
    # xterm.js helpers
    # ------------------------------------------------------------------

    def _term_write(self, text: str):
        if not self._terminal_ready:
            return
        js = f"termWrite({json.dumps(text)})"
        self._view.page().runJavaScript(js)

    def _term_reset(self):
        if not self._terminal_ready:
            return
        self._view.page().runJavaScript(
            f"termSetSize({self._rec_cols}, {self._rec_rows}); termReset();"
        )

    def _term_write_batch(self, texts: list[str]):
        """Write many strings at once to avoid per-event JS round-trips on seek."""
        if not self._terminal_ready or not texts:
            return
        js = f"termWriteBatch({json.dumps(texts)})"
        self._view.page().runJavaScript(js)

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def _on_play_pause(self):
        if self._playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        if not self._events:
            return
        if self._event_idx >= len(self._events):
            self._event_idx = 0
            self._term_reset()

        self._playing = True
        self._start_wall = time.monotonic()
        self._start_rec = self._events[self._event_idx][0] if self._event_idx > 0 else 0.0
        self._btn_play.setText("⏸ Pause")
        self._btn_stop.setEnabled(True)
        self._timer.start()

    def _pause_playback(self):
        self._timer.stop()
        self._playing = False
        self._btn_play.setText("▶ Play")

    def _stop_playback(self):
        self._timer.stop()
        self._playing = False
        self._event_idx = 0
        self._btn_play.setText("▶ Play")
        self._btn_stop.setEnabled(False)

    def _on_stop(self):
        self._stop_playback()
        self._term_reset()
        self._slider.setValue(0)
        self._update_time_label(0.0)

    def _on_restart(self):
        self._stop_playback()
        self._term_reset()
        self._slider.setValue(0)
        self._start_playback()

    def _on_speed_changed(self, text: str):
        was_playing = self._playing
        if was_playing:
            elapsed_wall = time.monotonic() - self._start_wall
            self._start_rec = self._start_rec + elapsed_wall * self._speed
            self._timer.stop()

        self._speed = float(text.rstrip("x"))

        if was_playing:
            self._start_wall = time.monotonic()
            self._timer.start()

    def _tick(self):
        elapsed_wall = time.monotonic() - self._start_wall
        target_rec = self._start_rec + elapsed_wall * self._speed

        batch: list[str] = []
        while self._event_idx < len(self._events):
            t, text = self._events[self._event_idx]
            if t > target_rec:
                break
            batch.append(text)
            self._event_idx += 1

        if batch:
            self._term_write_batch(batch)

        total = self._events[-1][0] if self._events else 1.0
        if not self._slider_dragging:
            self._slider.setValue(int(min(target_rec, total) / total * 1000))
        self._update_time_label(min(target_rec, total))

        if self._event_idx >= len(self._events):
            self._timer.stop()
            self._playing = False
            self._btn_play.setText("▶ Play")
            self._btn_stop.setEnabled(False)

    # ------------------------------------------------------------------
    # Progress slider (seek)
    # ------------------------------------------------------------------

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._slider_dragging = False
        if not self._events:
            return
        total = self._events[-1][0]
        target = self._slider.value() / 1000.0 * total
        self._seek_to(target)

    def _seek_to(self, target_rec: float):
        """Reset terminal and replay all events up to target_rec at once."""
        self._term_reset()
        self._event_idx = 0

        batch: list[str] = []
        for i, (t, text) in enumerate(self._events):
            if t <= target_rec:
                batch.append(text)
                self._event_idx = i + 1
            else:
                break

        self._term_write_batch(batch)
        self._update_time_label(target_rec)

        if self._playing:
            self._start_rec = target_rec
            self._start_wall = time.monotonic()

    # ------------------------------------------------------------------

    def _update_time_label(self, current: float):
        total = self._events[-1][0] if self._events else 0.0

        def fmt(s: float) -> str:
            s = int(s)
            return f"{s // 60}:{s % 60:02d}"

        self._time_label.setText(f"{fmt(current)} / {fmt(total)}")

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Recording", str(self._recording_dir), "Asciicast Files (*.cast);;All Files (*)"
        )
        if path:
            self._load_cast(path)
