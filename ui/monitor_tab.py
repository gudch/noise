"""实时监控页 — 大白话版"""
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QGroupBox, QFrame, QScrollArea)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from ui.styles import COLORS


class MonitorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._waveform_data = np.zeros(48000 * 5)
        self._spectrum_data = None
        self._spectrum_freqs = None
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(8, 8, 8, 8)

        # ════════════════════════════════════════
        # 1. 超大状态显示 — 一眼就知道楼上安不安静
        # ════════════════════════════════════════
        status_card = QFrame()
        status_card.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 14px;
                padding: 20px;
            }}
        """)
        status_inner = QHBoxLayout(status_card)
        status_inner.setContentsMargins(24, 16, 24, 16)

        # 左：大图标 + 文字
        left_status = QVBoxLayout()
        self.status_icon = QLabel("⚪")
        self.status_icon.setFont(QFont("Segoe UI Emoji", 48))
        self.status_icon.setAlignment(Qt.AlignCenter)
        left_status.addWidget(self.status_icon)
        status_inner.addLayout(left_status)

        mid_status = QVBoxLayout()
        mid_status.setSpacing(6)

        self.status_label = QLabel("等待开始...")
        self.status_label.setObjectName("big_status")
        self.status_label.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
        mid_status.addWidget(self.status_label)

        self.status_detail = QLabel("👆 请点击下方绿色按钮「开始监控」")
        self.status_detail.setFont(QFont("Microsoft YaHei", 14))
        self.status_detail.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.status_detail.setWordWrap(True)
        mid_status.addWidget(self.status_detail)

        status_inner.addLayout(mid_status, stretch=1)

        # 右：音量指示
        vol_box = QVBoxLayout()
        vol_box.setAlignment(Qt.AlignCenter)
        vol_title = QLabel("当前音量")
        vol_title.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        vol_title.setAlignment(Qt.AlignCenter)
        vol_box.addWidget(vol_title)

        self.volume_label = QLabel("-- dB")
        self.volume_label.setFont(QFont("Consolas", 22, QFont.Bold))
        self.volume_label.setAlignment(Qt.AlignCenter)
        self.volume_label.setStyleSheet(f"color: {COLORS['primary']};")
        vol_box.addWidget(self.volume_label)

        self.volume_bar = QFrame()
        self.volume_bar.setFixedHeight(10)
        self.volume_bar.setFixedWidth(0)
        self.volume_bar.setStyleSheet(
            f"background: {COLORS['success']}; border-radius: 5px;")
        vol_box.addWidget(self.volume_bar, alignment=Qt.AlignCenter)

        status_inner.addLayout(vol_box)
        layout.addWidget(status_card)

        # ════════════════════════════════════════
        # 2. 噪音分析仪表盘 — 低频能量 = 楼上动静
        # ════════════════════════════════════════
        meter_card = QFrame()
        meter_card.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 14px;
            }}
        """)
        meter_inner = QHBoxLayout(meter_card)
        meter_inner.setContentsMargins(20, 16, 20, 16)
        meter_inner.setSpacing(8)

        self.band_labels = {}
        meter_items = [
            ('low', '🔴 楼上动静\n（低频 20-200Hz）',
             COLORS['low_freq'],
             '楼上走路、拖椅子、关门\n都是这个频段，数字越大声音越响'),
            ('mid', '🔵 说话/电视\n（中频 200-2kHz）',
             COLORS['mid_freq'],
             '人说话、看电视的声音频段'),
            ('high', '🟢 细碎声音\n（高频 2kHz以上）',
             COLORS['high_freq'],
             '杯子碰撞、手机铃声等'),
            ('ratio', '⚡ 楼上可疑程度',
             COLORS['warning'],
             '数字越大，越可能是楼上的噪音\n超过 2.0 就会自动标记'),
        ]

        for name, label_text, color, tip_text in meter_items:
            box = QVBoxLayout()
            box.setSpacing(4)

            title = QLabel(label_text)
            title.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
            title.setAlignment(Qt.AlignCenter)
            title.setWordWrap(True)
            box.addWidget(title)

            val = QLabel("--")
            val.setFont(QFont("Consolas", 24, QFont.Bold))
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(f"color: {color};")
            box.addWidget(val)

            tip = QLabel(tip_text)
            tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            tip.setAlignment(Qt.AlignCenter)
            tip.setWordWrap(True)
            box.addWidget(tip)

            meter_inner.addLayout(box)
            self.band_labels[name] = val

            # 分隔线（最后一个不加）
            if name != 'ratio':
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setStyleSheet(f"color: {COLORS['card_border']};")
                meter_inner.addWidget(sep)

        layout.addWidget(meter_card)

        # ════════════════════════════════════════
        # 3. 声音波形 — 实时声音图
        # ════════════════════════════════════════
        wave_grp = QGroupBox("🎵 实时声音波形（声音越大，波浪越高）")
        wave_lay = QVBoxLayout(wave_grp)
        self.waveform_plot = pg.PlotWidget()
        self.waveform_plot.setBackground(COLORS['bg'])
        self.waveform_plot.setYRange(-0.5, 0.5)
        self.waveform_plot.setMouseEnabled(x=False, y=False)
        self.waveform_plot.hideAxis('bottom')
        self.waveform_plot.hideAxis('left')
        self.waveform_plot.setFixedHeight(120)
        self.waveform_curve = self.waveform_plot.plot(
            pen=pg.mkPen(COLORS['primary'], width=1.5))
        wave_lay.addWidget(self.waveform_plot)
        layout.addWidget(wave_grp)

        # ════════════════════════════════════════
        # 4. 频谱图 — 分辨是楼上还是自家
        # ════════════════════════════════════════
        spec_grp = QGroupBox("📊 频率分析图（左边红色区域代表楼上低频噪音）")
        spec_lay = QVBoxLayout(spec_grp)

        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setBackground(COLORS['bg'])
        self.spectrum_plot.setLogMode(x=True, y=False)
        self.spectrum_plot.setYRange(-80, 0)
        self.spectrum_plot.setXRange(np.log10(20), np.log10(8000))
        self.spectrum_plot.setMouseEnabled(x=False, y=False)
        self.spectrum_plot.setFixedHeight(170)
        self.spectrum_plot.setLabel('bottom', '频率 (Hz)')
        self.spectrum_plot.setLabel('left', '强度 (dB)')

        self.low_freq_region = pg.LinearRegionItem(
            values=[np.log10(20), np.log10(200)],
            brush=pg.mkBrush(255, 71, 87, 35),
            movable=False
        )
        self.spectrum_plot.addItem(self.low_freq_region)

        self.spectrum_curve = self.spectrum_plot.plot(
            pen=pg.mkPen(COLORS['mid_freq'], width=2))

        spec_lay.addWidget(self.spectrum_plot)

        # 图例
        legend_lay = QHBoxLayout()
        for text, color in [
            ("◆ 红色区域 = 楼上噪音频段", COLORS['low_freq']),
            ("◆ 蓝色曲线 = 当前声音频率", COLORS['mid_freq']),
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
            legend_lay.addWidget(lbl)
        legend_lay.addStretch()
        spec_lay.addLayout(legend_lay)
        layout.addWidget(spec_grp)

        # ════════════════════════════════════════
        # 5. 今日统计
        # ════════════════════════════════════════
        today_card = QFrame()
        today_card.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 14px;
            }}
        """)
        today_inner = QHBoxLayout(today_card)
        today_inner.setContentsMargins(24, 16, 24, 16)

        # 噪音次数
        cnt_box = QVBoxLayout()
        cnt_title = QLabel("今天检测到楼上噪音")
        cnt_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        cnt_box.addWidget(cnt_title)
        self.today_count = QLabel("0 次")
        self.today_count.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        self.today_count.setStyleSheet(f"color: {COLORS['danger']};")
        cnt_box.addWidget(self.today_count)
        today_inner.addLayout(cnt_box)

        today_inner.addSpacing(40)

        # 总时长
        dur_box = QVBoxLayout()
        dur_title = QLabel("累计吵了多久")
        dur_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        dur_box.addWidget(dur_title)
        self.today_duration = QLabel("0 分钟")
        self.today_duration.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        self.today_duration.setStyleSheet(f"color: {COLORS['warning']};")
        dur_box.addWidget(self.today_duration)
        today_inner.addLayout(dur_box)

        today_inner.addSpacing(40)

        # 最近一次
        last_box = QVBoxLayout()
        last_title = QLabel("最近一次噪音")
        last_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        last_box.addWidget(last_title)
        self.today_last = QLabel("暂无")
        self.today_last.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        self.today_last.setStyleSheet(f"color: {COLORS['text']};")
        last_box.addWidget(self.today_last)
        today_inner.addLayout(last_box)

        today_inner.addStretch()
        layout.addWidget(today_card)

        layout.addStretch()
        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── 更新方法 ──
    def update_waveform(self, audio: np.ndarray):
        n = len(audio)
        self._waveform_data = np.roll(self._waveform_data, -n)
        self._waveform_data[-n:] = audio
        display = self._waveform_data[::10]
        self.waveform_curve.setData(display)

    def update_spectrum(self, freqs: np.ndarray, spectrum_db: np.ndarray):
        mask = freqs > 0
        self.spectrum_curve.setData(freqs[mask], spectrum_db[mask])

    def update_analysis(self, low_db, mid_db, high_db, ratio, rms_db):
        self.band_labels['low'].setText(f"{low_db:.1f}")
        self.band_labels['mid'].setText(f"{mid_db:.1f}")
        self.band_labels['high'].setText(f"{high_db:.1f}")
        self.band_labels['ratio'].setText(f"{ratio:.2f}")
        self.volume_label.setText(f"{rms_db:.1f} dB")

        # 音量条
        w = max(0, min(200, int((rms_db + 80) * 200 / 80)))
        self.volume_bar.setFixedWidth(w)

        # 音量颜色变化
        if rms_db > -30:
            self.volume_bar.setStyleSheet(
                f"background: {COLORS['danger']}; border-radius: 5px;")
        elif rms_db > -50:
            self.volume_bar.setStyleSheet(
                f"background: {COLORS['warning']}; border-radius: 5px;")
        else:
            self.volume_bar.setStyleSheet(
                f"background: {COLORS['success']}; border-radius: 5px;")

    def update_status(self, classification: str, state: str):
        STATUS_MAP = {
            'silent':   ('⚪', '楼上安静', COLORS['text_dim'],
                         '一切正常，没有检测到楼上噪音'),
            'upstairs': ('🔴', '楼上有动静！', COLORS['danger'],
                         '检测到楼上低频噪音，正在自动记录...'),
            'home':     ('🟢', '自家声音', COLORS['success'],
                         '检测到声音，但是你自己发出的，已忽略'),
            'unknown':  ('🟡', '正在分析...', COLORS['warning'],
                         '听到声音了，正在判断是不是楼上的'),
        }
        icon, text, color, detail = STATUS_MAP.get(
            classification, STATUS_MAP['unknown'])
        self.status_icon.setText(icon)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

        STATE_DETAIL = {
            'silent': '待机监听中...',
            'confirming': '听到可疑声音，正在确认...',
            'active': '⚠️ 楼上噪音事件进行中，正在录音',
            'cooldown': '噪音刚停，观察是否还会继续...',
        }
        full_detail = STATE_DETAIL.get(state, detail)
        self.status_detail.setText(full_detail)

    def update_today_stats(self, count, total_minutes, last_time_str):
        self.today_count.setText(f"{count} 次")
        self.today_duration.setText(f"{total_minutes:.1f} 分钟")
        self.today_last.setText(last_time_str or "暂无")
