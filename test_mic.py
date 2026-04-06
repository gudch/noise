"""
麦克风快速诊断工具
列出所有可用设备，选择一个录 10 秒，分析低频/中频/高频能量分布。
帮助判断你的麦克风能不能检测到楼上噪音。

用法:  py test_mic.py
"""

import sounddevice as sd
import numpy as np
import sys

# ─── 1. 列出所有输入设备 ───
print("=" * 60)
print("  可用的输入设备")
print("=" * 60)

devices = sd.query_devices()
input_devs = []
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        api = sd.query_hostapis(d['hostapi'])['name']
        name_lower = d['name'].lower()
        # 跳过虚拟设备和 WDM-KS（兼容性差）
        if any(kw in name_lower for kw in ['映射', 'mapper', '主声音', 'primary']):
            continue
        if 'WDM-KS' in api:
            continue
        # 跳过扬声器/输出设备出现在输入列表里的
        if '扬声器' in d['name'] or 'speaker' in name_lower or 'output' in name_lower:
            continue
        input_devs.append((i, d['name'], api, d['max_input_channels'],
                           int(d['default_samplerate'])))

for idx, (dev_i, name, api, ch, sr) in enumerate(input_devs):
    print(f"  [{idx}]  {name}  ({api})  {ch}ch  {sr}Hz")

print()
choice = input("选择设备编号 (直接回车用第一个): ").strip()
if choice == '':
    sel = 0
else:
    sel = int(choice)

dev_index, dev_name, dev_api, dev_ch, dev_sr = input_devs[sel]
print(f"\n>>> 使用: {dev_name} (index={dev_index}, {dev_sr}Hz)")

# ─── 2. 录制 10 秒 ───
# 用设备默认采样率，避免不支持的采样率报错
SR = dev_sr
DURATION = 10

print(f"\n{'=' * 60}")
print(f"  开始录制 {DURATION} 秒")
print(f"  请在录制期间制造一些声音来测试：")
print(f"    - 前 5 秒：安静（采集底噪）")
print(f"    - 后 5 秒：模拟楼上噪音（敲桌子/跺脚）")
print(f"{'=' * 60}")
input("按回车开始录制...")

print("🔴 录制中...", end='', flush=True)
audio = sd.rec(int(DURATION * SR), samplerate=SR, channels=1,
               dtype='float32', device=dev_index)
sd.wait()
audio = audio[:, 0]
print(" 完成！\n")

# ─── 3. 分析 ───
# 分成 0.5 秒的帧
frame_len = SR // 2  # 8000 samples = 0.5s
n_frames = len(audio) // frame_len

print("=" * 60)
print("  逐段分析 (每段 0.5 秒)")
print("=" * 60)
print(f"{'时间':>6s}  {'总能量dB':>8s}  {'低频dB':>7s}  {'中频dB':>7s}  {'高频dB':>7s}  {'低/中高比':>8s}  {'判定'}")
print("-" * 75)

for i in range(n_frames):
    seg = audio[i * frame_len : (i + 1) * frame_len]
    
    # RMS → dB
    rms = np.sqrt(np.mean(seg ** 2))
    db_total = 20 * np.log10(max(rms, 1e-10))
    
    # FFT
    fft_vals = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / SR)
    
    # 频带能量 (用 RMS 的平方和)
    def band_energy(f_low, f_high):
        mask = (freqs >= f_low) & (freqs < f_high)
        if not np.any(mask):
            return 1e-20
        return np.sqrt(np.mean(fft_vals[mask] ** 2))
    
    e_low  = band_energy(20, 200)
    e_mid  = band_energy(200, 2000)
    e_high = band_energy(2000, 8000)
    
    db_low  = 20 * np.log10(max(e_low, 1e-10))
    db_mid  = 20 * np.log10(max(e_mid, 1e-10))
    db_high = 20 * np.log10(max(e_high, 1e-10))
    
    ratio = e_low / (e_mid + e_high + 1e-10)
    
    # 简易判定
    if db_total < -50:
        label = "⚪ 安静"
    elif ratio > 2.0:
        label = "🔴 低频主导(疑似楼上)"
    elif ratio > 1.0:
        label = "🟡 低频偏高"
    else:
        label = "🟢 中高频(自家声音)"
    
    t = i * 0.5
    print(f"{t:5.1f}s  {db_total:8.1f}  {db_low:7.1f}  {db_mid:7.1f}  {db_high:7.1f}  {ratio:8.2f}  {label}")

# ─── 4. 总结 ───
# 前5秒 vs 后5秒
half = len(audio) // 2
quiet_part = audio[:half]
noise_part = audio[half:]

rms_q = np.sqrt(np.mean(quiet_part ** 2))
rms_n = np.sqrt(np.mean(noise_part ** 2))
db_q = 20 * np.log10(max(rms_q, 1e-10))
db_n = 20 * np.log10(max(rms_n, 1e-10))
snr = db_n - db_q

print(f"\n{'=' * 60}")
print(f"  总结")
print(f"{'=' * 60}")
print(f"  前 5 秒 (安静) 平均: {db_q:.1f} dB")
print(f"  后 5 秒 (噪音) 平均: {db_n:.1f} dB")
print(f"  信噪比 (SNR):        {snr:.1f} dB")
print()

if snr > 20:
    print("  ✅ 非常好！麦克风灵敏度完全够用，信噪比很高。")
elif snr > 10:
    print("  ✅ 够用。信噪比可以，能区分噪音和安静。")
elif snr > 5:
    print("  ⚠️ 勉强。信号偏弱，灵敏度调高后可能能用。")
else:
    print("  ❌ 不行。麦克风几乎检测不到声音变化，需要换设备。")

print()

# 保存录音供后续分析
import wave, struct
wav_path = "test_recording.wav"
with wave.open(wav_path, 'w') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    pcm = (audio * 32767).astype(np.int16)
    wf.writeframes(pcm.tobytes())
print(f"  录音已保存到 {wav_path}，可用音频软件回放检查。")
