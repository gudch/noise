"""统计页 — 大白话版"""
import pyqtgraph as pg
import numpy as np
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QGroupBox, QPushButton)
from PyQt5.QtGui import QFont
from ui.styles import COLORS


class StatsTab(QWidget):
    def __init__(self, database):
        super().__init__()
        self._db = database
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("📈 噪音统计报表")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("🔄 刷新数据")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        tip = QLabel("💡 这里显示最近一周的噪音统计，帮你了解楼上什么时候最吵。")
        tip.setObjectName("tip_label")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # ── 每日统计柱状图 ──
        daily_grp = QGroupBox("📅 最近 7 天楼上吵了几次？")
        daily_lay = QVBoxLayout(daily_grp)
        self.daily_plot = pg.PlotWidget()
        self.daily_plot.setBackground(COLORS['bg'])
        self.daily_plot.setFixedHeight(220)
        self.daily_plot.setLabel('left', '噪音次数')
        self.daily_bar = pg.BarGraphItem(
            x=list(range(7)), height=[0]*7, width=0.6,
            brush=COLORS['danger']
        )
        self.daily_plot.addItem(self.daily_bar)
        daily_lay.addWidget(self.daily_plot)
        layout.addWidget(daily_grp)

        # ── 时段分布 ──
        hour_grp = QGroupBox("🕐 一天中哪个时段最吵？（最近 7 天汇总）")
        hour_lay = QVBoxLayout(hour_grp)
        self.hour_plot = pg.PlotWidget()
        self.hour_plot.setBackground(COLORS['bg'])
        self.hour_plot.setFixedHeight(220)
        self.hour_plot.setXRange(-0.5, 23.5)
        self.hour_plot.setLabel('left', '噪音次数')
        self.hour_plot.setLabel('bottom', '时间')
        self.hour_bar = pg.BarGraphItem(
            x=list(range(24)), height=[0]*24, width=0.7,
            brush=COLORS['warning']
        )
        self.hour_plot.addItem(self.hour_bar)
        hour_lay.addWidget(self.hour_plot)
        layout.addWidget(hour_grp)

        layout.addStretch()

    def refresh(self):
        daily = self._db.get_daily_stats(7)
        daily.reverse()
        dates = [d['date'][-5:] for d in daily]
        counts = [d['count'] for d in daily]

        x = list(range(len(daily)))
        self.daily_bar.setOpts(x=x, height=counts)

        ticks = [list(zip(x, dates))]
        ax = self.daily_plot.getAxis('bottom')
        ax.setTicks(ticks)

        hours = self._db.get_hourly_distribution(7)
        self.hour_bar.setOpts(x=list(range(24)), height=hours)

        hour_ticks = [[(i, f"{i}:00") for i in range(0, 24, 3)]]
        self.hour_plot.getAxis('bottom').setTicks(hour_ticks)
