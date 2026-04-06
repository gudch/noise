"""NoiseGuard - 楼上噪音智能监测系统 入口"""
import sys
import time
import numpy as np
import sounddevice as sd
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer

from core.config_manager import ConfigManager
from core.audio_capture import AudioCapture
from core.analyzer import Analyzer
from core.detector import Detector
from core.recorder import Recorder
from db.database import Database
from ui.main_window import MainWindow


class NoiseGuardApp:
    def __init__(self):
        self.config = ConfigManager()
        self.db = Database()

        # 核心组件
        det_cfg = self.config.detection
        self.analyzer = Analyzer(
            low_range=tuple(det_cfg.get('low_freq_range', [20, 200])),
            mid_range=tuple(det_cfg.get('mid_freq_range', [200, 2000])),
            high_range=tuple(det_cfg.get('high_freq_range', [2000, 8000])),
            silence_db=det_cfg.get('silence_threshold_db', -55),
        )
        self.detector = Detector(
            ratio_threshold=det_cfg.get('ratio_threshold', 2.0),
            silence_db=det_cfg.get('silence_threshold_db', -55),
            confirm_frames=det_cfg.get('confirm_frames', 3),
            cooldown_seconds=det_cfg.get('cooldown_seconds', 2.0),
        )

        rec_cfg = self.config.recording
        dev_cfg = self.config.device
        self.recorder = Recorder(
            sample_rate=dev_cfg.get('sample_rate', 48000),
            pre_buffer_sec=rec_cfg.get('pre_buffer_seconds', 3),
            post_buffer_sec=rec_cfg.get('post_buffer_seconds', 3),
            output_dir=rec_cfg.get('output_dir', 'recordings'),
        )

        self.capture = AudioCapture(
            device_index=dev_cfg.get('index', -1),
            sample_rate=dev_cfg.get('sample_rate', 48000),
            block_size=dev_cfg.get('block_size', 2048),
        )

        self._monitoring = False
        self._calibrating = False
        self._cal_frames = []

    def setup_ui(self, window: MainWindow):
        self.window = window

        # 按钮连接
        window.start_btn.clicked.connect(self._toggle_monitoring)
        window.home_btn.toggled.connect(self._on_home_toggle)
        window.cal_btn.clicked.connect(self._start_calibration)
        window.settings_tab.calibrate_requested.connect(self._start_calibration)
        window.settings_tab.settings_changed.connect(self._on_settings_changed)

        # 核心信号
        self.capture.audio_frame.connect(self._on_audio_frame)
        self.capture.error.connect(self._on_capture_error)
        self.detector.event_started.connect(self._on_event_started)
        self.detector.event_ended.connect(self._on_event_ended)
        self.detector.state_changed.connect(self._on_state_changed)

        # 今日统计定时刷新
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._refresh_today_stats)
        self._stats_timer.start(5000)
        self._refresh_today_stats()

        # 清理旧录音
        self.recorder.cleanup_old(
            self.config.recording.get('max_keep_days', 30))

        self._last_classification = 'silent'

        # ── 显示引导提示 ──
        self._update_guide()

    def _update_guide(self):
        """根据当前状态显示引导提示"""
        calibrated = self.config.calibration.get('calibrated', False)

        if not self._monitoring:
            if not calibrated:
                self.window.set_guide_text(
                    "👋 欢迎使用！第一步：点击下方绿色「开始监控」按钮 → "
                    "第二步：在安静时点「校准环境噪音」→ "
                    "然后程序就会自动帮你监测楼上噪音啦！")
            else:
                self.window.set_guide_text(
                    "✅ 已校准完毕！点击下方绿色「开始监控」按钮就能开始监测了。")
        elif self._monitoring and not calibrated:
            self.window.set_guide_text(
                "🎤 正在听声音... 现在请保持安静，"
                "然后点击「校准环境噪音」按钮，让程序记住你家正常有多安静。")
        elif self._monitoring and calibrated:
            self.window.set_guide_text("")

    def _toggle_monitoring(self):
        if self._monitoring:
            self.capture.stop()
            self._monitoring = False
            self.window.start_btn.setText("🎤 开始监控")
            self.window.start_btn.setStyleSheet("""
                QPushButton {
                    background: #2ed573;
                    border-radius: 12px;
                    font-size: 18px;
                }
                QPushButton:hover { background: #3ae080; }
            """)
            self.window.monitor_tab.status_label.setText("已停止")
            self.window.monitor_tab.status_detail.setText(
                "👆 点击下方绿色按钮重新开始")
            self.window.monitor_tab.status_icon.setText("⏸")
        else:
            self.capture.start()
            self._monitoring = True
            self.window.start_btn.setText("⏹ 停止监控")
            self.window.start_btn.setStyleSheet("""
                QPushButton {
                    background: #ff4757;
                    border-radius: 12px;
                    font-size: 18px;
                }
                QPushButton:hover { background: #ff6b7a; }
            """)
            self.window.monitor_tab.status_detail.setText(
                "正在监听中...")

        self._update_guide()

    def _on_home_toggle(self, active):
        self.detector.set_home_active(active)
        if active:
            self.window.home_btn.setText("🏠 我在活动中（点击取消）")
        else:
            self.window.home_btn.setText("🏠 我在家走动/做事")

    def _on_audio_frame(self, audio: np.ndarray, sample_rate: int):
        # 校准模式
        if self._calibrating:
            self._cal_frames.append(audio.copy())
            elapsed = len(self._cal_frames) * len(audio) / sample_rate
            remaining = max(0, self.config.calibration.get(
                'duration_seconds', 5) - elapsed)
            self.window.monitor_tab.status_detail.setText(
                f"🔧 正在校准...请保持安静（还剩 {remaining:.0f} 秒）")
            if elapsed >= self.config.calibration.get('duration_seconds', 5):
                self._finish_calibration(sample_rate)
            return

        # 正常分析
        result = self.analyzer.analyze(audio, sample_rate)
        classification = self.analyzer.classify(result)
        self._last_classification = classification

        # 喂入检测器
        self.detector.feed(result, classification)

        # 录音缓冲
        self.recorder.feed(audio)

        # 更新 UI
        mt = self.window.monitor_tab
        mt.update_waveform(audio)
        mt.update_spectrum(result.freqs, result.spectrum)
        mt.update_analysis(
            result.low_db, result.mid_db, result.high_db,
            result.ratio, result.rms_db)
        mt.update_status(classification, self.detector.state.value)

    def _on_capture_error(self, msg):
        QMessageBox.critical(self.window, "麦克风出错了",
                             f"无法读取麦克风数据，请检查麦克风是否插好。\n\n"
                             f"错误信息：{msg}")
        self._monitoring = False
        self.window.start_btn.setText("🎤 开始监控")
        self.window.start_btn.setStyleSheet("""
            QPushButton {
                background: #2ed573;
                border-radius: 12px;
                font-size: 18px;
            }
            QPushButton:hover { background: #3ae080; }
        """)
        self._update_guide()

    def _on_state_changed(self, state_name):
        pass

    def _on_event_started(self, event):
        if self.config.recording.get('enabled', True):
            self.recorder.start_recording()

    def _on_event_ended(self, event):
        self.recorder.stop_recording()
        self.db.insert_event(
            start_time=event.start_time,
            end_time=event.end_time,
            peak_db=event.peak_db,
            peak_ratio=event.peak_ratio,
            source=event.source,
        )
        self._refresh_today_stats()

        # 底部状态栏消息
        if self.config.alert.get('popup_enabled', True):
            dur = event.duration
            self.window.statusBar().showMessage(
                f"🔴 楼上噪音结束 — 吵了 {dur:.1f} 秒，"
                f"最大音量 {event.peak_db:.1f}dB，"
                f"录音已自动保存", 15000)

    def _start_calibration(self):
        if not self._monitoring:
            QMessageBox.information(
                self.window, "需要先开始监控",
                "请先点击绿色的「开始监控」按钮，\n"
                "让麦克风开始工作后，再来校准。\n\n"
                "校准时请保持安静，不要说话、不要走动。")
            return
        self._calibrating = True
        self._cal_frames = []
        self.window.monitor_tab.status_icon.setText("🔧")
        self.window.monitor_tab.status_label.setText("校准中...")
        self.window.monitor_tab.status_label.setStyleSheet(
            "color: #ffa502;")
        self.window.monitor_tab.status_detail.setText(
            "🔧 正在校准...请保持安静（5秒）")
        self.window.settings_tab.cal_status.setText("⏳ 校准中...请保持安静")

    def _finish_calibration(self, sample_rate):
        self._calibrating = False
        all_audio = np.concatenate(self._cal_frames)
        self.analyzer.calibrate(all_audio, sample_rate)
        self.detector.set_thresholds(silence_db=self.analyzer._silence_db)

        floor_db = self.analyzer.noise_floor_db
        threshold_db = self.analyzer._silence_db

        self.window.monitor_tab.status_icon.setText("✅")
        self.window.monitor_tab.status_label.setText("校准完成！")
        self.window.monitor_tab.status_label.setStyleSheet(
            "color: #2ed573;")
        self.window.monitor_tab.status_detail.setText(
            f"✅ 你家背景噪音 {floor_db:.1f}dB，"
            f"超过 {threshold_db:.1f}dB 就算有动静。现在开始自动监测！")
        self.window.settings_tab.cal_status.setText(
            f"✅ 校准成功！背景噪音: {floor_db:.1f}dB")
        self.window.settings_tab.silence_slider.setValue(int(threshold_db))

        self.config.set("calibration", "noise_floor_db", floor_db)
        self.config.set("calibration", "calibrated", True)
        self.config.set("detection", "silence_threshold_db", int(threshold_db))
        self.config.save()

        self._update_guide()

    def _on_settings_changed(self):
        det = self.config.detection
        self.analyzer._silence_db = det.get('silence_threshold_db', -55)
        self.analyzer._low_range = tuple(det.get('low_freq_range', [20, 200]))
        self.analyzer._mid_range = tuple(det.get('mid_freq_range', [200, 2000]))
        self.analyzer._high_range = tuple(det.get('high_freq_range', [2000, 8000]))
        self.detector.set_thresholds(
            ratio_threshold=det.get('ratio_threshold', 2.0),
            silence_db=det.get('silence_threshold_db', -55),
        )

    def _refresh_today_stats(self):
        events = self.db.get_events_today()
        count = len(events)
        total_dur = sum(e['duration'] for e in events) / 60.0
        last_str = ""
        if events:
            t = time.localtime(events[0]['start_time'])
            last_str = time.strftime("%H:%M:%S", t)
        self.window.monitor_tab.update_today_stats(count, total_dur, last_str)


def main():
    app = QApplication(sys.argv)
    config = ConfigManager()
    db = Database()

    window = MainWindow(config, db)
    engine = NoiseGuardApp()
    engine.config = config
    engine.db = db
    engine.setup_ui(window)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
