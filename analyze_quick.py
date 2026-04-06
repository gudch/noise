"""快速验证: 过减因子对安静帧 excess 的抑制效果"""
import os, sys, glob, numpy as np, wave

sys.path.insert(0, os.path.dirname(__file__))
import server

REC_DIR = os.path.join(os.path.dirname(__file__), 'recordings')

def read_wav(path):
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    return sr, data

wavs = sorted(glob.glob(os.path.join(REC_DIR, '*.wav')))
vib_files = [w for w in wavs if os.path.basename(w).startswith('vib_')]
noise_files = [w for w in wavs if os.path.basename(w).startswith('noise_')]

# Test 1: noise_ file (has continuous ambient)
print('--- noise_ file (continuous ambient) ---')
for f in noise_files[-2:]:
    sr, audio = read_wav(f)
    blk = 1024
    a = server.VibrationAnalyzer(sr, blk)
    cal_n = sr * 2
    a.calibrate(audio[:cal_n])
    
    quiet_excess = []
    event_excess = []
    for i in range(len(audio) // blk):
        frame = audio[i*blk:(i+1)*blk]
        r = a.analyze(frame)
        if r['rms_db'] < a.noise_floor_db + 3:
            quiet_excess.append(r['excess_db'])
        else:
            event_excess.append(r['excess_db'])
    
    qe = np.array(quiet_excess) if quiet_excess else np.array([0])
    ee = np.array(event_excess) if event_excess else np.array([0])
    print(f'{os.path.basename(f)}:')
    print(f'  quiet frames: {len(quiet_excess)}, max_excess={qe.max():.2f}, mean={qe.mean():.2f}')
    print(f'  event frames: {len(event_excess)}, max_excess={ee.max():.1f}, mean={ee.mean():.1f}')
    print(f'  MARGIN = min_event - max_quiet = {ee.min():.1f} - {qe.max():.2f} = {ee.min()-qe.max():.1f}dB')

# Test 2: vib_ file with pre-buffer zeros
print('\n--- vib_ file (impulsive, zeros in pre-buffer) ---')
for f in vib_files[-4:]:
    sr, audio = read_wav(f)
    blk = 1024
    a = server.VibrationAnalyzer(sr, blk)
    cal_n = sr * 2
    a.calibrate(audio[:cal_n])
    
    all_excess = []
    for i in range(len(audio) // blk):
        frame = audio[i*blk:(i+1)*blk]
        r = a.analyze(frame)
        all_excess.append(r['excess_db'])
    
    ae = np.array(all_excess)
    n_trigger = sum(1 for x in ae if x >= 1.0)
    print(f'{os.path.basename(f)}: max={ae.max():.1f} mean={ae.mean():.1f} '
          f'trigger@1dB={n_trigger}/{len(ae)} '
          f'cal_floor={a.noise_floor_db:.1f}')

# Test 3: Pure noise simulation
print('\n--- Synthetic white noise (worst case baseline) ---')
a = server.VibrationAnalyzer(44100, 1024)
cal_noise = np.random.randn(44100*5) * 0.001
a.calibrate(cal_noise)
excess_list = []
for i in range(200):
    frame = np.random.randn(1024) * 0.001
    r = a.analyze(frame)
    excess_list.append(r['excess_db'])
el = np.array(excess_list)
print(f'Pure noise: max_excess={el.max():.2f}, mean={el.mean():.2f}, >1dB: {sum(1 for x in el if x>=1)}/200')
