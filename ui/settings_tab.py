"""设置页 — 大白话版"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QGroupBox, QComboBox, QSlider, QPushButton,
                              QCheckBox, QSpinBox, QScrollArea, QMessageBox,
                              QFrame)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from core.audio_capture import list_input_devices
from ui.styles import COLORS


class SettingsTab(QWidget):
    settings_changed = pyqtSignal()
    calibrate_requested = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._init_ui()
        self._load_values()

    def _make_card(self, title_text):
        """创建卡片样式的分组"""
        grp = QGroupBox(title_text)
        grp.setStyleSheet(f"""
            QGroupBox {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 12px;
                margin-top: 18px;
                padding: 24px 18px 18px 18px;
                font-weight: bold;
                font-size: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 12px;
                color: {COLORS['text_secondary']};
            }}
        """)
        return grp

    def _make_tip(self, text):
        """创建提示文字"""
        lbl = QLabel(text)
        lbl.setObjectName("tip_label")
        lbl.setWordWrap(True)
        return lbl

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 8, 12, 8)

        # ══════════════════════════════════════
        # 麦克风选择
        # ══════════════════════════════════════
        dev_grp = self._make_card("🎤 选择你的麦克风")
        dev_lay = QVBoxLayout(dev_grp)

        dev_lay.addWidget(self._make_tip(
            "💡 选择你放在桌上用来听声音的那个麦克风（ERAZER），"
            "然后点「试听」确认能正常收音"))

        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("麦克风："))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(400)
        self.device_combo.setMinimumHeight(40)
        dev_row.addWidget(self.device_combo, stretch=1)
        refresh_btn = QPushButton("🔄 刷新列表")
        refresh_btn.clicked.connect(self._refresh_devices)
        dev_row.addWidget(refresh_btn)
        dev_lay.addLayout(dev_row)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("🔊 试听 3 秒")
        self.test_btn.setToolTip("录 3 秒声音然后播放给你听，确认麦克风能用")
        test_row.addWidget(self.test_btn)
        self.test_btn.clicked.connect(self._test_device)
        self.test_status = QLabel("")
        self.test_status.setStyleSheet(f"color: {COLORS['text_dim']};")
        test_row.addWidget(self.test_status, stretch=1)
        dev_lay.addLayout(test_row)
        layout.addWidget(dev_grp)

        # ══════════════════════════════════════
        # 灵敏度调节
        # ══════════════════════════════════════
        sens_grp = self._make_card("🎚️ 灵敏度（多大声才算噪音？）")
        sens_lay = QVBoxLayout(sens_grp)

        sens_lay.addWidget(self._make_tip(
            "💡 如果经常误报（没有噪音却报警），把灵敏度调低一点；\n"
            "　　如果楼上有动静但没检测到，把灵敏度调高一点。\n"
            "　　一般校准后不需要手动调整。"))

        # 安静判断线
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("多安静算「没声音」："))
        self.silence_slider = QSlider(Qt.Horizontal)
        self.silence_slider.setRange(-80, -30)
        self.silence_slider.setValue(-55)
        self.silence_val = QLabel("-55 dB")
        self.silence_val.setMinimumWidth(60)
        self.silence_slider.valueChanged.connect(
            lambda v: self.silence_val.setText(f"{v} dB"))
        row1.addWidget(self.silence_slider, stretch=1)
        row1.addWidget(self.silence_val)
        sens_lay.addLayout(row1)

        slider_tip1 = QLabel("← 更灵敏（容易误报）　　　　　　不太灵敏（不容易误报）→")
        slider_tip1.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        slider_tip1.setAlignment(Qt.AlignCenter)
        sens_lay.addWidget(slider_tip1)

        sens_lay.addSpacing(10)

        # 楼上判定阈值
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("多大算「楼上噪音」："))
        self.ratio_slider = QSlider(Qt.Horizontal)
        self.ratio_slider.setRange(10, 50)
        self.ratio_slider.setValue(20)
        self.ratio_val = QLabel("2.0")
        self.ratio_val.setMinimumWidth(40)
        self.ratio_slider.valueChanged.connect(
            lambda v: self.ratio_val.setText(f"{v/10:.1f}"))
        row2.addWidget(self.ratio_slider, stretch=1)
        row2.addWidget(self.ratio_val)
        sens_lay.addLayout(row2)

        slider_tip2 = QLabel("← 容易判定为楼上　　　　　　　　不容易判定为楼上 →")
        slider_tip2.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        slider_tip2.setAlignment(Qt.AlignCenter)
        sens_lay.addWidget(slider_tip2)

        sens_lay.addSpacing(10)

        # 确认次数
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("听到几次才确认："))
        self.confirm_spin = QSpinBox()
        self.confirm_spin.setRange(1, 10)
        self.confirm_spin.setValue(3)
        self.confirm_spin.setMinimumHeight(36)
        row3.addWidget(self.confirm_spin)
        row3.addWidget(QLabel("次"))
        confirm_tip = QLabel("（数字越大越不容易误报，但反应会慢一点）")
        confirm_tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        row3.addWidget(confirm_tip)
        row3.addStretch()
        sens_lay.addLayout(row3)

        layout.addWidget(sens_grp)

        # ══════════════════════════════════════
        # 录音设置
        # ══════════════════════════════════════
        rec_grp = self._make_card("💾 录音（自动保存噪音证据）")
        rec_lay = QVBoxLayout(rec_grp)

        rec_lay.addWidget(self._make_tip(
            "💡 开启后，每次检测到楼上噪音都会自动录下来保存。\n"
            "　　你可以在「噪音记录」页面听回放。"))

        self.rec_enabled = QCheckBox("检测到噪音时自动录音保存")
        self.rec_enabled.setChecked(True)
        rec_lay.addWidget(self.rec_enabled)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("录音保存多少天后自动删除："))
        self.keep_days_spin = QSpinBox()
        self.keep_days_spin.setRange(1, 365)
        self.keep_days_spin.setValue(30)
        self.keep_days_spin.setMinimumHeight(36)
        row4.addWidget(self.keep_days_spin)
        row4.addWidget(QLabel("天"))
        row4.addStretch()
        rec_lay.addLayout(row4)
        layout.addWidget(rec_grp)

        # ══════════════════════════════════════
        # 提醒设置
        # ══════════════════════════════════════
        alert_grp = self._make_card("🔔 提醒方式（检测到噪音时怎么通知你）")
        alert_lay = QVBoxLayout(alert_grp)
        self.alert_sound = QCheckBox("播放提示音")
        self.alert_sound.setChecked(True)
        alert_lay.addWidget(self.alert_sound)
        self.alert_popup = QCheckBox("在屏幕底部显示消息")
        self.alert_popup.setChecked(True)
        alert_lay.addWidget(self.alert_popup)
        layout.addWidget(alert_grp)

        # ══════════════════════════════════════
        # 校准
        # ══════════════════════════════════════
        cal_grp = self._make_card("🔧 校准（让程序知道你家正常有多安静）")
        cal_lay = QVBoxLayout(cal_grp)

        cal_lay.addWidget(self._make_tip(
            "💡 第一次使用必须校准！在家里安静的时候（没有电视、没说话），\n"
            "　　点下面的按钮，程序会听 5 秒钟，记住你家的背景噪音水平。\n"
            "　　以后就能分辨出哪些是额外的楼上噪音了。"))

        self.cal_btn = QPushButton("🔧 开始校准（请先开始监控）")
        self.cal_btn.setMinimumHeight(48)
        self.cal_btn.clicked.connect(self.calibrate_requested.emit)
        cal_lay.addWidget(self.cal_btn)

        self.cal_status = QLabel("")
        self.cal_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        cal_lay.addWidget(self.cal_status)
        layout.addWidget(cal_grp)

        # 保存按钮
        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = QPushButton("💾 保存所有设置")
        save_btn.setMinimumHeight(48)
        save_btn.setMinimumWidth(200)
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        save_row.addStretch()
        layout.addLayout(save_row)

        layout.addStretch()
        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _refresh_devices(self):
        self.device_combo.clear()
        devices = list_input_devices()
        configured = self._config.get("device", "index", -1)
        for d in devices:
            label = f"{d['name']}  [{d['host_api']}]  {d['sample_rate']}Hz"
            self.device_combo.addItem(label, d['index'])
            if d['index'] == configured:
                self.device_combo.setCurrentIndex(
                    self.device_combo.count() - 1)

    def _test_device(self):
        idx = self.device_combo.currentData()
        if idx is None:
            return
        import sounddevice as sd
        import numpy as np
        import threading

        dev_info = sd.query_devices(idx)
        sr = int(dev_info['default_samplerate'])

        self.test_btn.setEnabled(False)
        self.test_status.setText("🎤 正在录音...")
        self.test_status.setStyleSheet(f"color: {COLORS['danger']}; font-weight: bold;")

        def _worker():
            try:
                audio = sd.rec(int(3 * sr), samplerate=sr, channels=1,
                               dtype='float32', device=idx)
                sd.wait()
                audio = audio[:, 0]
                rms = float(np.sqrt(np.mean(audio ** 2)))
                peak = float(np.max(np.abs(audio)))
                self.test_status.setText("🔊 正在播放刚才录到的声音...")
                self.test_status.setStyleSheet(f"color: {COLORS['success']}; font-weight: bold;")
                gain = min(0.8 / max(peak, 0.001), 50.0)
                sd.play(audio * gain, samplerate=sr)
                sd.wait()
                db_val = 20*np.log10(max(rms,1e-10))
                if db_val > -40:
                    verdict = "✅ 麦克风工作正常，收音很好！"
                elif db_val > -55:
                    verdict = "✅ 麦克风正常，收音一般"
                else:
                    verdict = "⚠️ 声音很小，检查一下麦克风是否插好"
                self.test_status.setText(verdict)
                self.test_status.setStyleSheet(f"color: {COLORS['success']};")
            except Exception as e:
                self.test_status.setText(f"❌ 测试失败: {e}")
                self.test_status.setStyleSheet(f"color: {COLORS['danger']};")
            finally:
                self.test_btn.setEnabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    def _load_values(self):
        self._refresh_devices()
        det = self._config.detection
        self.silence_slider.setValue(int(det.get('silence_threshold_db', -55)))
        self.ratio_slider.setValue(int(det.get('ratio_threshold', 2.0) * 10))
        self.confirm_spin.setValue(det.get('confirm_frames', 3))
        rec = self._config.recording
        self.rec_enabled.setChecked(rec.get('enabled', True))
        self.keep_days_spin.setValue(rec.get('max_keep_days', 30))
        alert = self._config.alert
        self.alert_sound.setChecked(alert.get('sound_enabled', True))
        self.alert_popup.setChecked(alert.get('popup_enabled', True))

    def _save(self):
        idx = self.device_combo.currentData()
        if idx is not None:
            self._config.set("device", "index", idx)
        self._config.set("detection", "silence_threshold_db",
                         self.silence_slider.value())
        self._config.set("detection", "ratio_threshold",
                         self.ratio_slider.value() / 10.0)
        self._config.set("detection", "confirm_frames",
                         self.confirm_spin.value())
        self._config.set("recording", "enabled", self.rec_enabled.isChecked())
        self._config.set("recording", "max_keep_days",
                         self.keep_days_spin.value())
        self._config.set("alert", "sound_enabled",
                         self.alert_sound.isChecked())
        self._config.set("alert", "popup_enabled",
                         self.alert_popup.isChecked())
        self._config.save()
        self.settings_changed.emit()
        QMessageBox.information(self, "保存成功", "✅ 设置已保存！")
