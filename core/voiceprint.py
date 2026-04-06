"""声纹识别模块 — MFCC 特征提取 + 余弦相似度匹配

用于识别家庭成员语音，自动过滤为 'home' 而非 'upstairs'。
流程: 录制 5~10 秒语音 → 提取 MFCC 均值/方差 → 存储为模板
运行时: 检测到语音时提取 MFCC → 与模板余弦比对 → 匹配则标记为家人
"""
import json
import os
import numpy as np


class VoiceprintManager:
    """声纹管理: 注册、匹配、增删"""

    def __init__(self, data_dir: str, sample_rate: int = 44100):
        self._sr = sample_rate
        self._data_dir = data_dir
        self._db_path = os.path.join(data_dir, 'voiceprints.json')
        os.makedirs(data_dir, exist_ok=True)
        # { name: { 'mfcc_mean': [...], 'mfcc_std': [...] } }
        self._profiles: dict = {}
        self._load()

    # ── 公开接口 ──

    def enroll(self, name: str, audio: np.ndarray):
        """用一段语音注册声纹 (至少 2 秒)"""
        if len(audio) < self._sr * 2:
            raise ValueError('录音时长不足 2 秒')
        mfcc = _extract_mfcc(audio, self._sr)  # (N_frames, 13)
        if mfcc.shape[0] < 5:
            raise ValueError('有效语音帧太少，请大声说话')
        # 过滤静音帧 (能量太低的帧)
        frame_energy = np.sum(mfcc ** 2, axis=1)
        threshold = np.percentile(frame_energy, 25)
        voice_frames = mfcc[frame_energy > threshold]
        if voice_frames.shape[0] < 5:
            voice_frames = mfcc
        self._profiles[name] = {
            'mfcc_mean': voice_frames.mean(axis=0).tolist(),
            'mfcc_std': voice_frames.std(axis=0).tolist(),
        }
        self._save()

    def remove(self, name: str):
        if name in self._profiles:
            del self._profiles[name]
            self._save()
            return True
        return False

    def list_profiles(self):
        return list(self._profiles.keys())

    def match(self, audio: np.ndarray, threshold: float = 0.82) -> tuple:
        """检测一段音频是否匹配已注册声纹。
        返回 (matched: bool, best_name: str|None, best_score: float)
        """
        if not self._profiles:
            return False, None, 0.0
        mfcc = _extract_mfcc(audio, self._sr)
        if mfcc.shape[0] < 3:
            return False, None, 0.0
        # 过滤静音帧
        frame_energy = np.sum(mfcc ** 2, axis=1)
        th = np.percentile(frame_energy, 30)
        voice_frames = mfcc[frame_energy > th]
        if voice_frames.shape[0] < 2:
            return False, None, 0.0
        cur_mean = voice_frames.mean(axis=0)

        best_name, best_score = None, -1.0
        for name, profile in self._profiles.items():
            ref = np.array(profile['mfcc_mean'])
            score = _cosine_sim(cur_mean, ref)
            if score > best_score:
                best_score = score
                best_name = name
        matched = best_score >= threshold
        return matched, best_name, float(best_score)

    # ── 持久化 ──

    def _load(self):
        if os.path.exists(self._db_path):
            try:
                with open(self._db_path, 'r', encoding='utf-8') as f:
                    self._profiles = json.load(f)
            except Exception:
                self._profiles = {}

    def _save(self):
        with open(self._db_path, 'w', encoding='utf-8') as f:
            json.dump(self._profiles, f, ensure_ascii=False, indent=2)


# ── MFCC 提取 (纯 numpy, 不依赖额外库) ──

def _hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + hz / 700.0)

def _mel_to_hz(mel):
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

def _mel_filterbank(sr, n_fft, n_filters=26, f_low=80, f_high=None):
    """构建梅尔滤波器组"""
    if f_high is None:
        f_high = sr / 2
    mel_low = _hz_to_mel(f_low)
    mel_high = _hz_to_mel(f_high)
    mel_pts = np.linspace(mel_low, mel_high, n_filters + 2)
    hz_pts = _mel_to_hz(mel_pts)
    bins = np.floor((n_fft + 1) * hz_pts / sr).astype(int)

    fb = np.zeros((n_filters, n_fft // 2 + 1))
    for i in range(n_filters):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        for j in range(left, center):
            if center != left:
                fb[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fb[i, j] = (right - j) / (right - center)
    return fb

def _dct_matrix(n_out, n_in):
    """Type-II DCT 矩阵"""
    mat = np.zeros((n_out, n_in))
    for k in range(n_out):
        for n in range(n_in):
            mat[k, n] = np.cos(np.pi * k * (2 * n + 1) / (2 * n_in))
    return mat

def _extract_mfcc(audio: np.ndarray, sr: int,
                   n_mfcc: int = 13, frame_len: int = 1024,
                   hop: int = 512, n_filters: int = 26) -> np.ndarray:
    """提取 MFCC 特征矩阵 (N_frames, n_mfcc)"""
    # 预加重
    pre = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

    # 分帧
    n_frames = max(1, 1 + (len(pre) - frame_len) // hop)
    frames = np.zeros((n_frames, frame_len))
    for i in range(n_frames):
        start = i * hop
        end = start + frame_len
        if end <= len(pre):
            frames[i] = pre[start:end]
        else:
            seg = pre[start:]
            frames[i, :len(seg)] = seg

    # 加窗
    window = np.hamming(frame_len)
    frames *= window

    # FFT → 功率谱
    n_fft = frame_len
    mag = np.abs(np.fft.rfft(frames, n=n_fft))
    power = mag ** 2 / n_fft

    # 梅尔滤波器
    fb = _mel_filterbank(sr, n_fft, n_filters)
    mel_spec = power @ fb.T
    mel_spec = np.maximum(mel_spec, 1e-10)
    log_mel = np.log(mel_spec)

    # DCT → MFCC
    dct = _dct_matrix(n_mfcc, n_filters)
    mfcc = log_mel @ dct.T

    return mfcc


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
