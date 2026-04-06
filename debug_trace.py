"""Debug: trace per-frame band_power vs noise_ref"""
import numpy as np, sys
sys.path.insert(0, '.')
import server

np.random.seed(42)
a = server.VibrationAnalyzer(44100, 1024)
cal = np.random.randn(44100*5)*0.001
a.calibrate(cal)

print('Calibrated noise_band_power:', a._noise_band_power)
print('In dB:', [f'{10*np.log10(max(x,1e-20)):.1f}' for x in a._noise_band_power])
print()

test = np.random.randn(1024*20)*0.001
for i in range(20):
    frame = test[i*1024:(i+1)*1024]
    r = a.analyze(frame)
    ema = a._band_power_ema
    noise_ref = np.maximum(a._noise_band_power, a._adapt_band_power)
    ratios = ema / noise_ref
    print(f'f{i:2d} rms={r["rms_db"]:6.1f} excess={r["excess_db"]:5.1f} '
          f'ema/noise=[{ratios[0]:.2f}, {ratios[1]:.2f}, {ratios[2]:.2f}] '
          f'stalat={r["sta_lta"]:.2f}')
