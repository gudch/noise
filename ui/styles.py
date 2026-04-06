"""统一样式 — web-app 风格"""

COLORS = {
    'bg': '#0f0f1a',
    'surface': '#1a1a2e',
    'card': '#222240',
    'card_border': '#2d2d50',
    'primary': '#6c5ce7',
    'primary_hover': '#7d6ef0',
    'danger': '#ff4757',
    'warning': '#ffa502',
    'success': '#2ed573',
    'text': '#f0f0f0',
    'text_secondary': '#a0a0c0',
    'text_dim': '#666680',
    'low_freq': '#ff4757',
    'mid_freq': '#3498db',
    'high_freq': '#2ecc71',
    'accent_glow': 'rgba(108,92,231,0.3)',
}

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0f0f1a;
    color: #f0f0f0;
    font-family: "Microsoft YaHei", sans-serif;
    font-size: 14px;
}
QTabWidget::pane {
    border: 1px solid #2d2d50;
    border-radius: 8px;
    background: #0f0f1a;
}
QTabBar::tab {
    background: #1a1a2e;
    color: #a0a0c0;
    padding: 14px 32px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    font-size: 16px;
    font-weight: bold;
}
QTabBar::tab:hover {
    background: #222240;
    color: #ddd;
}
QTabBar::tab:selected {
    background: #2d2d50;
    color: #fff;
}
QGroupBox {
    border: 1px solid #2d2d50;
    border-radius: 12px;
    margin-top: 16px;
    padding: 24px 16px 16px 16px;
    font-weight: bold;
    font-size: 15px;
    background: #1a1a2e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 20px;
    padding: 0 12px;
    color: #a0a0c0;
}
QPushButton {
    background-color: #6c5ce7;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 12px 28px;
    font-size: 15px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #7d6ef0;
}
QPushButton:pressed {
    background-color: #5a4ad5;
}
QPushButton:disabled {
    background-color: #333350;
    color: #666680;
}
QPushButton[class="danger"] {
    background-color: #ff4757;
}
QSlider::groove:horizontal {
    height: 8px;
    background: #2d2d50;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    width: 20px;
    height: 20px;
    margin: -6px 0;
    background: #6c5ce7;
    border-radius: 10px;
}
QSlider::handle:horizontal:hover {
    background: #7d6ef0;
}
QComboBox {
    background: #1a1a2e;
    border: 1px solid #2d2d50;
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 36px;
    font-size: 14px;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox QAbstractItemView {
    background: #1a1a2e;
    border: 1px solid #2d2d50;
    selection-background-color: #6c5ce7;
}
QTableWidget {
    background: #1a1a2e;
    gridline-color: #2d2d50;
    border: 1px solid #2d2d50;
    border-radius: 8px;
    font-size: 14px;
}
QTableWidget::item {
    padding: 8px;
}
QHeaderView::section {
    background: #222240;
    color: #a0a0c0;
    padding: 10px;
    border: none;
    font-weight: bold;
    font-size: 13px;
}
QScrollBar:vertical {
    width: 8px;
    background: transparent;
}
QScrollBar::handle:vertical {
    background: #444460;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar:horizontal {
    height: 8px;
    background: transparent;
}
QScrollBar::handle:horizontal {
    background: #444460;
    border-radius: 4px;
    min-width: 30px;
}
QScrollArea {
    border: none;
}
QSpinBox {
    background: #1a1a2e;
    border: 1px solid #2d2d50;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 30px;
}
QCheckBox {
    spacing: 10px;
    font-size: 14px;
}
QCheckBox::indicator {
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: 2px solid #2d2d50;
    background: #1a1a2e;
}
QCheckBox::indicator:checked {
    background: #6c5ce7;
    border-color: #6c5ce7;
}
QLabel#tip_label {
    color: #a0a0c0;
    font-size: 13px;
    padding: 8px 12px;
    background: #222240;
    border-radius: 8px;
    border: 1px solid #2d2d50;
}
QLabel#guide_banner {
    color: #ffa502;
    font-size: 15px;
    font-weight: bold;
    padding: 14px 18px;
    background: rgba(255, 165, 2, 0.08);
    border-radius: 10px;
    border: 1px solid rgba(255, 165, 2, 0.25);
}
QLabel#big_status {
    font-size: 28px;
    font-weight: bold;
}
"""
