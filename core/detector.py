"""事件检测器 - 状态机管理噪音事件生命周期"""
import time
from dataclasses import dataclass, field
from enum import Enum
from PyQt5.QtCore import QObject, pyqtSignal

from core.analyzer import AnalysisResult


class State(Enum):
    SILENT = "silent"
    TRIGGERED = "triggered"
    CONFIRMING = "confirming"
    ACTIVE = "active"
    COOLDOWN = "cooldown"


@dataclass
class NoiseEvent:
    """一次噪音事件"""
    start_time: float = 0.0
    end_time: float = 0.0
    peak_db: float = -100.0
    peak_ratio: float = 0.0
    frame_count: int = 0
    source: str = "upstairs"

    @property
    def duration(self):
        return self.end_time - self.start_time


class Detector(QObject):
    """
    状态机:
      SILENT → TRIGGERED → CONFIRMING → ACTIVE → COOLDOWN → SILENT
    """
    event_started = pyqtSignal(object)   # NoiseEvent
    event_updated = pyqtSignal(object)   # NoiseEvent (进行中更新)
    event_ended = pyqtSignal(object)     # NoiseEvent (最终)
    state_changed = pyqtSignal(str)      # 状态名称

    def __init__(self, ratio_threshold=2.0, silence_db=-55,
                 confirm_frames=3, cooldown_seconds=2.0):
        super().__init__()
        self._ratio_threshold = ratio_threshold
        self._silence_db = silence_db
        self._confirm_frames = confirm_frames
        self._cooldown_seconds = cooldown_seconds

        self._state = State.SILENT
        self._confirm_count = 0
        self._current_event = None
        self._cooldown_start = 0.0
        self._home_active = False  # "我在活动"标记

    @property
    def state(self):
        return self._state

    def set_home_active(self, active: bool):
        """标记自己正在制造噪音，抑制检测"""
        self._home_active = active

    def set_thresholds(self, ratio_threshold=None, silence_db=None):
        if ratio_threshold is not None:
            self._ratio_threshold = ratio_threshold
        if silence_db is not None:
            self._silence_db = silence_db

    def feed(self, result: AnalysisResult, classification: str):
        """输入每帧分析结果，驱动状态机"""
        now = time.time()

        if self._home_active:
            # 用户标记自己在活动，不触发事件
            if self._state == State.ACTIVE:
                self._end_event(now)
            self._to_state(State.SILENT)
            return

        is_upstairs = (classification == 'upstairs' and
                       result.rms_db > self._silence_db)

        if self._state == State.SILENT:
            if is_upstairs:
                self._confirm_count = 1
                self._to_state(State.CONFIRMING)

        elif self._state == State.CONFIRMING:
            if is_upstairs:
                self._confirm_count += 1
                if self._confirm_count >= self._confirm_frames:
                    self._start_event(now, result)
                    self._to_state(State.ACTIVE)
            else:
                self._confirm_count = 0
                self._to_state(State.SILENT)

        elif self._state == State.ACTIVE:
            if is_upstairs:
                self._update_event(result)
            else:
                self._cooldown_start = now
                self._to_state(State.COOLDOWN)

        elif self._state == State.COOLDOWN:
            if is_upstairs:
                # 冷却期间又检测到 → 回到 ACTIVE
                self._update_event(result)
                self._to_state(State.ACTIVE)
            elif now - self._cooldown_start > self._cooldown_seconds:
                self._end_event(now)
                self._to_state(State.SILENT)

    def _to_state(self, new_state: State):
        if new_state != self._state:
            self._state = new_state
            self.state_changed.emit(new_state.value)

    def _start_event(self, now, result: AnalysisResult):
        self._current_event = NoiseEvent(
            start_time=now,
            peak_db=result.rms_db,
            peak_ratio=result.ratio,
            frame_count=1,
            source="upstairs",
        )
        self.event_started.emit(self._current_event)

    def _update_event(self, result: AnalysisResult):
        if self._current_event:
            self._current_event.frame_count += 1
            if result.rms_db > self._current_event.peak_db:
                self._current_event.peak_db = result.rms_db
            if result.ratio > self._current_event.peak_ratio:
                self._current_event.peak_ratio = result.ratio
            self.event_updated.emit(self._current_event)

    def _end_event(self, now):
        if self._current_event:
            self._current_event.end_time = now
            self.event_ended.emit(self._current_event)
            self._current_event = None
