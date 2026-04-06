"""用真实录音测试新版 VibrationAnalyzer — 模拟逐帧检测"""
import os, sys, glob, numpy as np, wave

sys.path.insert(0, os.path.dirname(__file__))
import server

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

def simulate_detection(wav_path, sensitivity_db=1.0):
    """逐帧喂给 VibrationAnalyzer, 返回每帧结果"""
    sr, audio = read_wav(wav_path)
    blk = 1024
    
    analyzer = server.VibrationAnalyzer(sr, blk)
    
    # 先用前2秒校准 (模拟已校准状态)
    cal_n = min(sr * 2, len(audio) // 2)
    if cal_n > blk * 3:
        analyzer.calibrate(audio[:cal_n])
    
    # 逐帧分析
    results = []
    n_frames = len(audio) // blk
    for i in range(n_frames):
        frame = audio[i*blk:(i+1)*blk]
        a = analyzer.analyze(frame)
        cls, label = server.classify_vibration(a, sensitivity_db)
        results.append({
            'frame': i,
            'time_s': round(i * blk / sr, 2),
            'rms_db': a['rms_db'],
            'excess_db': a['excess_db'],
            'sta_lta': a['sta_lta'],
            'sub_db': a['sub_db'],
            'low_db': a['low_db'],
            'mid_db': a['mid_db'],
            'cls': cls,
        })
    return sr, results

# === 分析几个典型录音 ===
wavs = sorted(glob.glob(os.path.join(REC_DIR, '*.wav')))
vib_files = [w for w in wavs if os.path.basename(w).startswith('vib_')]
noise_files = [w for w in wavs if os.path.basename(w).startswith('noise_')]

# 选几个有代表性的
# 强信号 vib
# 弱信号 vib
# noise 文件 
test_files = []
if vib_files:
    # 取最近的几个
    test_files += vib_files[-4:]
if noise_files:
    test_files += noise_files[-3:]

print('=== 逐帧检测模拟 (sensitivity_db=1.0) ===\n')

for fpath in test_files:
    fname = os.path.basename(fpath)
    try:
        sr, results = simulate_detection(fpath, sensitivity_db=1.0)
    except Exception as e:
        print(f'{fname}: Error: {e}\n')
        continue
    
    # 统计
    n_total = len(results)
    n_trigger = sum(1 for r in results if r['cls'] != 'silent')
    excess_arr = np.array([r['excess_db'] for r in results])
    rms_arr = np.array([r['rms_db'] for r in results])
    sta_arr = np.array([r['sta_lta'] for r in results])
    
    print(f'{fname} ({n_total} frames, {n_total*1024/sr:.1f}s):')
    print(f'  触发: {n_trigger}/{n_total} ({100*n_trigger/max(n_total,1):.0f}%)')
    print(f'  excess_db: min={excess_arr.min():.1f} max={excess_arr.max():.1f} '
          f'median={np.median(excess_arr):.1f} mean={excess_arr.mean():.1f}')
    print(f'  rms_db:    min={rms_arr.min():.1f} max={rms_arr.max():.1f} '
          f'median={np.median(rms_arr):.1f}')
    print(f'  sta_lta:   min={sta_arr.min():.2f} max={sta_arr.max():.2f}')
    
    # 分类统计
    cls_counts = {}
    for r in results:
        cls_counts[r['cls']] = cls_counts.get(r['cls'], 0) + 1
    print(f'  分类: {cls_counts}')
    
    # 显示触发的帧
    triggers = [r for r in results if r['cls'] != 'silent']
    if triggers:
        print(f'  触发帧示例:')
        for t in triggers[:8]:
            print(f'    t={t["time_s"]:5.2f}s excess={t["excess_db"]:5.1f} sta/lta={t["sta_lta"]:.2f} '
                  f'rms={t["rms_db"]:.1f} sub/low/mid={t["sub_db"]:.0f}/{t["low_db"]:.0f}/{t["mid_db"]:.0f} → {t["cls"]}')
    
    # 找安静帧中 excess 最高的 (最容易误报的)
    quiet = [r for r in results if r['cls'] == 'silent']
    if quiet:
        quiet_sorted = sorted(quiet, key=lambda r: r['excess_db'], reverse=True)
        print(f'  安静帧最高excess:')
        for q in quiet_sorted[:3]:
            print(f'    t={q["time_s"]:5.2f}s excess={q["excess_db"]:5.1f} sta/lta={q["sta_lta"]:.2f} rms={q["rms_db"]:.1f}')
    
    print()

# === 额外: 分析所有 vib 文件的 excess 分布 ===
print('=== 所有 vib_ 文件的 excess_db 分布 ===')
all_excess_max = []
all_excess_mean = []
all_trigger_rate = []

for fpath in vib_files:
    try:
        sr, results = simulate_detection(fpath, sensitivity_db=1.0)
        excess_arr = np.array([r['excess_db'] for r in results])
        n_trigger = sum(1 for r in results if r['cls'] != 'silent')
        all_excess_max.append(excess_arr.max())
        all_excess_mean.append(excess_arr.mean())
        all_trigger_rate.append(n_trigger / max(len(results), 1))
    except:
        pass

if all_excess_max:
    mx = np.array(all_excess_max)
    mn = np.array(all_excess_mean)
    tr = np.array(all_trigger_rate)
    print(f'  文件数: {len(mx)}')
    print(f'  max_excess: min={mx.min():.1f} max={mx.max():.1f} median={np.median(mx):.1f}')
    print(f'  mean_excess: min={mn.min():.1f} max={mn.max():.1f} median={np.median(mn):.1f}')
    print(f'  trigger_rate: min={tr.min():.2f} max={tr.max():.2f} median={np.median(tr):.2f}')
    # 有多少文件 max_excess < 2dB (很可能是误报)
    false_alarm = sum(1 for x in mx if x < 2)
    real_event = sum(1 for x in mx if x >= 5)
    ambiguous = len(mx) - false_alarm - real_event
    print(f'  疑似误报(max<2dB): {false_alarm}/{len(mx)}')
    print(f'  明确事件(max>=5dB): {real_event}/{len(mx)}')
    print(f'  模糊(2-5dB): {ambiguous}/{len(mx)}')
