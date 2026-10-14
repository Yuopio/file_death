#!/usr/bin/env python3
"""A tiny desktop companion using the PNG sprites in this folder."""

import argparse
import ctypes
import ctypes.util
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter, QPen, QPixmap, QPolygon, QTransform
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget


ASSET_DIR = Path(__file__).resolve().parent
IDLE_FRAME = "stay1.png"
IDLE_VARIANT_FRAME = "stay_walk.png"
PICKUP_FRAME = "pick_ma.png"
TICK_MS = 40
FRAME_SECONDS = 0.24
MOD_PROG_LOOP_FRAME_SECONDS = FRAME_SECONDS * 4
SPRITE_SCALE = 3
WALK_SPEED = 55.0 * SPRITE_SCALE
PICKUP_HEAD_ANCHOR = (42, 22)
PICKUP_MAX_SWING_DEGREES = 24.0
PICKUP_FULL_SWING_SPEED = 900.0
REST_MIN_SECONDS = 8.0
REST_MAX_SECONDS = 15.0
IDLE_VARIANT_MIN_INTERVAL = 25.0
IDLE_VARIANT_MAX_INTERVAL = 50.0
IDLE_VARIANT_DURATION = 0.55
WALK_STEPS = (1, 2, 3, 4)
MIN_WALK_CYCLES = 2
MAX_WALK_CYCLES = 5
MOD_PROG_START_FRAMES = ("mod_prog_1.png", "mod_prog_2.png")
MOD_PROG_LOOP_FRAMES = ("mod_prog_3.png", "mod_prog_4.png")
MOD_PROG_EXIT_FRAMES = ("mod_prog_2.png", "mod_prog_1.png")
MOD_KSP_START_FRAME = "mod_ksp_1.png"
MOD_KSP_LOOP_FRAMES = ("mod_ksp_2.png", "mod_ksp_3.png")
MOD_KSP_ALARM_FRAME = "mod_ksp_alarm.png"
MOD_KSP_FRAME_SECONDS = 1.5
MOD_KSP_FRAME1_DURATION = 5.0
MOD_KSP_ALARM_MIN_SECONDS = 20.0
MOD_KSP_ALARM_MAX_SECONDS = 300.0
MOD_KSP_ALARM_DURATION = 5.0
MOD_KSP_FRAME1_MIN_SECONDS = 20.0
MOD_KSP_FRAME1_MAX_SECONDS = 300.0
FALL_AIR_FRAMES = ("fall1.png", "fall2.png")
FALL3_FRAME = "fall3.png"
FALL3_ALT_FRAME = "fall3_alt.png"
FALL4_ALT_FRAME = "fall4_alt.png"
FALL_FLOOR_FRAME = "fall_floor.png"
FALL_WINDOW_FRAME = "fall_window.png"
FALL_GRAVITY = 2200.0
FALL_MAX_VELOCITY = 1400.0
FALL3_ALT_CHANCE = 0.08
FALL4_ALT_CHANCE = 0.12
FALL_WINDOW_LANDING_OFFSET_RATIO = 1 / 4
FLOOR_STAND_DELAY = 1.2
WINDOW_SUPPORT_CHECK_INTERVAL = 0.25
WIRE_SPAWN_INTERVAL = 60.0
WIRE_TICK_MS = 50
WIRE_STEP_LENGTH = 18.0
WIRE_GROWTH_SPEED = 42.0
WIRE_BRANCH_CHANCE = 0.055
WIRE_MAX_BRANCH_DEPTH = 3
CLICK_SEQUENCE_TIMEOUT_MS = 450
SPEECH_BUBBLE_DURATION_MS = 5000
SPEECH_FONT_PATH = ASSET_DIR / "assets" / "fonts" / "PressStart2P-Regular.ttf"
SPEECH_FONT_ID = -1
SPEECH_FONT_FAMILY = "Press Start 2P"


@dataclass
class WireSegment:
    start: QPointF
    end: QPointF
    starts_at: float
    duration: float
    width: float
    color: tuple[int, int, int]


class WireGrowthOverlay(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.screen_geometry = screen.geometry()
        self.setGeometry(self.screen_geometry)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.segments = []
        now = time.monotonic()
        self.enabled = False
        self.paused_at = None
        self.next_spawn_at = 0.0
        self.active_cluster_started_at = now
        self.timer = QTimer(self)
        self.timer.setInterval(WIRE_TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_screen(self, screen):
        if screen is None or screen == self.screen:
            return

        self.screen = screen
        self.screen_geometry = screen.geometry()
        self.setGeometry(self.screen_geometry)
        self.segments.clear()
        now = time.monotonic()
        if self.enabled:
            self.next_spawn_at = now + WIRE_SPAWN_INTERVAL
        self.active_cluster_started_at = now
        self.update()

    def set_enabled(self, enabled):
        if enabled == self.enabled:
            return

        now = time.monotonic()
        if enabled:
            if self.paused_at is None:
                self.next_spawn_at = now + WIRE_SPAWN_INTERVAL
            else:
                paused_duration = now - self.paused_at
                if self.next_spawn_at > self.paused_at:
                    self.next_spawn_at += paused_duration
                else:
                    self.next_spawn_at = now + WIRE_SPAWN_INTERVAL
                for segment in self.segments:
                    segment.starts_at += paused_duration
                self.paused_at = None
            self.enabled = True
        else:
            self.enabled = False
            self.paused_at = now
            self.update()

    def _grow_strand(self, x, y, heading, steps, depth, delay, width, color):
        angle = heading
        elapsed_on_strand = 0.0
        branch_created = False
        for step_index in range(steps):
            angle += random.uniform(-0.22, 0.22)
            step_length = random.uniform(WIRE_STEP_LENGTH * 0.65, WIRE_STEP_LENGTH * 1.35)
            next_x = x + math.cos(angle) * step_length
            next_y = y + math.sin(angle) * step_length

            if next_x < 0 or next_x >= self.width() or next_y < 0 or next_y >= self.height():
                center_x = self.width() / 2
                center_y = self.height() / 2
                angle = math.atan2(center_y - y, center_x - x) + random.uniform(-0.45, 0.45)
                next_x = x + math.cos(angle) * step_length
                next_y = y + math.sin(angle) * step_length

            next_x = min(max(next_x, 0.0), float(self.width() - 1))
            next_y = min(max(next_y, 0.0), float(self.height() - 1))
            actual_length = math.hypot(next_x - x, next_y - y)
            segment_duration = actual_length / WIRE_GROWTH_SPEED
            segment_delay = delay + elapsed_on_strand
            self.segments.append(
                WireSegment(
                    QPointF(x, y),
                    QPointF(next_x, next_y),
                    self.active_cluster_started_at + segment_delay,
                    segment_duration,
                    width,
                    color,
                )
            )

            elapsed_on_strand += segment_duration
            x, y = next_x, next_y

            if (
                depth > 0
                and not branch_created
                and step_index > 3
                and random.random() < WIRE_BRANCH_CHANCE
            ):
                branch_created = True
                branch_heading = angle + random.choice((-1, 1)) * random.uniform(0.65, 1.25)
                remaining_steps = steps - step_index
                branch_steps = max(12, int(remaining_steps * random.uniform(0.35, 0.65)))
                self._grow_strand(
                    x,
                    y,
                    branch_heading,
                    branch_steps,
                    depth - 1,
                    segment_delay + segment_duration,
                    width * 0.72,
                    color,
                )

    def _spawn_wire(self, now):
        width = self.width()
        height = self.height()
        edge = random.choice(("top", "right", "bottom", "left"))
        if edge == "top":
            x, y = random.uniform(0, width), 0.0
            heading = math.pi / 2
        elif edge == "right":
            x, y = float(width - 1), random.uniform(0, height)
            heading = math.pi
        elif edge == "bottom":
            x, y = random.uniform(0, width), float(height - 1)
            heading = -math.pi / 2
        else:
            x, y = 0.0, random.uniform(0, height)
            heading = 0.0

        heading += random.uniform(-0.5, 0.5)
        palette = ((82, 211, 168), (82, 171, 224), (194, 208, 111))
        color = random.choice(palette)
        main_steps = max(30, int(math.hypot(width, height) / WIRE_STEP_LENGTH * 1.7))
        self.active_cluster_started_at = now
        self._grow_strand(
            x,
            y,
            heading,
            main_steps,
            WIRE_MAX_BRANCH_DEPTH,
            0.0,
            random.uniform(2.1, 3.4),
            color,
        )

    def _tick(self):
        if not self.enabled:
            return

        now = time.monotonic()
        if now >= self.next_spawn_at:
            self._spawn_wire(now)
            self.next_spawn_at = now + WIRE_SPAWN_INTERVAL
        self.update()

    def clear_wires(self):
        self.segments.clear()
        now = time.monotonic()
        self.active_cluster_started_at = now
        self.next_spawn_at = now + WIRE_SPAWN_INTERVAL if self.enabled else 0.0
        self.update()

    def paintEvent(self, _event):
        now = self.paused_at if not self.enabled and self.paused_at is not None else time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for segment in self.segments:
            elapsed = now - segment.starts_at
            if elapsed <= 0:
                continue

            progress = min(elapsed / max(segment.duration, 0.001), 1.0)
            end_x = segment.start.x() + (segment.end.x() - segment.start.x()) * progress
            end_y = segment.start.y() + (segment.end.y() - segment.start.y()) * progress
            visible_end = QPointF(end_x, end_y)
            r, g, b = segment.color

            shadow = QPen(QColor(5, 12, 18, 130), segment.width + 2.2)
            shadow.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(shadow)
            painter.drawLine(segment.start, visible_end)

            core = QPen(QColor(r, g, b, 205), segment.width)
            core.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(core)
            painter.drawLine(segment.start, visible_end)

        painter.end()


class SpeechBubble(QWidget):
    def __init__(self):
        super().__init__(None)
        global SPEECH_FONT_ID, SPEECH_FONT_FAMILY
        if SPEECH_FONT_ID < 0 and SPEECH_FONT_PATH.is_file():
            SPEECH_FONT_ID = QFontDatabase.addApplicationFont(str(SPEECH_FONT_PATH))
            if SPEECH_FONT_ID >= 0:
                families = QFontDatabase.applicationFontFamilies(SPEECH_FONT_ID)
                if families:
                    SPEECH_FONT_FAMILY = families[0]
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.bubble_font = QFont(SPEECH_FONT_FAMILY)
        self.bubble_font.setPixelSize(10)
        self.text_color = QColor(20, 29, 35)
        self.paper_color = QColor(255, 255, 255)
        self.outline_color = QColor(20, 29, 35)
        self.lines = []
        self.body_height = 0
        self.text_left = 20
        self.text_top = 18
        self.line_height = 19
        self.corner_step = 4
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def _wrap_text(self, text, max_width):
        metrics = QFontMetrics(self.bubble_font)
        lines = []
        for paragraph in text.splitlines() or [text]:
            words = paragraph.split()
            current_line = ""
            for word in words:
                candidate = f"{current_line} {word}".strip()
                if current_line and metrics.horizontalAdvance(candidate) > max_width:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = candidate
            lines.append(current_line)
        return lines or [""]

    def _bubble_polygon(self):
        width = self.width()
        height = self.body_height
        step = self.corner_step
        tail_x = round(width * 0.72)
        return QPolygon(
            [
                QPoint(step, 0),
                QPoint(width - step, 0),
                QPoint(width, step),
                QPoint(width, height - step),
                QPoint(width - step, height),
                QPoint(tail_x + 12, height),
                QPoint(tail_x + 12, height + step),
                QPoint(tail_x + 8, height + step),
                QPoint(tail_x + 8, height + step * 2),
                QPoint(tail_x + 4, height + step * 2),
                QPoint(tail_x + 4, height + step * 3),
                QPoint(tail_x, height + step * 3),
                QPoint(tail_x - 4, height + step * 3),
                QPoint(tail_x - 4, height + step * 2),
                QPoint(tail_x - 8, height + step * 2),
                QPoint(tail_x - 8, height + step),
                QPoint(tail_x - 12, height + step),
                QPoint(tail_x - 12, height),
                QPoint(step, height),
                QPoint(0, height - step),
                QPoint(0, step),
            ]
        )

    def show_quote(self, quote, anchor):
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        max_text_width = max(120, min(520, area.width() - 56))
        self.lines = self._wrap_text(quote, max_text_width)
        metrics = QFontMetrics(self.bubble_font)
        text_width = max(metrics.horizontalAdvance(line) for line in self.lines)
        text_height = metrics.height()
        self.line_height = max(text_height + 7, 18)
        self.text_left = 20
        self.text_top = 18
        width = text_width + self.text_left * 2
        self.body_height = self.text_top + len(self.lines) * self.line_height + 14
        height = self.body_height + self.corner_step * 3 + 4
        self.setFixedSize(width, height)

        tail_x = round(width * 0.72)
        tail_x = max(24, min(tail_x, width - 24))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = round(anchor.x() - tail_x)
        y = round(anchor.y() - self.height() - 8)
        x = max(area.left(), min(x, area.right() - self.width() + 1))
        y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
        self.raise_()
        self.hide_timer.start(SPEECH_BUBBLE_DURATION_MS)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        polygon = self._bubble_polygon()
        painter.setPen(
            QPen(
                self.outline_color,
                4,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.SquareCap,
                Qt.PenJoinStyle.MiterJoin,
            )
        )
        painter.setBrush(self.paper_color)
        painter.drawPolygon(polygon)

        painter.setFont(self.bubble_font)
        painter.setPen(self.text_color)
        metrics = painter.fontMetrics()
        baseline = self.text_top + metrics.ascent()
        for line in self.lines:
            painter.drawText(self.text_left, baseline, line)
            baseline += self.line_height
        painter.end()


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("window_class", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


def _find_windows_landing_y(center_x, current_bottom, floor_y, own_window_id):
    user32 = ctypes.windll.user32

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    process_id = os.getpid()
    candidates = []
    ignored_classes = {"Progman", "WorkerW", "Shell_TrayWnd"}
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit_window(handle, _parameter):
        window_process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(window_process_id))
        if window_process_id.value == process_id or not user32.IsWindowVisible(handle):
            return True
        if user32.IsIconic(handle):
            return True

        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, class_name, len(class_name))
        if class_name.value in ignored_classes:
            return True

        rect = Rect()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return True
        if rect.left <= center_x < rect.right and current_bottom <= rect.top < floor_y:
            candidates.append(rect.top)
        return True

    callback = callback_type(visit_window)
    user32.EnumWindows(callback, 0)
    return min(candidates) if candidates else None


def _find_x11_landing_y(center_x, current_bottom, floor_y, own_window_id):
    library_name = ctypes.util.find_library("X11")
    if not library_name or not os.environ.get("DISPLAY"):
        return None

    x11 = ctypes.CDLL(library_name)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    display = x11.XOpenDisplay(None)
    if not display:
        return None

    window_type = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = window_type
    root = x11.XDefaultRootWindow(display)
    root_return = window_type()
    parent_return = window_type()
    children_return = ctypes.POINTER(window_type)()
    child_count = ctypes.c_uint()
    candidates = []

    try:
        x11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            window_type,
            ctypes.POINTER(window_type),
            ctypes.POINTER(window_type),
            ctypes.POINTER(ctypes.POINTER(window_type)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        x11.XQueryTree.restype = ctypes.c_int
        if not x11.XQueryTree(
            display,
            root,
            ctypes.byref(root_return),
            ctypes.byref(parent_return),
            ctypes.byref(children_return),
            ctypes.byref(child_count),
        ):
            return None

        x11.XGetWindowAttributes.argtypes = [
            ctypes.c_void_p,
            window_type,
            ctypes.POINTER(XWindowAttributes),
        ]
        x11.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            window_type,
            window_type,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(window_type),
        ]

        for index in range(child_count.value):
            window_id = children_return[index]
            if window_id == own_window_id:
                continue

            attributes = XWindowAttributes()
            if not x11.XGetWindowAttributes(display, window_id, ctypes.byref(attributes)):
                continue
            if attributes.map_state != 2:
                continue

            root_x = ctypes.c_int()
            root_y = ctypes.c_int()
            child_return = window_type()
            if not x11.XTranslateCoordinates(
                display,
                window_id,
                root,
                0,
                0,
                ctypes.byref(root_x),
                ctypes.byref(root_y),
                ctypes.byref(child_return),
            ):
                continue

            if (
                root_x.value <= center_x < root_x.value + attributes.width
                and current_bottom <= root_y.value < floor_y
            ):
                candidates.append(root_y.value)
    finally:
        if children_return:
            x11.XFree.argtypes = [ctypes.c_void_p]
            x11.XFree(children_return)
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay(display)

    return min(candidates) if candidates else None


def find_window_landing_y(center_x, current_bottom, floor_y, own_window_id):
    """Find the nearest visible application-window top below the sprite."""
    if sys.platform == "win32":
        return _find_windows_landing_y(center_x, current_bottom, floor_y, own_window_id)
    if sys.platform.startswith("linux"):
        return _find_x11_landing_y(center_x, current_bottom, floor_y, own_window_id)
    return None


def build_walk_sequence(side, cycles):
    """Return start frame, repeated 1-4 steps, and the ending start frame."""
    start_frame = f"walk_{side}_s.png"
    one_cycle = [f"walk_{side}_{step}.png" for step in WALK_STEPS]

    sequence = [start_frame]
    for _ in range(cycles):
        sequence.extend(one_cycle)
    sequence.append(start_frame)
    return sequence


def pickup_swing_angle(horizontal_speed):
    """Map horizontal cursor speed to a bounded opposite swing angle."""
    speed_ratio = max(-1.0, min(1.0, horizontal_speed / PICKUP_FULL_SWING_SPEED))
    return speed_ratio * PICKUP_MAX_SWING_DEGREES


def show_walk_sequences():
    """Print the walking pattern used by the animation."""
    for side, direction in (("r", "right"), ("l", "left")):
        start_frame = f"walk_{side}_s.png"
        one_cycle = " -> ".join(f"walk_{side}_{step}.png" for step in WALK_STEPS)
        print(
            f"{direction}: {start_frame} -> ({one_cycle}) x "
            f"{MIN_WALK_CYCLES}-{MAX_WALK_CYCLES} -> {start_frame} -> {IDLE_FRAME}"
        )


class Shimeji(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shimeji")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.frames = self._load_frames()
        self.quotes = self._load_quotes()
        self.frame_width = self.frames[IDLE_FRAME].width()
        self.frame_height = self.frames[IDLE_FRAME].height()
        self.setFixedSize(self.frame_width, self.frame_height)

        self.image = QLabel(self)
        self.image.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.image.setFixedSize(self.frame_width, self.frame_height)
        self._set_frame(IDLE_FRAME)
        self.speech_bubble = SpeechBubble()

        self.state = "idle"
        self.direction = 1
        self.walk_frames = []
        self.walk_frame_index = 0
        self.next_frame_at = 0.0
        self.next_decision_at = time.monotonic() + random.uniform(
            REST_MIN_SECONDS, REST_MAX_SECONDS
        )
        self.next_idle_variant_at = time.monotonic() + random.uniform(
            IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
        )
        self.idle_variant_until = 0.0
        self.last_tick_at = time.monotonic()
        self.position_x = 0.0
        self.position_y = 0.0
        self.paused = False
        self.drag_offset = None
        self.pick_cursor_position = None
        self.pending_pick_position = None
        self.pick_last_move_at = 0.0
        self.pick_angle = 0.0
        self.pick_direction = 1
        self.pick_press_position = None
        self.pick_dragged = False
        self.left_click_count = 0
        self.click_sequence_timer = QTimer(self)
        self.click_sequence_timer.setSingleShot(True)
        self.click_sequence_timer.setInterval(CLICK_SEQUENCE_TIMEOUT_MS)
        self.click_sequence_timer.timeout.connect(self._finish_click_sequence)
        self.fall_frames = []
        self.fall_frame_index = 0
        self.fall_next_frame_at = 0.0
        self.fall_velocity = 0.0
        self.fall_landing_y = 0.0
        self.fall_landing_x = 0
        self.fall_floor_y = 0.0
        self.fall_landing_frame = FALL_FLOOR_FRAME
        self.fall_uses_window_alt = False
        self.fall_window_alt_shown = False
        self.platform_rect = None
        self.stand_up_at = 0.0
        self.stand_up_frames = []
        self.stand_up_frame_index = 0
        self.stand_up_next_frame_at = 0.0
        self.next_window_support_check_at = 0.0
        self.mod_prog_frame_index = 0
        self.mod_prog_next_frame_at = 0.0
        self.mod_prog_exit_index = 0
        self.mod_prog_bottom = 0
        self.mod_prog_center_x = 0
        self.mod_ksp_frame_index = 0
        self.mod_ksp_next_frame_at = 0.0
        self.mod_ksp_alarm_at = 0.0
        self.mod_ksp_alarm_until = 0.0
        self.mod_ksp_frame1_at = 0.0
        self.mod_ksp_center_x = 0.0
        self.mod_ksp_bottom = 0.0

        self._place_at_bottom()
        current_screen = QApplication.screenAt(self.frameGeometry().center())
        self.wire_overlay = WireGrowthOverlay(current_screen or QApplication.primaryScreen())
        self.wire_overlay.show()
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    @staticmethod
    def _load_frames():
        names = [
            IDLE_FRAME,
            IDLE_VARIANT_FRAME,
            PICKUP_FRAME,
            *FALL_AIR_FRAMES,
            FALL3_FRAME,
            FALL3_ALT_FRAME,
            FALL4_ALT_FRAME,
            FALL_FLOOR_FRAME,
            FALL_WINDOW_FRAME,
            *MOD_PROG_START_FRAMES,
            *MOD_PROG_LOOP_FRAMES,
            MOD_KSP_START_FRAME,
            *MOD_KSP_LOOP_FRAMES,
            MOD_KSP_ALARM_FRAME,
        ]
        for side in ("r", "l"):
            names.append(f"walk_{side}_s.png")
            names.extend(f"walk_{side}_{index}.png" for index in range(1, 5))

        frames = {}
        for name in names:
            path = ASSET_DIR / name
            if not path.is_file():
                raise FileNotFoundError(f"Missing sprite: {path}")
            image = QImage(str(path))
            if image.isNull():
                raise ValueError(f"Could not read sprite: {path}")
            pixmap = QPixmap.fromImage(image)
            frames[name] = pixmap.scaled(
                pixmap.width() * SPRITE_SCALE,
                pixmap.height() * SPRITE_SCALE,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        size = (frames[IDLE_FRAME].width(), frames[IDLE_FRAME].height())
        regular_frame_names = [
            IDLE_FRAME,
            IDLE_VARIANT_FRAME,
            PICKUP_FRAME,
            *FALL_AIR_FRAMES,
            FALL3_FRAME,
            FALL3_ALT_FRAME,
            FALL4_ALT_FRAME,
            FALL_FLOOR_FRAME,
            FALL_WINDOW_FRAME,
            *(f"walk_{side}_{suffix}.png" for side in ("r", "l") for suffix in ("s", 1, 2, 3, 4)),
        ]
        if any(
            (frames[name].width(), frames[name].height()) != size
            for name in regular_frame_names
        ):
            raise ValueError("Idle and walking sprites must have matching dimensions.")
        return frames

    @staticmethod
    def _load_quotes():
        path = ASSET_DIR / "words.txt"
        if not path.is_file():
            return ["Hello! I am here."]
        raw_text = path.read_bytes()
        try:
            text = raw_text.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_text.decode("cp1251")
        quotes = [
            line.strip().strip('"')
            for line in text.splitlines()
            if line.strip()
        ]
        return quotes or ["Hello! I am here."]

    def _place_at_bottom(self):
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.position_x = area.x() + (area.width() - self.frame_width) / 2
        self.position_y = area.y() + area.height() - self.frame_height
        self._move_window()

    def _move_window(self):
        center = QPoint(
            round(self.position_x + self.width() / 2),
            round(self.position_y + self.height() / 2),
        )
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            max_x = max(area.left(), area.right() - self.width() + 1)
            max_y = max(area.top(), area.bottom() - self.height() + 1)
            self.position_x = min(max(self.position_x, area.left()), max_x)
            self.position_y = min(max(self.position_y, area.top()), max_y)
        self.move(round(self.position_x), round(self.position_y))
        overlay = getattr(self, "wire_overlay", None)
        if overlay is not None:
            overlay.set_screen(screen)

    def _set_frame(self, name):
        self.setFixedSize(self.frame_width, self.frame_height)
        self.image.setFixedSize(self.frame_width, self.frame_height)
        self.image.setPixmap(self.frames[name])

    def _set_mod_prog_frame(self, name):
        pixmap = self.frames[name]
        frame_width = pixmap.width()
        frame_height = pixmap.height()
        self.setFixedSize(frame_width, frame_height)
        self.image.setFixedSize(frame_width, frame_height)
        self.image.setPixmap(pixmap)
        self.position_x = self.mod_prog_center_x - frame_width / 2
        self.position_y = self.mod_prog_bottom - frame_height
        self._move_window()

    def _start_mod_prog(self):
        if self.state != "idle":
            return
        self.wire_overlay.set_enabled(True)
        self.state = "mod_prog_start"
        self.mod_prog_center_x = self.x() + self.width() / 2
        self.mod_prog_bottom = self.y() + self.height()
        self.mod_prog_frame_index = 0
        self._set_mod_prog_frame(MOD_PROG_START_FRAMES[0])
        self.mod_prog_next_frame_at = time.monotonic() + FRAME_SECONDS

    def _end_mod_prog(self):
        if self.state not in ("mod_prog_start", "mod_prog_loop"):
            return
        self.wire_overlay.set_enabled(False)
        self.state = "mod_prog_exit"
        self.mod_prog_exit_index = 0
        self._set_mod_prog_frame(MOD_PROG_EXIT_FRAMES[0])
        self.mod_prog_next_frame_at = time.monotonic() + FRAME_SECONDS

    def _advance_mod_prog(self, now):
        if now < self.mod_prog_next_frame_at:
            return

        if self.state == "mod_prog_start":
            self.mod_prog_frame_index += 1
            if self.mod_prog_frame_index < len(MOD_PROG_START_FRAMES):
                self._set_mod_prog_frame(
                    MOD_PROG_START_FRAMES[self.mod_prog_frame_index]
                )
            else:
                self.state = "mod_prog_loop"
                self.mod_prog_frame_index = 0
                self._set_mod_prog_frame(MOD_PROG_LOOP_FRAMES[0])
        elif self.state == "mod_prog_loop":
            self.mod_prog_frame_index = (self.mod_prog_frame_index + 1) % len(
                MOD_PROG_LOOP_FRAMES
            )
            self._set_mod_prog_frame(MOD_PROG_LOOP_FRAMES[self.mod_prog_frame_index])
        elif self.state == "mod_prog_exit":
            self.mod_prog_exit_index += 1
            if self.mod_prog_exit_index < len(MOD_PROG_EXIT_FRAMES):
                self._set_mod_prog_frame(MOD_PROG_EXIT_FRAMES[self.mod_prog_exit_index])
            else:
                self.state = "idle"
                self._set_frame(IDLE_FRAME)
                self.position_x = self.mod_prog_center_x - self.frame_width / 2
                self.position_y = self.mod_prog_bottom - self.frame_height
                self._move_window()
                self.next_decision_at = now + random.uniform(
                    REST_MIN_SECONDS, REST_MAX_SECONDS
                )
            
        frame_duration = (
            MOD_PROG_LOOP_FRAME_SECONDS
            if self.state == "mod_prog_loop"
            else FRAME_SECONDS
        )
        self.mod_prog_next_frame_at = now + frame_duration

    def _set_mod_ksp_frame(self, name):
        pixmap = self.frames[name]
        self.setFixedSize(pixmap.size())
        self.image.setFixedSize(pixmap.size())
        self.image.setPixmap(pixmap)
        self.position_x = self.mod_ksp_center_x - pixmap.width() / 2
        self.position_y = self.mod_ksp_bottom - pixmap.height()
        self._move_window()

    def _start_mod_ksp(self):
        if self.state != "idle":
            return
        self.state = "mod_ksp_frame1"
        self.mod_ksp_center_x = self.x() + self.width() / 2
        self.mod_ksp_bottom = self.y() + self.height()
        now = time.monotonic()
        self.mod_ksp_frame_index = 0
        self.mod_ksp_next_frame_at = now + MOD_KSP_FRAME1_DURATION
        self.mod_ksp_alarm_at = time.monotonic() + random.uniform(
            MOD_KSP_ALARM_MIN_SECONDS, MOD_KSP_ALARM_MAX_SECONDS
        )
        self.mod_ksp_frame1_at = time.monotonic() + random.uniform(
            MOD_KSP_FRAME1_MIN_SECONDS, MOD_KSP_FRAME1_MAX_SECONDS
        )
        self.mod_ksp_alarm_until = 0.0
        self._set_mod_ksp_frame(MOD_KSP_START_FRAME)

    def _stop_mod_ksp(self):
        if self.state not in ("mod_ksp_frame1", "mod_ksp_loop", "mod_ksp_alarm"):
            return
        self.state = "idle"
        self._set_frame(IDLE_FRAME)
        self.position_x = self.mod_ksp_center_x - self.frame_width / 2
        self.position_y = self.mod_ksp_bottom - self.frame_height
        self._move_window()
        now = time.monotonic()
        self.next_decision_at = now + random.uniform(REST_MIN_SECONDS, REST_MAX_SECONDS)
        self.next_idle_variant_at = now + random.uniform(
            IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
        )

    def _advance_mod_ksp(self, now):
        if self.state == "mod_ksp_alarm":
            if now >= self.mod_ksp_alarm_until:
                self.state = "mod_ksp_loop"
                self._set_mod_ksp_frame(MOD_KSP_LOOP_FRAMES[self.mod_ksp_frame_index])
                self.mod_ksp_next_frame_at = now + MOD_KSP_FRAME_SECONDS
                self.mod_ksp_alarm_at = now + random.uniform(
                    MOD_KSP_ALARM_MIN_SECONDS, MOD_KSP_ALARM_MAX_SECONDS
                )
                self.mod_ksp_frame1_at = now + random.uniform(
                    MOD_KSP_FRAME1_MIN_SECONDS, MOD_KSP_FRAME1_MAX_SECONDS
                )
            return

        if now >= self.mod_ksp_alarm_at:
            self.state = "mod_ksp_alarm"
            self._set_mod_ksp_frame(MOD_KSP_ALARM_FRAME)
            self.mod_ksp_alarm_until = now + MOD_KSP_ALARM_DURATION
            return

        if self.state == "mod_ksp_frame1":
            if now >= self.mod_ksp_next_frame_at:
                self.state = "mod_ksp_loop"
                self.mod_ksp_frame_index = 0
                self._set_mod_ksp_frame(MOD_KSP_LOOP_FRAMES[self.mod_ksp_frame_index])
                self.mod_ksp_next_frame_at = now + MOD_KSP_FRAME_SECONDS
                self.mod_ksp_frame1_at = now + random.uniform(
                    MOD_KSP_FRAME1_MIN_SECONDS, MOD_KSP_FRAME1_MAX_SECONDS
                )
            return

        if now >= self.mod_ksp_frame1_at:
            self.state = "mod_ksp_frame1"
            self._set_mod_ksp_frame(MOD_KSP_START_FRAME)
            self.mod_ksp_next_frame_at = now + MOD_KSP_FRAME1_DURATION
            return

        if now >= self.mod_ksp_next_frame_at:
            self.mod_ksp_frame_index = (self.mod_ksp_frame_index + 1) % len(
                MOD_KSP_LOOP_FRAMES
            )
            self._set_mod_ksp_frame(MOD_KSP_LOOP_FRAMES[self.mod_ksp_frame_index])
            self.mod_ksp_next_frame_at = now + MOD_KSP_FRAME_SECONDS

    def _render_pick_frame(self):
        source = self.frames[PICKUP_FRAME]
        anchor_x = PICKUP_HEAD_ANCHOR[0] * SPRITE_SCALE
        anchor_y = PICKUP_HEAD_ANCHOR[1] * SPRITE_SCALE

        if self.pick_direction < 0:
            source = source.transformed(QTransform().scale(-1, 1))
            anchor_x = self.frame_width - anchor_x

        transform = QTransform()
        transform.translate(anchor_x, anchor_y)
        transform.rotate(self.pick_angle)
        transform.translate(-anchor_x, -anchor_y)

        bounds = transform.mapRect(QRectF(0, 0, source.width(), source.height()))
        rotated = source.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        anchor_in_window = QPointF(anchor_x, anchor_y) - bounds.topLeft()

        self.setFixedSize(rotated.size())
        self.image.setFixedSize(rotated.size())
        self.image.setPixmap(rotated)
        if self.pick_cursor_position is not None:
            top_left = self.pick_cursor_position - anchor_in_window.toPoint()
            self.position_x = float(top_left.x())
            self.position_y = float(top_left.y())
            self._move_window()

    def _start_walk(self, direction):
        self.state = "walk"
        self.idle_variant_until = 0.0
        self.direction = direction
        side = "r" if direction > 0 else "l"
        cycles = random.randint(MIN_WALK_CYCLES, MAX_WALK_CYCLES)
        self.walk_frames = build_walk_sequence(side, cycles)
        self.walk_frame_index = 0
        self._set_frame(self.walk_frames[0])
        self.next_frame_at = time.monotonic() + FRAME_SECONDS

    def _begin_fall(self):
        center_x = self.x() + self.width() / 2
        top_y = self.y()
        self.setFixedSize(self.frame_width, self.frame_height)
        self.image.setFixedSize(self.frame_width, self.frame_height)
        self.position_x = center_x - self.frame_width / 2
        self.position_y = float(top_y)

        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        floor_y = area.y() + area.height()
        self.fall_floor_y = floor_y
        current_bottom = self.position_y + self.frame_height
        self.fall_landing_x = round(center_x)
        self.fall_landing_y = find_window_landing_y(
            self.fall_landing_x,
            round(current_bottom),
            floor_y,
            int(self.winId()),
        )
        self.platform_rect = None
        self.fall_landing_frame = FALL_FLOOR_FRAME
        self.fall_uses_window_alt = self.fall_landing_y is not None and random.random() < FALL4_ALT_CHANCE
        self.fall_window_alt_shown = False
        if self.fall_landing_y is None:
            self.fall_landing_y = floor_y
        else:
            self.fall_landing_frame = FALL_WINDOW_FRAME

        third_frame = (
            FALL3_ALT_FRAME if random.random() < FALL3_ALT_CHANCE else FALL3_FRAME
        )
        self.fall_frames = [*FALL_AIR_FRAMES, third_frame]
        if self.fall_uses_window_alt:
            self.fall_frames.append(FALL4_ALT_FRAME)

        self.fall_frame_index = 0
        self.fall_velocity = 0.0
        self.fall_next_frame_at = time.monotonic() + FRAME_SECONDS
        self.state = "falling"
        self._set_frame(self.fall_frames[0])
        self._move_window()

    def _finish_fall(self):
        self.state = "landed"
        self._set_frame(self.fall_landing_frame)
        if self.fall_landing_frame == FALL_FLOOR_FRAME:
            self.stand_up_at = time.monotonic() + FLOOR_STAND_DELAY
        else:
            self.next_window_support_check_at = (
                time.monotonic() + WINDOW_SUPPORT_CHECK_INTERVAL
            )

    def _check_window_support(self, now):
        if now < self.next_window_support_check_at:
            return

        self.next_window_support_check_at = now + WINDOW_SUPPORT_CHECK_INTERVAL
        if self.fall_landing_y is None:
            self._begin_fall()
            return

        current_surface_y = find_window_landing_y(
            self.fall_landing_x,
            round(self.fall_landing_y - 1),
            self.fall_floor_y,
            int(self.winId()),
        )
        if current_surface_y != self.fall_landing_y:
            self._begin_fall()

    def _start_standing_up(self, now):
        self.state = "getting_up"
        self.stand_up_frames = [FALL3_FRAME, "fall2.png", "fall1.png", IDLE_FRAME]
        self.stand_up_frame_index = 0
        self.stand_up_next_frame_at = now + FRAME_SECONDS
        self._set_frame(self.stand_up_frames[0])

    def _advance_standing_up(self, now):
        if now < self.stand_up_next_frame_at:
            return

        self.stand_up_frame_index += 1
        if self.stand_up_frame_index >= len(self.stand_up_frames):
            self.state = "idle"
            self.next_decision_at = now + random.uniform(
                REST_MIN_SECONDS, REST_MAX_SECONDS
            )
            self.next_idle_variant_at = now + random.uniform(
                IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
            )
            self._set_frame(IDLE_FRAME)
            return

        self._set_frame(self.stand_up_frames[self.stand_up_frame_index])
        self.stand_up_next_frame_at = now + FRAME_SECONDS

    def _advance_fall(self, now, elapsed):
        if now >= self.fall_next_frame_at and self.fall_frame_index + 1 < len(self.fall_frames):
            self.fall_frame_index += 1
            frame = self.fall_frames[self.fall_frame_index]
            self._set_frame(frame)
            if frame == FALL4_ALT_FRAME:
                self.fall_window_alt_shown = True
            self.fall_next_frame_at = now + FRAME_SECONDS

        self.fall_velocity = min(
            self.fall_velocity + FALL_GRAVITY * elapsed,
            FALL_MAX_VELOCITY,
        )
        next_y = self.position_y + self.fall_velocity * elapsed
        landing_top = self.fall_landing_y - self.frame_height
        if self.fall_landing_frame == FALL_WINDOW_FRAME:
            landing_top += round(self.frame_height * FALL_WINDOW_LANDING_OFFSET_RATIO)
            landing_top = min(landing_top, self.fall_floor_y - self.frame_height)

        if next_y >= landing_top:
            self.position_y = landing_top
            self._move_window()
            if self.fall_uses_window_alt and not self.fall_window_alt_shown:
                self.state = "landing_alt"
                self._set_frame(FALL4_ALT_FRAME)
                self.fall_window_alt_shown = True
                self.fall_next_frame_at = now + FRAME_SECONDS
            else:
                self._finish_fall()
            return

        self.position_y = next_y
        self._move_window()

    def _advance_landing_alt(self, now):
        if now >= self.fall_next_frame_at:
            self._finish_fall()

    def _finish_walk(self):
        self.state = "idle"
        self._set_frame(IDLE_FRAME)
        self.next_decision_at = time.monotonic() + random.uniform(
            REST_MIN_SECONDS, REST_MAX_SECONDS
        )

    def _tick(self):
        now = time.monotonic()
        elapsed = min(now - self.last_tick_at, 0.1)
        self.last_tick_at = now

        if self.paused:
            pass
        elif self.state in ("mod_prog_start", "mod_prog_loop", "mod_prog_exit"):
            self._advance_mod_prog(now)
        elif self.state in ("mod_ksp_frame1", "mod_ksp_loop", "mod_ksp_alarm"):
            self._advance_mod_ksp(now)
        elif self.state == "falling":
            self._advance_fall(now, elapsed)
        elif self.state == "landing_alt":
            self._advance_landing_alt(now)
        elif self.state == "landed":
            if self.fall_landing_frame == FALL_WINDOW_FRAME:
                self._check_window_support(now)
            elif now >= self.stand_up_at:
                self._start_standing_up(now)
        elif self.state == "getting_up":
            self._advance_standing_up(now)
        elif self.state == "picked":
            if abs(self.pick_angle) > 0.25:
                self.pick_angle *= 0.82
                if abs(self.pick_angle) < 0.5:
                    self.pick_angle = 0.0
                self._render_pick_frame()
        elif self.state == "idle":
            if self.idle_variant_until and now >= self.idle_variant_until:
                self.idle_variant_until = 0.0
                self._set_frame(IDLE_FRAME)
            elif not self.idle_variant_until and now >= self.next_idle_variant_at:
                self._set_frame(IDLE_VARIANT_FRAME)
                self.idle_variant_until = now + IDLE_VARIANT_DURATION
                self.next_idle_variant_at = now + random.uniform(
                    IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
                )
            elif now >= self.next_decision_at:
                if random.random() < 0.7:
                    self._start_walk(random.choice((-1, 1)))
                else:
                    self.next_decision_at = now + random.uniform(
                        REST_MIN_SECONDS, REST_MAX_SECONDS
                    )

        elif self.state == "walk":
            current_position = self.pos()
            self.position_x = current_position.x()
            self.position_y = current_position.y()
            self.position_x += self.direction * WALK_SPEED * elapsed
            screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            left_edge = area.x()
            right_edge = area.x() + area.width() - self.frame_width

            if self.position_x <= left_edge or self.position_x >= right_edge:
                self.position_x = min(max(self.position_x, left_edge), right_edge)
                self._move_window()
                self._start_walk(-self.direction)
            else:
                self._move_window()

            if now >= self.next_frame_at:
                self.walk_frame_index += 1
                if self.walk_frame_index >= len(self.walk_frames):
                    self._finish_walk()
                else:
                    self._set_frame(self.walk_frames[self.walk_frame_index])
                    self.next_frame_at = now + FRAME_SECONDS

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.globalPosition().toPoint()
            self._register_left_click(position)
            self.pending_pick_position = position
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            pause_action = menu.addAction("Resume" if self.paused else "Pause")
            pause_action.triggered.connect(self._toggle_pause)
            menu.addSeparator()
            if self.state in ("mod_prog_start", "mod_prog_loop"):
                menu.addAction("End mod_prog", self._end_mod_prog)
            elif self.state in ("mod_ksp_frame1", "mod_ksp_loop", "mod_ksp_alarm"):
                menu.addAction("End mod_ksp", self._stop_mod_ksp)
            elif self.state == "idle":
                menu.addAction("mod_prog", self._start_mod_prog)
                menu.addAction("mod_ksp", self._start_mod_ksp)
            menu.addAction("Clear wires", self.wire_overlay.clear_wires)
            menu.addAction("Quit", self.close)
            menu.exec(event.globalPosition().toPoint())
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.globalPosition().toPoint()
            self._register_left_click(position, double_click=True)
            self.pending_pick_position = position
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _register_left_click(self, position, double_click=False):
        if self.click_sequence_timer.isActive():
            self.left_click_count += 1
            self.click_sequence_timer.stop()
        else:
            self.left_click_count = 2 if double_click else 1

        if double_click:
            self.left_click_count = max(self.left_click_count, 2)
        self.click_sequence_position = position

    def _begin_pick(self, position):
        if self.state in ("mod_prog_start", "mod_prog_loop"):
            self.wire_overlay.set_enabled(False)
        elif self.state in ("mod_ksp_frame1", "mod_ksp_loop", "mod_ksp_alarm"):
            self._stop_mod_ksp()
        self.pick_cursor_position = position
        self.pick_press_position = position
        self.pick_dragged = False
        self.pick_last_move_at = time.monotonic()
        self.state = "picked"
        self.idle_variant_until = 0.0
        self.pick_angle = 0.0
        self.pick_direction = self.direction
        self.next_decision_at = time.monotonic() + random.uniform(
            REST_MIN_SECONDS, REST_MAX_SECONDS
        )
        self.next_idle_variant_at = time.monotonic() + random.uniform(
            IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
        )
        self._render_pick_frame()

    def _finish_click_sequence(self):
        if self.left_click_count >= 2:
            anchor = QPoint(round(self.x() + self.width() / 2), self.y())
            self.speech_bubble.show_quote(random.choice(self.quotes), anchor)
        self.left_click_count = 0
        self.pending_pick_position = None

    def mouseMoveEvent(self, event):
        if (
            self.state != "picked"
            and self.pending_pick_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            cursor_position = event.globalPosition().toPoint()
            drag_distance = (
                cursor_position - self.pending_pick_position
            ).manhattanLength()
            if drag_distance >= QApplication.startDragDistance():
                self.click_sequence_timer.stop()
                self.left_click_count = 0
                self._begin_pick(cursor_position)
                self.pick_dragged = True

        if (
            self.state == "picked"
            and self.pick_cursor_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            new_cursor_position = event.globalPosition().toPoint()
            if (
                self.pick_press_position is not None
                and (new_cursor_position - self.pick_press_position).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self.pick_dragged = True
            delta_x = new_cursor_position.x() - self.pick_cursor_position.x()
            now = time.monotonic()
            elapsed = max(now - self.pick_last_move_at, 0.001)
            horizontal_speed = delta_x / elapsed
            if delta_x:
                self.pick_direction = 1 if delta_x > 0 else -1
            target_angle = pickup_swing_angle(horizontal_speed)
            response = 0.2 + 0.5 * min(
                abs(horizontal_speed) / PICKUP_FULL_SWING_SPEED, 1.0
            )
            self.pick_angle += (target_angle - self.pick_angle) * response
            self.pick_cursor_position = new_cursor_position
            self.pick_last_move_at = now
            self._render_pick_frame()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self.state == "picked" and self.pick_dragged
            self.pick_cursor_position = None
            self.pick_angle = 0.0
            self.pick_press_position = None
            self.pick_dragged = False
            if was_dragging:
                self.click_sequence_timer.stop()
                self.left_click_count = 0
                self.pending_pick_position = None
                self._begin_fall()
            else:
                self.pending_pick_position = None
                self.click_sequence_timer.start()
            event.accept()

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.wire_overlay.set_enabled(False)
            if self.state in ("mod_ksp_frame1", "mod_ksp_loop", "mod_ksp_alarm"):
                self._stop_mod_ksp()
            self.idle_variant_until = 0.0
            self._set_frame(IDLE_FRAME)
        else:
            self.state = "idle"
            self.next_idle_variant_at = time.monotonic() + random.uniform(
                IDLE_VARIANT_MIN_INTERVAL, IDLE_VARIANT_MAX_INTERVAL
            )
            self.next_decision_at = time.monotonic() + random.uniform(
                REST_MIN_SECONDS, REST_MAX_SECONDS
            )
            self.last_tick_at = time.monotonic()

    def closeEvent(self, event):
        self.wire_overlay.close()
        self.speech_bubble.close()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description="A small desktop sprite companion.")
    parser.add_argument(
        "--show-sequence",
        action="store_true",
        help="print the walking frame sequence without opening the window",
    )
    args = parser.parse_args()

    if args.show_sequence:
        show_walk_sequences()
        return 0

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(True)
    try:
        shimeji = Shimeji()
        shimeji.show()
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as error:
        print(f"Could not start shimeji: {error}", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())