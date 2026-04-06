"""主窗口 — 引导式布局"""
from PyQt5.QtWidgets import (QMainWindow, QTabWidget, QHBoxLayout, QVBoxLayout,
                              QPushButton, QWidget, QLabel, QStatusBar)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from ui.monitor_tab import MonitorTab
from ui.log_tab import LogTab
from ui.stats_tab import StatsTab
from ui.settings_tab import SettingsTab
from ui.styles import STYLESHEET, COLORS


class MainWindow(QMainWindow):
    def __init__(self, config, database):
        super().__init__()
        self._config = config
        self._db = database
        self.setWindowTitle("NoiseGuard — 楼上噪音监测助手")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(12, 10, 12, 10)
        main_lay.setSpacing(10)

        # ── 顶部引导提示 ──
        self.guide_banner = QLabel("")
        self.guide_banner.setObjectName("guide_banner")
        self.guide_banner.setWordWrap(True)
        self.guide_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_lay.addWidget(self.guide_banner)

        # ── Tab 页 ──
        self.tabs = QTabWidget()
        self.monitor_tab = MonitorTab()
        self.log_tab = LogTab(self._db)
        self.stats_tab = StatsTab(self._db)
        self.settings_tab = SettingsTab(self._config)

        self.tabs.addTab(self.monitor_tab, "📊 实时监控")
        self.tabs.addTab(self.log_tab, "📋 噪音记录")
        self.tabs.addTab(self.stats_tab, "📈 统计报表")
        self.tabs.addTab(self.settings_tab, "⚙️ 设置")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_lay.addWidget(self.tabs)

        # ── 底部操作栏 ──
        ctrl_container = QWidget()
        ctrl_container.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['surface']};
                border-radius: 12px;
                border: 1px solid {COLORS['card_border']};
            }}
        """)
        ctrl_inner = QHBoxLayout(ctrl_container)
        ctrl_inner.setContentsMargins(16, 12, 16, 12)
        ctrl_inner.setSpacing(12)

        # 开始/停止按钮 — 最重要的按钮，放最大
        start_box = QVBoxLayout()
        self.start_btn = QPushButton("🎤 开始监控")
        self.start_btn.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self.start_btn.setMinimumHeight(56)
        self.start_btn.setMinimumWidth(220)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['success']};
                border-radius: 12px;
                font-size: 18px;
            }}
            QPushButton:hover {{ background: #3ae080; }}
        """)
        start_box.addWidget(self.start_btn)
        start_tip = QLabel("第一步：点这里让程序开始听声音")
        start_tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent; border: none;")
        start_tip.setAlignment(Qt.AlignCenter)
        start_box.addWidget(start_tip)
        ctrl_inner.addLayout(start_box)

        # 校准按钮
        cal_box = QVBoxLayout()
        self.cal_btn = QPushButton("🔧 校准环境噪音")
        self.cal_btn.setFont(QFont("Microsoft YaHei", 13))
        self.cal_btn.setMinimumHeight(56)
        self.cal_btn.setMinimumWidth(180)
        self.cal_btn.setToolTip("在安静时点这个按钮，让程序记住你家正常的背景声音")
        cal_box.addWidget(self.cal_btn)
        cal_tip = QLabel("第二步：安静时校准（只需做一次）")
        cal_tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent; border: none;")
        cal_tip.setAlignment(Qt.AlignCenter)
        cal_box.addWidget(cal_tip)
        ctrl_inner.addLayout(cal_box)

        ctrl_inner.addSpacing(20)

        # 我在家活动 按钮
        home_box = QVBoxLayout()
        self.home_btn = QPushButton("🏠 我在家走动/做事")
        self.home_btn.setFont(QFont("Microsoft YaHei", 13))
        self.home_btn.setMinimumHeight(56)
        self.home_btn.setMinimumWidth(200)
        self.home_btn.setCheckable(True)
        self.home_btn.setToolTip("自己在家走动或做家务时打开，避免把自家声音误当成楼上噪音")
        self.home_btn.setStyleSheet(f"""
            QPushButton {{
                background: #444460;
                border-radius: 12px;
            }}
            QPushButton:hover {{ background: #555575; }}
            QPushButton:checked {{
                background: {COLORS['success']};
            }}
        """)
        home_box.addWidget(self.home_btn)
        home_tip = QLabel("自己活动时打开，避免误报")
        home_tip.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent; border: none;")
        home_tip.setAlignment(Qt.AlignCenter)
        home_box.addWidget(home_tip)
        ctrl_inner.addLayout(home_box)

        main_lay.addWidget(ctrl_container)

        # ── 状态栏 ──
        sb = QStatusBar()
        sb.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        self.setStatusBar(sb)

    def set_guide_text(self, text):
        """设置顶部引导提示文字"""
        if text:
            self.guide_banner.setText(text)
            self.guide_banner.show()
        else:
            self.guide_banner.hide()

    def _on_tab_changed(self, idx):
        if idx == 1:  # 日志页
            self.log_tab.refresh()
        elif idx == 2:  # 统计页
            self.stats_tab.refresh()
