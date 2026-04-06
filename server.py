"""NoiseGuard v4 — SM-24 检波器楼上噪音监测系统

设计哲学: 极简检测 + 与人耳对齐
- 不区分噪音类型（脚步/冲击/拖拽），只判断"有没有噪音"
- 超阈值即触发，1帧就够，不需要确认帧
- 无冷却时间、无报警静默期，始终检测
- 峰度仅用于排除电气干扰(EMI)，不用于分类

信号处理链:
1. 4阶 Butterworth 带通滤波 (5-250Hz)
2. 50Hz谐波陷波 (消除电源EMI)
3. 整体功率检测 (BW×T=5.6, 统计充分)
4. 峰度抗干扰 (kurtosis<3.5 + 低能量 = 干扰，忽略)
5. 百分位自适应基线 (30秒窗口第20百分位)
"""
import asyncio, json, time, os, wave, collections, threading, math, sys
import numpy as np
import sounddevice as sd

# 修复 Windows GBK 终端无法打印 Unicode 特殊字符 (如 ®) 导致崩溃
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
from scipy.signal import butter, sosfilt, sosfilt_zi, iirnotch, lfilter, lfilter_zi
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
import uvicorn
from core.config_manager import ConfigManager
from db.database import Database

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _wasapi_extra(dev_idx):
    """若设备属于 WASAPI host-api 则返回 exclusive 低延迟 settings, 否则 None"""
    try:
        info = sd.query_devices(dev_idx)
        api_name = sd.query_hostapis(info['hostapi'])['name']
        if 'WASAPI' in api_name:
            return sd.WasapiSettings(exclusive=True)
    except Exception:
        pass
    return None


def _find_test_device(dev_idx):
    """测试录音用: 若设备是 WASAPI，找 DirectSound/MME 等效设备以避免设备锁冲突。
    
    WASAPI 设备在引擎 stop() 后句柄释放慢，sd.rec() 会因 -9999 失败。
    DirectSound/MME 不存在此问题，用于测试录音最可靠。
    """
    try:
        info = sd.query_devices(dev_idx)
        api_name = sd.query_hostapis(info['hostapi'])['name']
        if 'WASAPI' not in api_name:
            return dev_idx  # 非 WASAPI, 直接用
        # 找同名设备的 DirectSound 或 MME 版本
        target_name = info['name']
        devices = sd.query_devices()
        best_idx, best_prio = dev_idx, 9
        prio_map = {'Windows DirectSound': 0, 'MME': 1}
        for i, d in enumerate(devices):
            if d['max_input_channels'] <= 0:
                continue
            a = sd.query_hostapis(d['hostapi'])['name']
            p = prio_map.get(a, 9)
            if p >= 9:
                continue
            # 前缀匹配 (MME 截断名称)
            short = min(d['name'], target_name, key=len)
            long = max(d['name'], target_name, key=len)
            if long.startswith(short) and p < best_prio:
                best_idx = i
                best_prio = p
        return best_idx
    except Exception:
        return dev_idx


# ═══════════════════════════════════════════════
#  设备管理 — WASAPI 优先，智能解析
# ═══════════════════════════════════════════════
def list_input_devices():
    """列出所有输入设备, WASAPI 排最前"""
    devices = sd.query_devices()
    result = []
    api_prio = {'Windows WASAPI': 0, 'Windows DirectSound': 1, 'MME': 2}
    for i, d in enumerate(devices):
        if d['max_input_channels'] <= 0:
            continue
        api = sd.query_hostapis(d['hostapi'])['name']
        lo = d['name'].lower()
        if any(k in lo for k in ['映射', 'mapper', '主声音', 'primary', '扬声器', 'speaker', 'output']):
            continue
        if 'WDM-KS' in api:
            continue
        result.append({'index': i, 'name': d['name'], 'host_api': api,
                       'channels': d['max_input_channels'],
                       'sample_rate': int(d['default_samplerate'])})
    result.sort(key=lambda x: api_prio.get(x['host_api'], 9))
    return result


def list_input_devices_dedup():
    """列出物理输入设备 (按设备名去重, 只保留最优API版本)
    
    同一物理设备在 Windows 里会出现3次 (WASAPI/DirectSound/MME)。
    优先保留 WASAPI 版本, 其次 DirectSound, 最后 MME。
    注意: MME截断到31字符, DirectSound也会截断, 所以用前缀匹配。
    """
    all_devs = list_input_devices()
    api_prio = {'Windows WASAPI': 0, 'Windows DirectSound': 1, 'MME': 2}
    groups = []  # list of (canonical_name, best_device)
    for d in all_devs:
        name = d['name']
        prio = api_prio.get(d['host_api'], 9)
        matched = False
        for i, (canon, best) in enumerate(groups):
            # 前缀匹配: 短名是长名的前缀 → 同一个物理设备
            short, long = (name, canon) if len(name) <= len(canon) else (canon, name)
            if long.startswith(short):
                best_prio = api_prio.get(best['host_api'], 9)
                if prio < best_prio:
                    # 更新为更好的API + 保留最长名称
                    groups[i] = (long, d)
                elif len(name) > len(canon):
                    groups[i] = (name, best)
                matched = True
                break
        if not matched:
            groups.append((name, d))
    result = [best for _, best in groups]
    result.sort(key=lambda x: api_prio.get(x['host_api'], 9))
    return result


def resolve_wasapi_device(name_hint=None, fallback_idx=None):
    """智能解析设备: 始终优先选择同名设备的 WASAPI 版本。
    
    解析顺序:
    1. 若有 name_hint, 找同名的 WASAPI 设备
    2. 若 fallback_idx 是 WASAPI 设备, 直接用
    3. 若 fallback_idx 是非-WASAPI, 找同名的 WASAPI 版本
    4. 默认: 选含 'Audio Device' 的 WASAPI (即 SM-24 所接的 3.5mm)
    5. 最后: 任意 WASAPI 输入设备
    """
    devs = list_input_devices()
    wasapi = [d for d in devs if 'WASAPI' in d['host_api']]
    
    # 按名称匹配 WASAPI
    if name_hint:
        for d in wasapi:
            if d['name'] == name_hint:
                return d['index'], d['name'], d['sample_rate']
    
    # 检查 fallback_idx
    if fallback_idx is not None and fallback_idx >= 0:
        for d in wasapi:
            if d['index'] == fallback_idx:
                return d['index'], d['name'], d['sample_rate']
        # fallback_idx 是非-WASAPI, 找同名 WASAPI
        for d_all in devs:
            if d_all['index'] == fallback_idx:
                for d in wasapi:
                    if d['name'] == d_all['name']:
                        return d['index'], d['name'], d['sample_rate']
                break
    
    # 默认: SM-24 接的 3.5mm = 'Audio Device'
    for d in wasapi:
        if 'audio device' in d['name'].lower():
            return d['index'], d['name'], d['sample_rate']
    
    # 任意 WASAPI
    if wasapi:
        d = wasapi[0]
        return d['index'], d['name'], d['sample_rate']
    
    # 无 WASAPI, 用第一个可用设备
    if devs:
        d = devs[0]
        return d['index'], d['name'], d['sample_rate']
    
    return None, None, 48000


# ═══════════════════════════════════════════════
#  SM-24 振动分析引擎 v2 — 频谱减除 + 陷波滤波
# ═══════════════════════════════════════════════
#
#  核心改进 (对比 v1):
#  1. 陷波滤波器: 消除 50Hz 电源干扰及谐波 (板载声卡 EMI 的根源)
#  2. 频谱噪声指纹: 校准时记录每频段底噪中位数 (不是单一 RMS)
#  3. 频谱减除检测: 逐频段减去底噪基线, 只有突变的能量才计入判定
#  4. STA/LTA 对去噪信号做: 不受稳态干扰影响
#  5. 自适应底噪只降不升: 防止真实噪音被吸收进底噪
#  → 彻底解决: 板载声卡 EMI 误报 + 微弱楼上走路漏检

# SM-24 物理参数
SM24_SENSITIVITY = 28.8   # V/(m/s)
SM24_F_NATURAL   = 10.0   # Hz
SM24_F_LOW       = 5.0    # Hz, 滤波下限
SM24_F_HIGH      = 250.0  # Hz, 滤波上限

# 检测频段 — 按振动物理特征划分
#   5-40Hz:  结构共振/重击/跑跳 (SM-24 最灵敏区, 楼板一阶模态 15-30Hz)
#   40-120Hz: 脚步/关门/家具碰撞
#   120-250Hz: 拖拽摩擦/刮擦
DETECT_BANDS = [(5, 40), (40, 120), (120, 250)]


def _build_bandpass(sr, low=SM24_F_LOW, high=SM24_F_HIGH, order=4):
    """4阶 Butterworth 带通滤波器 (SOS 格式, 数值稳定)"""
    nyq = sr / 2.0
    lo = max(low / nyq, 0.001)
    hi = min(high / nyq, 0.999)
    return butter(order, [lo, hi], btype='band', output='sos')


def _build_notches(sr, harmonics=(50, 100, 150, 200), Q=30):
    """构建 50Hz 及其谐波的陷波滤波器
    
    板载 Realtek 声卡通过主板走线拾取大量 50Hz 电源干扰 (EMI),
    这是清晨安静时误报的根本原因。陷波滤波器精确挖掉这些频率,
    对其他频率几乎无影响 (Q=30, 带宽仅 ~1.7Hz)。
    """
    filters = []
    for freq in harmonics:
        if freq < sr / 2 - 10:  # 远离 Nyquist
            b, a = iirnotch(freq, Q, sr)
            zi = lfilter_zi(b, a)
            filters.append([b, a, zi * 1e-10])
    return filters


class VibrationAnalyzer:
    """SM-24 检波器分析器 v2 — 频谱减除 + 陷波滤波
    
    处理链:
    raw PCM → 带通(5-250Hz) → 陷波(50Hz谐波) → 分频段FFT
    → 频谱减除(减去底噪指纹) → 干净超额能量 → STA/LTA → 分类判定
    
    校准时: 多帧 FFT + 中位数 → 鲁棒的频谱噪声指纹
    检测时: 逐频段减去指纹 → 只有真正突变的振动才触发
    → 稳态干扰 (EMI/声卡底噪/空调) 被自动消除
    → 微弱楼上走路信号从干扰中浮现
    """
    
    def __init__(self, sr=48000, block_size=1024):
        self.sr = sr
        self.block_size = block_size
        
        # ── 滤波器链 ──
        # 1. 带通: 只保留 5-250Hz (SM-24 有效范围)
        self._sos = _build_bandpass(sr)
        # [BUG修复] sosfilt_zi(sos) 返回的是 DC=1.0 的稳态初始条件
        # 实际信号幅度 ~0.001, 导致滤波器启动时内部状态高1000×
        # → 前10-15帧有巨大衰减瞬态 (40+dB excess)
        # 修复: 用零初始状态, 滤波器从零平滑上升到噪声水平, 无过冲
        self._zi = sosfilt_zi(self._sos) * 0.0
        # 2. 陷波: 精确消除 50Hz 电源干扰及谐波
        self._notches = _build_notches(sr)  # 已用 zi * 1e-10, OK
        
        # ── FFT 参数 ──
        # 4倍零填充: 1024→4096, 频率分辨率 48000/4096 ≈ 11.7Hz
        # 足够区分 15-30Hz 楼板共振 vs 50Hz 干扰
        self._fft_n = max(4096, block_size * 4)
        self._fft_freqs = np.fft.rfftfreq(self._fft_n, 1.0 / sr)
        self._fft_window = np.hanning(block_size)
        
        # 预计算频段掩码
        self._band_masks = []
        for (f_lo, f_hi) in DETECT_BANDS:
            mask = (self._fft_freqs >= f_lo) & (self._fft_freqs < f_hi)
            self._band_masks.append(mask)
        
        # ── 噪声频谱指纹 (校准时设定) ──
        # 最小底噪功率: 对应约 -100dBFS, 防止全零校准导致 >100dB excess
        # 现实中任何 ADC+前放 的量化噪声都不会低于此值
        self._min_noise_power = 1e-10
        self._noise_band_power = np.full(len(DETECT_BANDS), self._min_noise_power)
        self.noise_floor_db = -60.0   # 向后兼容
        self.calibrated = False
        
        # ── 自适应底噪 (逐频段, 只降不升) ──
        self._adapt_band_power = np.full(len(DETECT_BANDS), self._min_noise_power)
        self._adapt_inited = False
        
        # ── STA/LTA (对去噪能量做) ──
        self._sta_len = max(1, int(0.1 * sr / block_size))
        self._lta_len = max(10, int(5.0 * sr / block_size))
        self._sta_sum = 0.0
        self._lta_sum = 0.0
        self._sta_buf = collections.deque(maxlen=self._sta_len)
        self._lta_buf = collections.deque(maxlen=self._lta_len)
        
        # ── 整体功率跟踪 (显式初始化, 不用 hasattr) ──
        self._power_ema = 0.0
        self._adapt_overall_power = self._min_noise_power
        
        # ── V3: 百分位噪声追踪 ──
        # 最近30秒的功率值, 用第20百分位作为鲁棒噪声基线
        self._noise_pct_buf = collections.deque(maxlen=max(200, int(30.0 * sr / block_size)))
        
        # ── 滤波器预热 ──
        self._warm_frames = 0
    
    def set_sr(self, sr):
        """重新设置采样率, 重建所有滤波器"""
        saved_cal = self.calibrated
        saved_floor = self.noise_floor_db
        saved_band = self._noise_band_power.copy() if self.calibrated else None
        
        self.__init__(sr, self.block_size)
        
        # 恢复校准数据 (采样率变了但频段不变, 功率仍有效)
        if saved_cal and saved_band is not None:
            self.calibrated = True
            self.noise_floor_db = saved_floor
            self._noise_band_power = saved_band
            self._adapt_band_power = saved_band.copy()
            self._adapt_inited = True
            # 恢复整体功率基线 (从 noise_floor_db 反算)
            self._adapt_overall_power = max(10 ** (saved_floor / 10), self._min_noise_power)
    
    def analyze(self, raw_audio):
        """分析一帧检波器数据 — 整体功率检测 + 频段分类
        
        [实测决策] 195个真实录音分析后的架构:
        - 检测: 用整体滤波后功率 (带通245Hz × 23ms = BW×T=5.6, 统计充分)
        - 分类: 用FFT频段比例 (仅在确认事件后使用, 不做检测判定)
        - 陷波: 50Hz谐波去除 (实测突出度6-9dB, 有效但非决定性)
        
        [为什么不用逐频段检测]
        1024样本@44100Hz=23ms, 频率分辨率43Hz
        5-40Hz频段仅3个FFT bin → 功率估计方差 > 100% → 误报不可消除
        整体功率有1024个时域样本 → 方差 ~25% → 过减因子轻松解决
        """
        n = len(raw_audio)
        
        # ── 1. 带通滤波 5-250Hz ──
        filtered, self._zi = sosfilt(self._sos, raw_audio, zi=self._zi)
        
        # ── 2. 陷波滤波: 消除 50/100/150/200Hz 电源干扰 ──
        audio = filtered.copy()
        for entry in self._notches:
            audio, entry[2] = lfilter(entry[0], entry[1], audio, zi=entry[2])
        
        # [BUG修复] 始终用滤波后音频. zi*0.0 保证输出从零平滑上升, 无过冲
        # 前~15帧功率低于基线 → excess=0 (自然无误报)
        
        # ── 3. 基础指标 ──
        rms = float(np.sqrt(np.mean(audio ** 2)))
        rms_db = 20 * math.log10(max(rms, 1e-10))
        peak = float(np.max(np.abs(audio)))
        crest = peak / max(rms, 1e-10)
        raw_rms = float(np.sqrt(np.mean(raw_audio ** 2)))
        raw_rms_db = 20 * math.log10(max(raw_rms, 1e-10))
        velocity_um = (rms / SM24_SENSITIVITY) * 1e6
        
        # ── 3.5 V3: 峰度(Kurtosis) — 区分冲击 vs 平滑干扰 ──
        # 真实物理冲击(跺脚/掉东西): kurt > 6 (信号有尖锐脉冲)
        # EMI/触摸板电容扫描:       kurt ≈ 1.5-3 (类正弦平滑信号)
        # 高斯底噪:                  kurt ≈ 3
        if rms > 1e-10:
            kurt = float(np.mean((audio / rms) ** 4))
        else:
            kurt = 3.0
        
        # ── 4. 整体功率检测 (核心!) ──
        # [实测依据] 整体RMS²有1024个样本, BW×T≈5.6, 统计可靠
        # 不再用逐频段FFT做检测 (3个bin方差太大, 误报不可消除)
        overall_power = float(np.mean(audio ** 2))
        
        # EMA平滑 (alpha=0.15, 等效~7帧≈160ms)
        # [实测] 真实走路信号持续>200ms, 160ms平滑不影响检测
        # 冲击via瞬态路径处理, 不依赖EMA
        self._power_ema = self._power_ema * 0.85 + overall_power * 0.15
        
        # 噪声基线: 校准值 or 自适应值 (取较大者, 更保守)
        noise_power = max(10 ** (self.noise_floor_db / 10), self._min_noise_power)
        if self.calibrated:
            noise_power = max(noise_power, self._adapt_overall_power)
        else:
            noise_power = self._adapt_overall_power
        
        # 双路径检测:
        # 路径1 — 持续 (走路/拖拽): 平滑功率 vs 2×噪声基线
        # [数学] BW×T=5.6 → std(power)/mean = 1/sqrt(2×5.6) = 0.30
        #   EMA(0.15)再降~2.5× → 最终std/mean ≈ 0.12
        #   过减2× → 需power>2×mean → z=(2-1)/0.12 = 8.3σ → 概率≈0
        excess_sustained = max(0.0, self._power_ema - noise_power * 2.0)
        
        # 路径2 — 瞬态 (冲击/跺脚): 原始功率 vs 4×噪声
        # [数学] 未平滑: std/mean ≈ 0.30, 过减4× → z=(4-1)/0.30 = 10σ → 概率≈0
        # [实测] 真实冲击 >30dB (1000×noise), 4× 阈值无影响
        excess_transient = max(0.0, overall_power - noise_power * 4.0)
        
        total_excess = max(excess_sustained, excess_transient)
        
        # excess_db: 信噪比 (dB)
        if total_excess > 0:
            clean_excess_db = 10 * math.log10(1 + total_excess / max(noise_power, 1e-20))
        else:
            clean_excess_db = 0.0
        
        # ── 5. STA/LTA (对整体功率做) ──
        energy = total_excess + 1e-20
        if len(self._sta_buf) == self._sta_len:
            self._sta_sum -= self._sta_buf[0]
        self._sta_buf.append(energy)
        self._sta_sum += energy
        sta = self._sta_sum / len(self._sta_buf)
        
        if len(self._lta_buf) == self._lta_len:
            self._lta_sum -= self._lta_buf[0]
        self._lta_buf.append(energy)
        self._lta_sum += energy
        lta = self._lta_sum / len(self._lta_buf)
        
        sta_lta = sta / max(lta, 1e-20)
        
        # ── 6. FFT频段分析 (仅用于分类, 不做检测) ──
        win = self._fft_window if n == self.block_size else np.hanning(n)
        padded = np.zeros(self._fft_n)
        padded[:n] = audio * win
        fft_mag = np.abs(np.fft.rfft(padded)) / n
        
        band_power = np.zeros(len(DETECT_BANDS))
        for j, mask in enumerate(self._band_masks):
            if np.any(mask):
                band_power[j] = float(np.mean(fft_mag[mask] ** 2))
        
        e_sub = band_power[0]   # 5-40Hz: 结构共振/重击
        e_low = band_power[1]   # 40-120Hz: 脚步/碰撞
        e_mid = band_power[2]   # 120-250Hz: 拖拽/摩擦
        total_band = e_sub + e_low + e_mid + 1e-20
        sub_ratio = e_sub / total_band
        low_ratio = e_low / total_band
        mid_ratio = e_mid / total_band
        sub_db = 10 * math.log10(max(e_sub, 1e-20))
        low_db = 10 * math.log10(max(e_low, 1e-20))
        mid_db = 10 * math.log10(max(e_mid, 1e-20))
        
        # ── 7. V4: 删除了冲击检测(is_impact)和帧间跳变(jump_db) ──
        # 不再需要区分冲击类型，classify_vibration只做二分类
        
        # ── 8. V4: 删除了步态周期性检测 ──
        # 用户不需要分类，步态检测已移除
        
        # ── 9. V3: 自适应底噪 (百分位追踪 + 受控双向更新) ──
        # V2问题: 非对称EMA只降不升, 长期运行后基线系统性偏低 → 误报
        # V3方案: 用最近30秒功率的第20百分位作为参考, 双向追踪
        self._noise_pct_buf.append(overall_power)
        if sta_lta < 1.3 and clean_excess_db < 1.0:
            # 安静帧: 更新基线
            if len(self._noise_pct_buf) >= 50:
                sorted_buf = sorted(self._noise_pct_buf)
                pct_idx = max(0, int(len(sorted_buf) * 0.2))
                pct_noise = sorted_buf[pct_idx]
                if pct_noise < self._adapt_overall_power:
                    alpha = 0.02    # 下降较快 (~2.3s时间常数)
                else:
                    alpha = 0.005   # 上升较慢 (~9.2s时间常数), 但允许上升
                self._adapt_overall_power = (
                    self._adapt_overall_power * (1 - alpha) + pct_noise * alpha)
            else:
                # 样本不足时用保守EMA
                if overall_power < self._adapt_overall_power:
                    alpha = 0.01
                else:
                    alpha = 0.002   # V3: 0.002 (V2是0.001), 允许略微上升
                self._adapt_overall_power = (
                    self._adapt_overall_power * (1 - alpha) + overall_power * alpha)
        
        # ── 10. 频谱数据 (前端图表) ──
        plot_mask = (self._fft_freqs >= 5) & (self._fft_freqs <= 300)
        spec_f = self._fft_freqs[plot_mask].tolist()
        spec_db = (20 * np.log10(np.maximum(fft_mag[plot_mask], 1e-10))).tolist()
        
        # 向后兼容字段
        adapt_db = 10 * math.log10(max(getattr(self, '_adapt_overall_power', noise_power), 1e-20))
        effective_floor = max(self.noise_floor_db, adapt_db) if self.calibrated else adapt_db
        
        return {
            'rms_db': round(rms_db, 1),
            'raw_rms_db': round(raw_rms_db, 1),
            'peak': round(peak, 6),
            'crest': round(crest, 1),
            'velocity_um': round(velocity_um, 2),
            'sta_lta': round(sta_lta, 2),
            'excess_db': round(clean_excess_db, 1),
            'effective_floor_db': round(effective_floor, 1),
            'adaptive_floor_db': round(adapt_db, 1),
            'sub_db': round(sub_db, 1), 'low_db': round(low_db, 1), 'mid_db': round(mid_db, 1),
            'sub_ratio': round(sub_ratio, 2), 'low_ratio': round(low_ratio, 2), 'mid_ratio': round(mid_ratio, 2),
            'kurtosis': round(kurt, 1),
            'spec_f': [round(f, 0) for f in spec_f],
            'spec_db': [round(d, 1) for d in spec_db],
        }
    
    def calibrate(self, audio):
        """频谱指纹校准 — 记录每个频段的底噪基线
        
        方法:
        1. 带通 + 陷波滤波 (与实时处理一致)
        2. 分帧 FFT, 每帧计算各频段功率
        3. 取中位数 (自动去掉异常高/低的帧, 比均值鲁棒)
        4. 对持续高能量 + 低方差的频段加安全余量 (可能是 EMI)
        
        → 建立频谱噪声指纹
        → 检测时逐频段减除, 只留真正的振动信号
        """
        # 带通 + 陷波 (与实时链一致)
        sos = _build_bandpass(self.sr)
        filtered = sosfilt(sos, audio)
        for freq in [50, 100, 150, 200]:
            if freq < self.sr / 2 - 10:
                b, a = iirnotch(freq, 30, self.sr)
                filtered = lfilter(b, a, filtered)
        
        # 取后半段 (滤波器稳定后)
        half = len(filtered) // 2
        if half > 0:
            filtered = filtered[half:]
        
        # 分帧 (与实时处理相同帧长)
        frame_n = self.block_size
        n_frames = len(filtered) // frame_n
        if n_frames < 3:
            rms = float(np.sqrt(np.mean(filtered ** 2)))
            self.noise_floor_db = 20 * math.log10(max(rms, 1e-10))
            min_power = max(rms**2 / len(DETECT_BANDS), self._min_noise_power)
            self._noise_band_power = np.full(len(DETECT_BANDS), min_power)
            self._adapt_band_power = self._noise_band_power.copy()
            self._adapt_inited = True
            self.calibrated = True
            return self.noise_floor_db
        
        # 逐帧 FFT → 每频段功率
        band_powers = np.zeros((n_frames, len(DETECT_BANDS)))
        window = np.hanning(frame_n)
        for i in range(n_frames):
            frame = filtered[i*frame_n:(i+1)*frame_n]
            padded = np.zeros(self._fft_n)
            padded[:frame_n] = frame * window
            fft_mag = np.abs(np.fft.rfft(padded)) / frame_n
            for j, mask in enumerate(self._band_masks):
                if np.any(mask):
                    band_powers[i, j] = float(np.mean(fft_mag[mask] ** 2))
        
        # 中位数: 自动去掉异常帧 (你说的"去头去尾"的鲁棒版本)
        self._noise_band_power = np.median(band_powers, axis=0)
        
        # [实测依据] 很多录音的前置缓冲区是全零 (-200dB)
        # 如果校准数据含大量零帧, 中位数会极小, 导致任何信号都 >100dB excess
        # 钳位到最小底噪功率 (约 -100dBFS, 任何真实 ADC 的量化噪声都不会低于此)
        self._noise_band_power = np.maximum(self._noise_band_power, self._min_noise_power)
        
        # 对持续稳定高能量的频段加 50% 安全余量 (疑似稳态干扰)
        # [实测] noise_ 录音中 200Hz/172Hz 有稳定峰值 (+6-9dB), 属于建筑结构共振
        for j in range(len(DETECT_BANDS)):
            col = band_powers[:, j]
            mean_p = float(np.mean(col))
            std_p = float(np.std(col))
            cv = std_p / (mean_p + 1e-20)
            median_all = float(np.median(self._noise_band_power))
            # 低变异系数 + 高能量 = 稳定干扰源
            if cv < 0.3 and mean_p > median_all * 3:
                self._noise_band_power[j] *= 1.5
        
        # 整体 RMS (向后兼容)
        rms = float(np.sqrt(np.mean(filtered ** 2)))
        self.noise_floor_db = 20 * math.log10(max(rms, 1e-10))
        
        # 初始化自适应底噪
        self._adapt_band_power = self._noise_band_power.copy()
        self._adapt_inited = True
        
        self.calibrated = True
        
        # 打印校准报告
        print(f'[CAL] 频谱指纹校准完成:')
        for j, (f_lo, f_hi) in enumerate(DETECT_BANDS):
            db = 10 * math.log10(max(self._noise_band_power[j], 1e-20))
            print(f'  [{f_lo:3d}-{f_hi:3d}Hz] noise={db:.1f}dB')
        print(f'  overall floor={self.noise_floor_db:.1f}dB')
        
        return self.noise_floor_db


# ═══════════════════════════════════════════════
#  振动分类器 v2 — 基于频谱减除后的干净信号
# ═══════════════════════════════════════════════
def classify_vibration(a, sensitivity_db):
    """V4 振动判定 — 极简二分类: silent / noise
    
    设计哲学: 不区分类型，只判断"有没有噪音"
    - 超过灵敏度阈值 → 噪音
    - 低峰度 + 低能量 → 电气干扰，忽略
    - 其他 → 安静
    """
    excess = a['excess_db']
    kurt = a.get('kurtosis', 3.0)
    
    if excess < sensitivity_db:
        return 'silent', '安静'
    
    # 抗干扰: 低峰度(<3.5) + 不太强的信号 → 大概率是EMI/触摸板
    # 真实物理振动在超阈值时峰度几乎不可能<3.5
    # 但如果能量特别强(>2倍阈值)，即使低峰度也放行（安全阀）
    if kurt < 3.5 and excess < sensitivity_db * 2:
        return 'silent', '安静'
    
    return 'noise', '检测到噪音'


# ═══════════════════════════════════════════════
#  音频引擎 (检波器核心 — WASAPI 独占 + 带通滤波)
# ═══════════════════════════════════════════════
class Engine:

    def __init__(self, cfg: ConfigManager, db: Database):
        self.config = cfg
        self.db = db
        self.monitoring = False
        
        dev = cfg.device
        det = cfg.detection
        
        # 设备解析: 有明确配置就用配置, 没有才自动查找 WASAPI
        saved_idx = dev.get('index', -1)
        saved_name = dev.get('name')
        if saved_idx >= 0:
            # 用户已选过设备, 直接使用
            self._dev_idx = saved_idx
            self._dev_name = saved_name
            self._sr = dev.get('sample_rate', 48000)
        else:
            # 首次运行, 自动查找 WASAPI 设备
            idx, name, sr = resolve_wasapi_device(saved_name, saved_idx)
            self._dev_idx = idx
            self._dev_name = name
            self._sr = sr or dev.get('sample_rate', 48000)
        self._blk = dev.get('block_size', 1024)
        self._stream = None
        
        self.analyzer = VibrationAnalyzer(self._sr, self._blk)
        
        # 检测参数
        self._sensitivity_db = det.get('sensitivity_db', 6)  # 超出底噪多少dB才报警
        
        # 校准恢复 (含频谱指纹)
        cal = cfg.calibration
        if cal.get('calibrated'):
            floor = cal.get('noise_floor_db')
            if floor is None or not isinstance(floor, (int, float)):
                print('[ENGINE] ⚠ 校准数据损坏 (noise_floor_db缺失), 需要重新校准')
            else:
                self.analyzer.noise_floor_db = float(floor)
                self.analyzer.calibrated = True
                # 恢复整体功率基线
                self.analyzer._adapt_overall_power = max(
                    10 ** (float(floor) / 10), self.analyzer._min_noise_power)
                # 恢复频谱噪声指纹
                band_power = cal.get('noise_band_power')
                if band_power and isinstance(band_power, list) and len(band_power) == len(DETECT_BANDS):
                    self.analyzer._noise_band_power = np.array(band_power, dtype=float)
                    self.analyzer._adapt_band_power = np.array(band_power, dtype=float)
                    self.analyzer._adapt_inited = True
                else:
                    print('[ENGINE] ⚠ noise_band_power 缺失或格式错误, 需要重新校准')
                    self.analyzer.calibrated = False
        
        # V4 状态机
        self._state = 'silent'
        self._quiet_count = 0
        self._ev_start = 0
        self._ev_peak_db = -100
        
        # 校准
        self._calibrating = False
        self._cal_frames = []
        self._cal_result = None
        self._cal_remaining = 0
        self._cal_start = 0
        
        # 录音
        rec = cfg.recording
        self._rec_on = rec.get('enabled', True)
        self._rec_dir = os.path.join(BASE_DIR, rec.get('output_dir', 'recordings'))
        os.makedirs(self._rec_dir, exist_ok=True)
        ring_sz = int(self._sr * 3 / self._blk) + 2
        self._ring = collections.deque(maxlen=ring_sz)
        self._rec_active = False
        self._rec_frames = []
        self._rec_post = 0
        self._rec_post_max = int(3 * self._sr / self._blk) + 1
        self._rec_fn = None
        
        # 波形缓冲
        self._wave_buf = np.zeros(self._sr * 3)
        
        # 室内麦克风 (多设备声源过滤)
        # V4: 支持多个麦克风同时监测室内声音
        # 除检波器外的所有输入设备均可用于室内声源过滤
        mic_cfg = cfg.get('mic') or {}
        self._mic_enabled = mic_cfg.get('enabled', False)
        self._mic_threshold_db = mic_cfg.get('threshold_db', -40)
        
        # 多麦克风: mic.devices = [idx1, idx2, ...]
        # 兼容旧配置: mic.index (单个)
        mic_devs = mic_cfg.get('devices', [])
        old_idx = mic_cfg.get('index', -1)
        if not mic_devs and old_idx >= 0:
            mic_devs = [old_idx]
        self._mic_devices = [d for d in mic_devs if d != self._dev_idx and d >= 0]
        
        self._mic_streams = []         # [(stream, dev_idx), ...]
        self._mic_data = {}            # {dev_idx: {rms_db, spike, active, baseline_db}}
        self._mic_lock = threading.Lock()
        self._mic_rms_db = -100.0      # 兼容: 所有麦克风中最高的 rms_db
        self._mic_active = False       # 兼容: 任一麦克风 active
        self._mic_spike = False        # 兼容: 任一麦克风 spike
        self._mic_baseline_db = -100.0 # 兼容: 取最高基线
        
        # 生效时段
        sched = cfg.get('schedule') or {}
        self._sched_enabled = sched.get('enabled', False)
        self._sched_start = sched.get('start_time', '22:00')
        self._sched_end = sched.get('end_time', '08:00')
        
        # 线程安全
        self._latest = None
        self._lock = threading.Lock()
        self._notifs = []
        self._nlock = threading.Lock()
        
        # 统计缓存
        self._st_cache = {'count': 0, 'duration': 0.0, 'last': ''}
        self._st_time = 0
        
        # 清理旧录音
        self._cleanup(rec.get('max_keep_days', 30))
        
        print(f'[ENGINE] 初始化完成: dev=[{self._dev_idx}] {self._dev_name}, sr={self._sr}')
    
    def start(self):
        if self.monitoring:
            return None
        try:
            # 使用已存储的设备, 不重新解析
            if self._dev_idx is not None:
                info = sd.query_devices(self._dev_idx)
            else:
                info = sd.query_devices(kind='input')
            sr = int(info['default_samplerate'])
            self._sr = sr
            self.analyzer.set_sr(sr)  # 重建滤波器 + STA/LTA 缓冲区
            self._wave_buf = np.zeros(sr * 3)
            ring_sz = int(sr * 3 / self._blk) + 2
            self._ring = collections.deque(maxlen=ring_sz)
            self._rec_post_max = int(3 * sr / self._blk) + 1
            extra = _wasapi_extra(self._dev_idx)
            api_tag = 'shared'
            try:
                self._stream = sd.InputStream(
                    device=self._dev_idx, samplerate=sr, channels=1,
                    blocksize=self._blk, dtype='float32', callback=self._cb,
                    latency='low', extra_settings=extra)
                self._stream.start()
                if extra:
                    api_tag = 'WASAPI-EX'
            except Exception:
                print('[ENGINE] WASAPI exclusive 失败, 回退共享模式')
                self._stream = sd.InputStream(
                    device=self._dev_idx, samplerate=sr, channels=1,
                    blocksize=self._blk, dtype='float32', callback=self._cb,
                    latency='low')
                self._stream.start()
                api_tag = 'shared-fallback'
            self.monitoring = True
            api_name = sd.query_hostapis(info['hostapi'])['name']
            print(f'[ENGINE] 检波器已启动: [{self._dev_idx}] {self._dev_name} ({api_name}) sr={sr} {api_tag}')
            self._start_mic()
            return None
        except Exception as e:
            return str(e)
    
    def _start_mic(self):
        """启动所有室内麦克风流（多设备并行）"""
        self._stop_mic()
        if not self._mic_enabled or not self._mic_devices:
            return
        for dev_idx in self._mic_devices:
            if dev_idx == self._dev_idx:
                print(f'[MIC] ⚠ 设备{dev_idx}与检波器相同, 跳过')
                continue
            try:
                info = sd.query_devices(dev_idx)
                if info['max_input_channels'] <= 0:
                    print(f'[MIC] ⚠ 设备{dev_idx}不是输入设备, 跳过')
                    continue
                sr = int(info['default_samplerate'])
                with self._mic_lock:
                    self._mic_data[dev_idx] = {
                        'rms_db': -100.0, 'spike': False, 'active': False,
                        'baseline_db': -100.0, 'name': info['name']
                    }
                mic_extra = _wasapi_extra(dev_idx)
                def make_cb(didx):
                    return lambda indata, frames, time_info, status: self._mic_cb(indata, didx)
                try:
                    stream = sd.InputStream(
                        device=dev_idx, samplerate=sr, channels=1,
                        blocksize=self._blk, dtype='float32', callback=make_cb(dev_idx),
                        latency='low', extra_settings=mic_extra)
                    stream.start()
                except Exception:
                    # WASAPI exclusive 失败, 回退共享模式
                    stream = sd.InputStream(
                        device=dev_idx, samplerate=sr, channels=1,
                        blocksize=self._blk, dtype='float32', callback=make_cb(dev_idx),
                        latency='low')
                    stream.start()
                self._mic_streams.append((stream, dev_idx))
                print(f'[MIC] 室内麦已启动: [{dev_idx}] {info["name"]}, sr={sr}')
            except Exception as e:
                print(f'[MIC] 设备{dev_idx}启动失败: {e}')
        if not self._mic_streams:
            print('[MIC] ⚠ 没有成功启动任何室内麦克风')
    
    def _stop_mic(self):
        for stream, _ in self._mic_streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._mic_streams = []
        with self._mic_lock:
            self._mic_data.clear()
    
    def _mic_cb(self, indata, dev_idx):
        """多麦克风回调 - 检测室内声音突变"""
        try:
            audio = indata[:, 0]
            rms = float(np.sqrt(np.mean(audio ** 2)))
            db = round(20 * math.log10(max(rms, 1e-10)), 1)
            
            with self._mic_lock:
                d = self._mic_data.get(dev_idx)
                if d is None:
                    return
                if d['baseline_db'] < -90:
                    d['baseline_db'] = db
                else:
                    alpha = 0.008 if db > d['baseline_db'] else 0.05
                    d['baseline_db'] = d['baseline_db'] * (1 - alpha) + db * alpha
                
                d['rms_db'] = db
                d['spike'] = (db - d['baseline_db']) > 6
                d['active'] = db > self._mic_threshold_db
                
                all_d = list(self._mic_data.values())
                self._mic_rms_db = max(x['rms_db'] for x in all_d)
                self._mic_spike = any(x['spike'] for x in all_d)
                self._mic_active = any(x['active'] for x in all_d)
                self._mic_baseline_db = max(x['baseline_db'] for x in all_d)
        except Exception:
            pass
    
    def stop(self):
        self._stop_mic()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.monitoring = False
        self._state = 'silent'
        self._quiet_count = 0
        self._calibrating = False
        # 保存正在进行的录音 (防止 stop 时丢失已录内容)
        if self._rec_active and self._rec_frames and self._rec_fn:
            threading.Thread(target=self._write_wav,
                             args=(self._rec_frames[:], self._rec_fn),
                             daemon=True).start()
        self._rec_active = False
        self._rec_frames = []
        self._rec_post = 0
        self._rec_fn = None
        with self._lock:
            self._latest = None
        self._mic_active = False
        self._mic_rms_db = -100.0
        self._mic_baseline_db = -100.0
        self._mic_spike = False
    
    def _push(self, t, d):
        with self._nlock:
            self._notifs.append({'type': t, 'data': d})
    
    def _cb(self, indata, frames, time_info, status):
        """检波器数据回调 — 核心处理链"""
        try:
            audio = indata[:, 0].copy()
            self._ring.append(audio)
            
            # 录音收集
            if self._rec_active:
                self._rec_frames.append(audio)
                if self._rec_post > 0:
                    self._rec_post -= 1
                    if self._rec_post <= 0:
                        self._save_rec()
            
            # 振动分析
            a = self.analyzer.analyze(audio)
            
            # 波形缓冲
            n = len(audio)
            self._wave_buf = np.roll(self._wave_buf, -n)
            self._wave_buf[-n:] = audio
            
            now = time.time()
            
            # ── 校准模式: 暂停识别 ──
            if self._calibrating:
                self._cal_frames.append(audio)
                elapsed = len(self._cal_frames) * n / self._sr
                cal_dur = self.config.calibration.get('duration_seconds', 5)
                if time.time() - self._cal_start > cal_dur + 10:
                    self._calibrating = False
                    self._cal_result = {'status': 'error', 'message': '校准超时'}
                elif elapsed >= cal_dur:
                    self._finish_cal()
                else:
                    self._cal_remaining = round(max(0, cal_dur - elapsed), 1)
                cls, cls_label = 'silent', '校准中'
                state = 'calibrating'
            
            # ── 正常检测 (V4: 删除报警静默期，始终检测) ──
            else:
                # 时段检查
                in_schedule = True
                if self._sched_enabled:
                    now_hm = time.strftime('%H:%M')
                    s, e = self._sched_start, self._sched_end
                    if s <= e:
                        in_schedule = s <= now_hm <= e
                    else:
                        in_schedule = now_hm >= s or now_hm <= e
                
                # 分类振动 (V4: 只有 silent / noise)
                cls, cls_label = classify_vibration(a, self._sensitivity_db)
                
                # 会议麦辅助: 室内突发声音 + 同时有振动 → 可能自己碰了天花板
                mic_filtered = False
                if self._mic_enabled and cls != 'silent':
                    with self._mic_lock:
                        mic_spike_now = self._mic_spike
                    if mic_spike_now:
                        mic_filtered = True
                        cls_label = cls_label + ' (自家活动)'
                
                # 时段外不报警
                if not in_schedule and cls != 'silent':
                    cls, cls_label = 'silent', '非监控时段'
                    mic_filtered = True
                
                tick_cls = 'silent' if mic_filtered else cls
                self._tick(a, tick_cls)
                state = self._state
            
            # 构建帧数据
            step = max(1, len(self._wave_buf) // 800)
            wf = self._wave_buf[::step].tolist()
            
            with self._lock:
                self._latest = {
                    **a,
                    'cls': cls, 'cls_label': cls_label, 'state': state,
                    'sensitivity_db': self._sensitivity_db,
                    'noise_floor_db': round(self.analyzer.noise_floor_db, 1),
                    'waveform': wf,
                    'cal_active': self._calibrating,
                    'cal_remaining': self._cal_remaining,
                    'cal_result': self._cal_result,
                    'mic_enabled': self._mic_enabled,
                    'mic_rms_db': self._mic_rms_db,
                    'mic_active': self._mic_active,
                    'mic_spike': self._mic_spike,
                    'mic_baseline_db': round(self._mic_baseline_db, 1) if self._mic_baseline_db > -95 else -100.0,
                    'mic_threshold_db': self._mic_threshold_db,
                    'mic_devices_status': {str(k): {'rms_db': v['rms_db'], 'spike': v['spike'], 'name': v.get('name', '')} for k, v in self._mic_data.items()} if self._mic_data else {},
                }
        except Exception as e:
            import traceback
            print(f'[CB ERROR] {e}')
            traceback.print_exc()
    
    def _tick(self, a, cls):
        """V4 状态机: silent ↔ noise（极简两态）
        
        - silent: 没噪音。收到noise帧 → 立即切换到noise并报警
        - noise: 有噪音。连续quiet_frames帧安静 → 切换回silent，记录事件
        
        不再有confirm_frames、cooldown、静默期。信号超阈值就触发，1帧就够。
        """
        now = time.time()
        is_noise = cls != 'silent'
        
        if self._state == 'silent':
            if is_noise:
                self._enter_noise(a, now)
        elif self._state == 'noise':
            if is_noise:
                # 持续噪音中，更新峰值
                if a['rms_db'] > self._ev_peak_db:
                    self._ev_peak_db = a['rms_db']
                self._quiet_count = 0
            else:
                # 安静帧，累计计数
                self._quiet_count += 1
                # 约0.5秒的安静确认事件结束（~22帧@44100/1024）
                quiet_threshold = max(5, int(0.5 * self._sr / self._blk))
                if self._quiet_count >= quiet_threshold:
                    self._state = 'silent'
                    # 记录事件到数据库
                    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime(self._ev_start))
                    rec_path = f'vib_{ts}.wav' if self._rec_active else None
                    self._rec_fn = rec_path
                    if self._rec_active:
                        self._rec_post = self._rec_post_max
                    self.db.insert_event(
                        start_time=self._ev_start, end_time=now,
                        peak_db=self._ev_peak_db, peak_ratio=0,
                        source='noise', recording_path=rec_path)
                    self._push('event_ended', {
                        'duration': round(now - self._ev_start, 1),
                        'peak_db': round(self._ev_peak_db, 1),
                        'source': 'noise'})
    
    def _enter_noise(self, a, now):
        """进入 noise 状态: 触发报警通知 + 开始录音"""
        self._state = 'noise'
        self._ev_start = now
        self._ev_peak_db = a['rms_db']
        self._quiet_count = 0
        # 通知前端（前端自行控制报警音播放间隔）
        self._push('event_started', {'cls': 'noise'})
        # 开始录音
        if self._rec_on:
            self._rec_active = True
            self._rec_frames = list(self._ring)
            self._rec_post = 0
    
    def _save_rec(self):
        frames, fn = self._rec_frames[:], self._rec_fn
        self._rec_frames = []
        self._rec_active = False
        self._rec_post = 0
        if not frames or not fn:
            return
        threading.Thread(target=self._write_wav, args=(frames, fn), daemon=True).start()
    
    def _write_wav(self, frames, fn):
        audio = np.concatenate(frames)
        peak = float(np.max(np.abs(audio)))
        # 仅防止削波, 不做增益放大 — 保持原始信号清晰度
        if peak > 0.95:
            audio = audio * (0.95 / peak)
        path = os.path.join(self._rec_dir, fn)
        try:
            with wave.open(path, 'w') as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(self._sr)
                pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
                wf.writeframes(pcm.tobytes())
            print(f'[REC] {fn} saved, {len(audio)/self._sr:.1f}s, peak={peak:.4f}')
        except Exception as e:
            print(f'[REC] error: {e}')
    
    def _finish_cal(self):
        self._calibrating = False
        all_audio = np.concatenate(self._cal_frames)
        floor = self.analyzer.calibrate(all_audio)
        self.config.set('calibration', 'noise_floor_db', floor)
        self.config.set('calibration', 'calibrated', True)
        # 存储频谱噪声指纹 (每频段底噪功率)
        self.config.set('calibration', 'noise_band_power',
                        self.analyzer._noise_band_power.tolist())
        self.config.save()
        
        # V3: 校准结果验证
        warnings = []
        if floor < -80:
            warnings.append(f'底噪极低({floor:.0f}dB), 请确认检波器已正确连接到声卡输入')
        if floor > -30:
            warnings.append(f'底噪偏高({floor:.0f}dB), 请检查是否有持续干扰或增益过高')
        band_pw = self.analyzer._noise_band_power
        if all(p <= self.analyzer._min_noise_power * 10 for p in band_pw):
            warnings.append('所有频段功率接近最小值, 设备可能无有效信号输入')
        
        self._cal_result = {
            'status': 'done',
            'floor_db': round(floor, 1),
            'sensitivity_db': self._sensitivity_db,
        }
        if warnings:
            self._cal_result['warnings'] = warnings
            for w in warnings:
                print(f'[CAL] ⚠ {w}')
        
        print(f'[CAL] 频谱指纹校准完成: floor={floor:.1f}dB, sensitivity={self._sensitivity_db}dB')
    
    def start_calibration(self):
        if not self.monitoring:
            return False
        if self._calibrating:
            self._calibrating = False
            self._cal_result = {'status': 'cancelled'}
            return 'cancelled'
        self._calibrating = True
        self._state = 'silent'   # 校准时重置状态机
        self._quiet_count = 0
        self._cal_frames = []
        self._cal_start = time.time()
        self._cal_result = None
        self._cal_remaining = 5.0
        return True
    
    def get_latest(self):
        with self._lock:
            return self._latest
    
    def pop_notifs(self):
        with self._nlock:
            n = self._notifs[:]
            self._notifs.clear()
            return n
    
    def get_stats(self):
        now = time.time()
        if now - self._st_time > 3:
            evts = self.db.get_events_today()
            self._st_cache = {
                'count': len(evts),
                'duration': round(sum(e['duration'] for e in evts) / 60.0, 1),
                'last': time.strftime('%H:%M:%S', time.localtime(evts[0]['start_time'])) if evts else '',
            }
            self._st_time = now
        return self._st_cache
    
    def update_settings(self, s):
        if 'sensitivity_db' in s:
            v = max(1, min(30, float(s['sensitivity_db'])))
            self._sensitivity_db = v
            self.config.set('detection', 'sensitivity_db', v)
        if 'recording_enabled' in s:
            self._rec_on = bool(s['recording_enabled'])
            self.config.set('recording', 'enabled', self._rec_on)
        if 'keep_days' in s:
            self.config.set('recording', 'max_keep_days', int(s['keep_days']))
        if 'device_index' in s:
            idx = int(s['device_index'])
            dev_name = None
            if idx >= 0:
                try:
                    dev_name = sd.query_devices(idx)['name']
                except Exception:
                    pass
            # 直接使用用户选择的设备, 不强制转 WASAPI
            self._dev_idx = None if idx == -1 else idx
            self._dev_name = dev_name
            if self._dev_idx is not None:
                try:
                    self._sr = int(sd.query_devices(self._dev_idx)['default_samplerate'])
                    self.config.set('device', 'sample_rate', self._sr)
                except Exception:
                    pass
            self.config.set('device', 'index', self._dev_idx if self._dev_idx is not None else -1)
            self.config.set('device', 'name', self._dev_name)
        if 'alert_enabled' in s:
            self.config.set('alert', 'enabled', bool(s['alert_enabled']))
        if 'alert_sound' in s:
            self.config.set('alert', 'sound', str(s['alert_sound']))
        if 'alert_interval' in s:
            self.config.set('alert', 'min_interval_seconds', max(1, int(s['alert_interval'])))
        if 'schedule_enabled' in s:
            self._sched_enabled = bool(s['schedule_enabled'])
            self.config.set('schedule', 'enabled', self._sched_enabled)
        if 'schedule_start' in s:
            self._sched_start = str(s['schedule_start'])
            self.config.set('schedule', 'start_time', self._sched_start)
        if 'schedule_end' in s:
            self._sched_end = str(s['schedule_end'])
            self.config.set('schedule', 'end_time', self._sched_end)
        if 'mic_enabled' in s:
            self._mic_enabled = bool(s['mic_enabled'])
            self.config.set('mic', 'enabled', self._mic_enabled)
        if 'mic_devices' in s:
            raw = s['mic_devices']
            if isinstance(raw, list):
                devs = [int(x) for x in raw if int(x) >= 0]
            else:
                devs = [int(raw)] if int(raw) >= 0 else []
            self._mic_devices = [d for d in devs if d != self._dev_idx]
            self.config.set('mic', 'devices', self._mic_devices)
        if 'mic_threshold_db' in s:
            self._mic_threshold_db = int(s['mic_threshold_db'])
            self.config.set('mic', 'threshold_db', self._mic_threshold_db)
        # 麦克风设置变更时重启麦克风流
        if any(k in s for k in ('mic_enabled', 'mic_devices', 'mic_threshold_db')):
            if self.monitoring:
                self._start_mic()
        self.config.save()
    
    def _cleanup(self, days=30):
        cutoff = time.time() - days * 86400
        if not os.path.exists(self._rec_dir):
            return
        for f in os.listdir(self._rec_dir):
            fp = os.path.join(self._rec_dir, f)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                try:
                    os.remove(fp)
                except OSError:
                    pass


# ═══════════════════════════════════════════════
#  全局实例
# ═══════════════════════════════════════════════
config = ConfigManager()
db = Database()
engine = Engine(config, db)
ws_clients: set = set()

# ── 提示音 ──
ALERTS_DIR = os.path.join(BASE_DIR, 'alerts')
os.makedirs(ALERTS_DIR, exist_ok=True)

def _ensure_knock():
    path = os.path.join(ALERTS_DIR, 'knock.wav')
    if os.path.exists(path):
        return
    sr = 44100
    def _k(dur, amp):
        n = int(sr * dur); t = np.linspace(0, dur, n, False)
        body = np.sin(2*np.pi*120*t) + 0.35*np.sin(2*np.pi*240*t) + 0.15*np.sin(2*np.pi*180*t)
        cl = min(int(sr*0.005), n); click = np.zeros(n)
        click[:cl] = np.random.RandomState(42).uniform(-1,1,cl) * np.exp(-np.linspace(0,6,cl))
        env = np.minimum(t/0.0005,1.0) * np.exp(-8*t)
        return amp * (body*env + 0.4*click)
    k = _k(0.22, 0.8); gap = np.zeros(int(sr*0.28))
    audio = np.concatenate([k, gap, k, gap, k])
    pk = np.max(np.abs(audio))
    if pk > 0: audio = audio / pk * 0.95
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(((audio*32767).clip(-32768,32767).astype(np.int16)).tobytes())

_ensure_knock()

# 内置音效列表
def _list_alerts():
    labels = {'knock.wav': '敲墙声 (咚咚咚)', 'water_drop.wav': '水滴声', 'qq_online.wav': 'QQ上线',
              'qq_msg.wav': 'QQ消息', 'wechat_msg.wav': '微信消息', 'default_beep.wav': '默认提示音',
              'close_door.mp3': '关门声'}
    result = []
    if os.path.isdir(ALERTS_DIR):
        for f in sorted(os.listdir(ALERTS_DIR)):
            if f.endswith(('.wav', '.mp3')):
                result.append({'file': f, 'label': labels.get(f, f)})
    return result


# ═══════════════════════════════════════════════
#  FastAPI 应用
# ═══════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.stop()

app = FastAPI(lifespan=lifespan)

@app.get('/')
async def index():
    return FileResponse(os.path.join(BASE_DIR, 'web', 'index.html'))

# ── REST API ──
@app.get('/api/status')
async def get_status():
    return {'monitoring': engine.monitoring, 'calibrated': engine.analyzer.calibrated}

@app.get('/api/devices')
async def get_devices():
    return list_input_devices_dedup()

@app.get('/api/settings')
async def get_settings():
    sched = config.get('schedule') or {}
    mic = config.get('mic') or {}
    return {
        'device': dict(config.device),
        'detection': dict(config.detection),
        'recording': dict(config.recording),
        'alert': dict(config.alert) if config.alert else {'enabled': True, 'sound': 'knock.wav', 'min_interval_seconds': 10},
        'calibration': dict(config.calibration),
        'schedule': {'enabled': sched.get('enabled', False),
                     'start_time': sched.get('start_time', '22:00'),
                     'end_time': sched.get('end_time', '08:00')},
        'mic': {'enabled': mic.get('enabled', False),
                'devices': mic.get('devices', []),
                'threshold_db': mic.get('threshold_db', -40)},
    }

@app.post('/api/settings')
async def save_settings(request: Request):
    engine.update_settings(await request.json())
    return {'ok': True}

@app.post('/api/start')
async def start_monitor():
    err = engine.start()
    if err:
        return JSONResponse({'error': err}, 500)
    return {'monitoring': True}

@app.post('/api/stop')
async def stop_monitor():
    engine.stop()
    return {'monitoring': False}

@app.post('/api/calibrate')
async def calibrate():
    r = engine.start_calibration()
    if r is False:
        return JSONResponse({'error': '请先开启监控'}, 400)
    return {'ok': True, 'cancelled': r == 'cancelled'}

@app.post('/api/switch-device')
async def switch_device(request: Request):
    body = await request.json()
    idx = body.get('device_index')
    if idx is None:
        return JSONResponse({'error': 'no device_index'}, 400)
    idx = int(idx)
    
    # 验证设备存在
    dev_name = None
    api_name = ''
    if idx >= 0:
        try:
            info = sd.query_devices(idx)
            if info['max_input_channels'] <= 0:
                return JSONResponse({'error': '该设备不是输入设备'}, 400)
            dev_name = info['name']
            api_name = sd.query_hostapis(info['hostapi'])['name']
        except Exception:
            return JSONResponse({'error': f'设备 {idx} 不存在'}, 400)
    
    engine._dev_idx = idx
    engine._dev_name = dev_name
    
    try:
        info = sd.query_devices(idx)
        engine._sr = int(info['default_samplerate'])
    except Exception:
        pass
    
    engine.config.set('device', 'index', idx)
    engine.config.set('device', 'name', dev_name)
    engine.config.set('device', 'sample_rate', engine._sr)
    engine.config.save()
    
    if engine.monitoring:
        engine.stop()
        err = engine.start()
        if err:
            return JSONResponse({'ok': False, 'error': err}, 500)
    return {'ok': True, 'resolved_index': idx, 'resolved_name': dev_name, 'api': api_name}

@app.post('/api/test-device')
async def test_device(request: Request):
    body = await request.json()
    idx = body.get('device_index')
    if idx is None:
        return JSONResponse({'error': 'no device'}, 400)
    was = engine.monitoring
    if was:
        engine.stop()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _test_sync, idx)
    if was:
        engine.start()
    return result

def _test_sync(idx):
    """测试检波器录音 — 生成两个WAV: 原始音频 + 检测引擎滤波后音频"""
    try:
        idx = int(idx)
        rec_idx = _find_test_device(idx)  # WASAPI→DirectSound 避免设备锁
        info = sd.query_devices(rec_idx)
        sr = int(info['default_samplerate'])
        dur = 3
        
        time.sleep(0.3)
        audio = sd.rec(int(sr * dur), samplerate=sr, channels=1,
                       device=rec_idx, dtype='float32', blocking=True)[:, 0]
        
        raw_rms = float(np.sqrt(np.mean(audio**2)))
        raw_peak = float(np.max(np.abs(audio)))
        
        # === 原始录音 (轻度归一化, 保留全频段, 让用户听到真实声音) ===
        raw_audio = audio.copy()
        rpeak = float(np.max(np.abs(raw_audio)))
        if rpeak > 1e-6:
            raw_audio = raw_audio * min(0.8 / rpeak, 50.0)
        raw_path = os.path.join(BASE_DIR, 'web', 'test_rec.wav')
        with wave.open(raw_path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            pcm = (raw_audio * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        
        # === 滤波后录音 (5-250Hz 带通, 展示检测引擎"听"到的信号) ===
        try:
            sos = _build_bandpass(sr)
            filtered = sosfilt(sos, audio)
            skip = min(int(0.1 * sr), len(filtered) // 4)
            filtered = filtered[skip:]
        except Exception as e:
            print(f'[TEST] 滤波器失败: {e}')
            filtered = audio
        fpeak = float(np.max(np.abs(filtered)))
        if fpeak > 1e-6:
            filtered = filtered * (0.7 / fpeak)
        filt_path = os.path.join(BASE_DIR, 'web', 'test_rec_filtered.wav')
        with wave.open(filt_path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            pcm = (filtered * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        
        rms_db = round(20 * np.log10(max(raw_rms, 1e-10)), 1)
        api_name = sd.query_hostapis(info['hostapi'])['name']
        return {'ok': True, 'rms_db': rms_db, 'peak': round(raw_peak, 6),
                'sr': sr, 'channels': 1, 'device': info['name'],
                'api': api_name}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get('/api/test-playback')
async def test_playback():
    path = os.path.join(BASE_DIR, 'web', 'test_rec.wav')
    if not os.path.exists(path):
        return JSONResponse({'error': '无录音'}, 404)
    return FileResponse(path, media_type='audio/wav',
                        headers={'Cache-Control': 'no-store'})

@app.get('/api/test-playback-filtered')
async def test_playback_filtered():
    path = os.path.join(BASE_DIR, 'web', 'test_rec_filtered.wav')
    if not os.path.exists(path):
        return JSONResponse({'error': '无录音'}, 404)
    return FileResponse(path, media_type='audio/wav',
                        headers={'Cache-Control': 'no-store'})

@app.post('/api/test-mic')
async def test_mic(request: Request):
    """试听麦克风 — 暂停监测，录制2秒原始音频"""
    body = await request.json()
    idx = body.get('device_index')
    if idx is None:
        return JSONResponse({'error': '未指定设备'}, 400)
    was = engine.monitoring
    if was:
        engine.stop()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _test_mic_sync, int(idx))
    if was:
        engine.start()
    return result

def _test_mic_sync(idx):
    """试听麦克风 — sd.rec() 直接录制原始音频"""
    try:
        rec_idx = _find_test_device(idx)  # WASAPI→DirectSound 避免设备锁
        info = sd.query_devices(rec_idx)
        if info['max_input_channels'] <= 0:
            return {'ok': False, 'error': '不是输入设备'}
        sr = int(info['default_samplerate'])
        dur = 2
        
        time.sleep(0.3)
        audio = sd.rec(int(sr * dur), samplerate=sr, channels=1,
                       device=rec_idx, dtype='float32', blocking=True)[:, 0]
        
        rms = float(np.sqrt(np.mean(audio**2)))
        rms_db = round(20 * np.log10(max(rms, 1e-10)), 1)
        peak = float(np.max(np.abs(audio)))
        # 轻度归一化: 只防削波
        if peak > 0.01:
            audio = audio * min(0.9 / peak, 3.0)
        path = os.path.join(BASE_DIR, 'web', f'test_mic_{idx}.wav')
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            wf.writeframes(pcm.tobytes())
        api_name = sd.query_hostapis(info['hostapi'])['name']
        return {'ok': True, 'rms_db': rms_db, 'peak': round(peak, 6),
                'sr': sr, 'device': info['name'],
                'api': api_name, 'device_index': idx}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.get('/api/test-mic-playback/{idx}')
async def test_mic_playback(idx: int):
    path = os.path.join(BASE_DIR, 'web', f'test_mic_{idx}.wav')
    if not os.path.exists(path):
        return JSONResponse({'error': '无录音'}, 404)
    return FileResponse(path, media_type='audio/wav',
                        headers={'Cache-Control': 'no-store'})

@app.get('/api/alerts')
async def get_alerts():
    return _list_alerts()

@app.get('/api/alert-sound/{name}')
async def get_alert_sound(name: str):
    safe = os.path.basename(name)
    path = os.path.join(ALERTS_DIR, safe)
    if not os.path.exists(path):
        return JSONResponse({'error': 'not found'}, 404)
    mime = 'audio/mpeg' if safe.endswith('.mp3') else 'audio/wav'
    return FileResponse(path, media_type=mime)

@app.get('/api/events')
async def get_events():
    return engine.db.get_events_today()

@app.get('/api/stats/daily')
async def daily_stats():
    return engine.db.get_daily_stats(7)

@app.get('/api/stats/hourly')
async def hourly_stats():
    return engine.db.get_hourly_distribution(7)

@app.get('/api/recordings')
async def list_recordings():
    files = []
    if os.path.exists(engine._rec_dir):
        for f in sorted(os.listdir(engine._rec_dir), reverse=True):
            if f.endswith('.wav'):
                files.append(f)
    return files

@app.get('/api/recording/{name}')
async def get_recording(name: str):
    safe = os.path.basename(name)
    path = os.path.join(engine._rec_dir, safe)
    if not os.path.exists(path):
        return JSONResponse({'error': 'not found'}, 404)
    return FileResponse(path, media_type='audio/wav')

# ── WebSocket 实时推送 ──
@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await asyncio.sleep(0.08)
            frame = engine.get_latest()
            if frame is None:
                await ws.send_json({'type': 'idle'})
                continue
            notifs = engine.pop_notifs()
            stats = engine.get_stats()
            await ws.send_json({
                'type': 'frame',
                'frame': frame,
                'notifs': notifs,
                'stats': stats,
                'monitoring': engine.monitoring,
            })
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        ws_clients.discard(ws)


# ═══════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 50)
    print('  NoiseGuard v4 — SM-24 检波器噪音监测')
    print('=' * 50)
    print()
    print('  👉  http://127.0.0.1:8899')
    print()
    print('=' * 50)
    uvicorn.run(app, host='127.0.0.1', port=8899, log_level='info')

