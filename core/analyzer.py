"""频谱分析器 - FFT 频带能量计算 + 楼上噪音检测

楼上典型噪音特征（通过楼板传导）:
  - 拖鞋/脚步: 30-120Hz 冲击，短促，周期性
  - 拖拽家具: 30-150Hz 持续低频 + 摩擦泛音
  - 物体掉落: 宽带冲击，但低频能量突出
  - 关门/撞击: 30-80Hz 极强冲击

核心策略（单麦克风）:
  1. 低频绝对能量超过底噪一定量 → 基本判据
  2. 低频占比高 → 辅助判据（排除自家全频段声音）
  3. 突发冲击检测 → 捕捉脚步/撞击
  4. 人在家时不关闭检测，而是提高阈值
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class AnalysisResult:
    """单帧分析结果"""
    rms_db: float           # 总 RMS (dB)
    low_energy: float       # 低频段能量 (线性)
    mid_energy: float       # 中频段能量
    high_energy: float      # 高频段能量
    low_db: float           # 低频 dB
    mid_db: float           # 中频 dB
    high_db: float          # 高频 dB
    ratio: float            # 低频 / (中频+高频) 比值
    is_impact: bool         # 是否突发冲击
    low_excess_db: float    # 低频超出底噪多少 dB
    spectral_centroid: float  # 频谱质心 (Hz) — 结构声<250, 人声>400
    harmonic_ratio: float     # 谐波比 0~1 — 人声>0.5, 结构声<0.3
    zcr: float                # 过零率 — 结构声<0.05, 人声>0.1
    crest_factor: float       # 波峰因子 — 冲击>6, 持续声<4
    spectrum: np.ndarray    # FFT 频谱 (用于绘图)
    freqs: np.ndarray       # 频率轴


class Analyzer:
    """频谱分析 + 楼上噪音检测"""

    def __init__(self, low_range=(20, 200), mid_range=(200, 2000),
                 high_range=(2000, 8000), silence_db=-55):
        self._low_range = low_range
        self._mid_range = mid_range
        self._high_range = high_range
        self._silence_db = silence_db
        self._prev_rms = 0.0
        self._prev_low_db = -100.0
        self._noise_floor_db = -65.0
        self._low_floor_db = -70.0    # 低频段底噪（校准时测定）

    def set_noise_floor(self, db):
        self._noise_floor_db = db

    @property
    def noise_floor_db(self):
        return self._noise_floor_db

    @property
    def low_floor_db(self):
        return self._low_floor_db

    def analyze(self, audio: np.ndarray, sample_rate: int) -> AnalysisResult:
        """分析一帧音频，返回 AnalysisResult"""
        n = len(audio)

        # RMS → dB
        rms = float(np.sqrt(np.mean(audio ** 2)))
        rms_db = 20 * np.log10(max(rms, 1e-10))

        # 加窗 FFT
        window = np.hanning(n)
        fft_vals = np.abs(np.fft.rfft(audio * window)) / n
        freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

        # 转 dB (用于绘图)
        spectrum_db = 20 * np.log10(np.maximum(fft_vals, 1e-10))

        # 频带能量
        low_e = self._band_energy(fft_vals, freqs, *self._low_range)
        mid_e = self._band_energy(fft_vals, freqs, *self._mid_range)
        high_e = self._band_energy(fft_vals, freqs, *self._high_range)

        low_db = 20 * np.log10(max(low_e, 1e-10))
        mid_db = 20 * np.log10(max(mid_e, 1e-10))
        high_db = 20 * np.log10(max(high_e, 1e-10))

        ratio = low_e / (mid_e + high_e + 1e-10)

        # 低频超出底噪多少 dB
        low_excess_db = low_db - self._low_floor_db

        # 冲击检测: 低频 dB 在一帧内跳升 > 6dB (更灵敏，针对脚步/撞击)
        low_jump = low_db - self._prev_low_db
        is_impact = low_jump > 6
        self._prev_rms = rms
        self._prev_low_db = low_db

        # ── 新增维度 ──
        # 1. 频谱质心: 加权平均频率，结构声低、人声高
        power = fft_vals ** 2
        total_power = np.sum(power) + 1e-20
        spectral_centroid = float(np.sum(freqs * power) / total_power)

        # 2. 谐波比: 检测是否存在等间距谐波梳齿（人声特征）
        harmonic_ratio = self._calc_harmonic_ratio(fft_vals, freqs, sample_rate)

        # 3. 过零率: 每采样点符号变化率
        signs = np.sign(audio)
        zcr = float(np.sum(np.abs(np.diff(signs)) > 0)) / max(n - 1, 1)

        # 4. 波峰因子: peak/rms, 冲击声高、持续声低
        peak = float(np.max(np.abs(audio)))
        crest_factor = peak / max(rms, 1e-10)

        return AnalysisResult(
            rms_db=rms_db,
            low_energy=low_e,
            mid_energy=mid_e,
            high_energy=high_e,
            low_db=low_db,
            mid_db=mid_db,
            high_db=high_db,
            ratio=ratio,
            is_impact=is_impact,
            low_excess_db=low_excess_db,
            spectral_centroid=spectral_centroid,
            harmonic_ratio=harmonic_ratio,
            zcr=zcr,
            crest_factor=crest_factor,
            spectrum=spectrum_db,
            freqs=freqs,
        )

    def calibrate(self, audio: np.ndarray, sample_rate: int):
        """用安静环境录音校准底噪，同时测定低频段底噪"""
        rms = float(np.sqrt(np.mean(audio ** 2)))
        self._noise_floor_db = 20 * np.log10(max(rms, 1e-10))
        self._silence_db = self._noise_floor_db + 6

        # 计算低频段底噪
        n = len(audio)
        window = np.hanning(n)
        fft_vals = np.abs(np.fft.rfft(audio * window)) / n
        freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
        low_e = self._band_energy(fft_vals, freqs, *self._low_range)
        self._low_floor_db = 20 * np.log10(max(low_e, 1e-10))

    @staticmethod
    def _band_energy(fft_vals, freqs, f_low, f_high):
        mask = (freqs >= f_low) & (freqs < f_high)
        if not np.any(mask):
            return 1e-20
        return float(np.sqrt(np.mean(fft_vals[mask] ** 2)))

    @staticmethod
    def _calc_harmonic_ratio(fft_vals, freqs, sr):
        """自相关法估计谐波比: 人声有明显基频→比值高, 噪声/冲击→低."""
        # 只看 80-4000Hz 范围
        mask = (freqs >= 80) & (freqs <= 4000)
        if np.sum(mask) < 10:
            return 0.0
        spec = fft_vals[mask]
        total_e = np.sum(spec ** 2)
        if total_e < 1e-20:
            return 0.0
        # 在频谱上做自相关找基频周期
        # 基频范围 80-400Hz → 对应 FFT bin 间距
        df = freqs[1] - freqs[0] if len(freqs) > 1 else 1.0
        min_lag = max(1, int(80 / max(df, 0.1)))   # 对应最高基频 ~400Hz
        max_lag = min(len(spec) // 2, int(400 / max(df, 0.1)))  # 对应最低基频 ~80Hz
        if min_lag >= max_lag or max_lag >= len(spec):
            return 0.0
        # 归一化自相关
        spec_norm = spec - np.mean(spec)
        ac0 = np.sum(spec_norm ** 2)
        if ac0 < 1e-20:
            return 0.0
        best = 0.0
        for lag in range(min_lag, max_lag):
            ac = np.sum(spec_norm[:len(spec_norm)-lag] * spec_norm[lag:])
            r = ac / ac0
            if r > best:
                best = r
        return float(max(0.0, min(1.0, best)))
