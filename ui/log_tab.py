"""噪音记录页 — 带回放功能"""
import os
import time
import threading
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView, QPushButton,
                              QHBoxLayout, QLabel, QFrame)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from ui.styles import COLORS


class LogTab(QWidget):
    def __init__(self, database):
        super().__init__()
        self._db = database
        self._playing = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 标题 + 说明
        header = QHBoxLayout()
        title = QLabel("📋 噪音记录")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        tip = QLabel(
            "💡 这里显示今天所有检测到的楼上噪音事件。"
            "点击最右边的 ▶ 按钮就可以听当时录下来的声音。")
        tip.setObjectName("tip_label")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "发生时间", "吵了多久", "最大音量", "可疑程度",
            "判定来源", "有录音", "回放"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 70)
        self.table.setColumnWidth(6, 100)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # 底部提示
        bottom_tip = QLabel("💡 录音文件保存在 recordings 文件夹中，也可以用播放器直接打开")
        bottom_tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(bottom_tip)

    def refresh(self):
        events = self._db.get_events_today()
        self.table.setRowCount(len(events))
        for i, ev in enumerate(events):
            start = time.strftime("%H:%M:%S", time.localtime(ev['start_time']))
            dur = f"{ev['duration']:.1f} 秒"
            peak = f"{ev['peak_db']:.1f} dB"
            ratio = f"{ev['peak_ratio']:.2f}"
            source = "🔴 楼上" if ev['source'] == 'upstairs' else \
                     "🟡 未知" if ev['source'] == 'unknown' else ev['source']
            rec_path = ev.get('recording_path', '')
            has_rec = "✅ 有" if rec_path and os.path.exists(rec_path) else "❌ 无"

            for j, val in enumerate([start, dur, peak, ratio, source, has_rec]):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, item)

            # 播放按钮
            if rec_path and os.path.exists(rec_path):
                play_btn = QPushButton("▶ 播放")
                play_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['primary']};
                        border-radius: 6px;
                        padding: 6px 12px;
                        font-size: 13px;
                    }}
                    QPushButton:hover {{ background: {COLORS['primary_hover']}; }}
                """)
                play_btn.clicked.connect(
                    lambda checked, path=rec_path: self._play_recording(path))
                self.table.setCellWidget(i, 6, play_btn)
            else:
                item = QTableWidgetItem("—")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(Qt.gray)
                self.table.setItem(i, 6, item)

    def _play_recording(self, path):
        """播放录音文件"""
        if self._playing:
            return
        self._playing = True

        def _worker():
            try:
                import sounddevice as sd
                import numpy as np
                from scipy.io import wavfile
                sr, data = wavfile.read(path)
                if data.dtype == np.int16:
                    data = data.astype(np.float32) / 32768.0
                elif data.dtype == np.int32:
                    data = data.astype(np.float32) / 2147483648.0
                if data.ndim > 1:
                    data = data[:, 0]
                sd.play(data, samplerate=sr)
                sd.wait()
            except Exception:
                pass
            finally:
                self._playing = False

        threading.Thread(target=_worker, daemon=True).start()
