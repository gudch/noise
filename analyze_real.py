"""分析真实录音 — 基于现实数据而非假设"""
import os, glob, numpy as np, wave, struct

REC_DIR = os.path.join(os.path.dirname(__file__), 'recordings')

def read_wav(path):
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    else:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float64) / 128.0 - 1.0
    if ch > 1:
        data = data[::ch]
    return sr, data

def analyze_spectrum(audio, sr, label=''):
    """分析一段音频的频谱特征"""
    n = len(audio)
    rms = np.sqrt(np.mean(audio**2))
    rms_db = 20 * np.log10(max(rms, 1e-10))
    peak = np.max(np.abs(audio))
    
    # FFT (整段, 用 Hanning 窗)
    win = np.hanning(n)
    fft_mag = np.abs(np.fft.rfft(audio * win)) / n
    freqs = np.fft.rfftfreq(n, 1.0/sr)
    fft_db = 20 * np.log10(np.maximum(fft_mag, 1e-10))
    
    # 找频谱峰值 (10-300Hz)
    mask = (freqs >= 5) & (freqs <= 300)
    f_crop = freqs[mask]
    db_crop = fft_db[mask]
    
    # Top 5 峰值频率
    top_idx = np.argsort(db_crop)[-5:][::-1]
    peaks = [(round(f_crop[i], 1), round(db_crop[i], 1)) for i in top_idx]
    
    # 各频段能量
    bands = [(5,40), (40,120), (120,250)]
    band_db = []
    for lo, hi in bands:
        m = (freqs >= lo) & (freqs < hi)
        if np.any(m):
            bp = np.mean(fft_mag[m]**2)
            band_db.append(10 * np.log10(max(bp, 1e-20)))
        else:
            band_db.append(-200)
    
    # 50Hz 附近特别检查 (±2Hz)
    m50 = (freqs >= 48) & (freqs <= 52)
    if np.any(m50):
        p50 = float(np.max(fft_db[m50]))
    else:
        p50 = -200
    
    # 全频段平均底噪
    avg_noise = float(np.mean(db_crop))
    
    print(f'  {label}')
    print(f'    RMS={rms_db:.1f}dB  Peak={peak:.6f}  Duration={n/sr:.1f}s  SR={sr}')
    print(f'    频段能量: [5-40Hz]={band_db[0]:.1f}  [40-120Hz]={band_db[1]:.1f}  [120-250Hz]={band_db[2]:.1f}')
    print(f'    50Hz峰值={p50:.1f}dB  频段平均={avg_noise:.1f}dB  50Hz突出={p50-avg_noise:.1f}dB')
    print(f'    Top5频率: {peaks}')
    return {
        'rms_db': rms_db, 'peak': peak, 'band_db': band_db,
        'p50': p50, 'avg_noise': avg_noise, 'peaks': peaks
    }

def analyze_segments(audio, sr, seg_ms=100):
    """分段分析: 找最响和最安静的片段"""
    seg_n = int(sr * seg_ms / 1000)
    n_segs = len(audio) // seg_n
    if n_segs < 2:
        return
    rms_list = []
    for i in range(n_segs):
        seg = audio[i*seg_n:(i+1)*seg_n]
        rms = np.sqrt(np.mean(seg**2))
        rms_list.append(20 * np.log10(max(rms, 1e-10)))
    rms_arr = np.array(rms_list)
    print(f'    100ms段: min={rms_arr.min():.1f}dB  max={rms_arr.max():.1f}dB  '
          f'median={np.median(rms_arr):.1f}dB  std={np.std(rms_arr):.1f}dB  '
          f'range={rms_arr.max()-rms_arr.min():.1f}dB')

# === 主分析 ===
wavs = sorted(glob.glob(os.path.join(REC_DIR, '*.wav')))
print(f'找到 {len(wavs)} 个录音文件')
print()

# 分析最近的 vib_ 文件 (新版录音) 和 noise_ 文件 (旧版)
vib_files = [w for w in wavs if os.path.basename(w).startswith('vib_')]
noise_files = [w for w in wavs if os.path.basename(w).startswith('noise_')]

# 取最近几个 vib 文件详细分析
print('=== 最近 vib_ 录音 (触发的事件) ===')
for f in vib_files[-6:]:
    try:
        sr, audio = read_wav(f)
        analyze_spectrum(audio, sr, os.path.basename(f))
        analyze_segments(audio, sr)
    except Exception as e:
        print(f'  {os.path.basename(f)}: Error {e}')
    print()

# 取几个 noise_ 文件 (旧版触发)
print('=== 最近 noise_ 录音 (旧版触发) ===')
for f in noise_files[-6:]:
    try:
        sr, audio = read_wav(f)
        analyze_spectrum(audio, sr, os.path.basename(f))
        analyze_segments(audio, sr)
    except Exception as e:
        print(f'  {os.path.basename(f)}: Error {e}')
    print()

# 统计总览
print('=== 所有 vib_ 文件统计 ===')
all_rms = []
all_peak = []
all_p50 = []
for f in vib_files:
    try:
        sr, audio = read_wav(f)
        rms = np.sqrt(np.mean(audio**2))
        all_rms.append(20 * np.log10(max(rms, 1e-10)))
        all_peak.append(np.max(np.abs(audio)))
        # 50Hz 检查
        n = len(audio)
        fft_mag = np.abs(np.fft.rfft(audio * np.hanning(n))) / n
        freqs = np.fft.rfftfreq(n, 1.0/sr)
        m50 = (freqs >= 48) & (freqs <= 52)
        if np.any(m50):
            all_p50.append(float(np.max(20*np.log10(np.maximum(fft_mag[m50], 1e-10)))))
    except:
        pass

if all_rms:
    arr = np.array(all_rms)
    p50_arr = np.array(all_p50) if all_p50 else np.array([-200])
    pk_arr = np.array(all_peak)
    print(f'  文件数: {len(all_rms)}')
    print(f'  RMS(dB):  min={arr.min():.1f}  max={arr.max():.1f}  median={np.median(arr):.1f}  std={np.std(arr):.1f}')
    print(f'  Peak:     min={pk_arr.min():.6f}  max={pk_arr.max():.6f}  median={np.median(pk_arr):.6f}')
    print(f'  50Hz(dB): min={p50_arr.min():.1f}  max={p50_arr.max():.1f}  median={np.median(p50_arr):.1f}')
