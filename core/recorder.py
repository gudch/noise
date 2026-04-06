"""录音器 - 环形缓冲 + 事件触发录音"""
import os
import wave
import time
import collections
import numpy as np
import threading


class Recorder:
    """环形缓冲区 + 事件录音"""

    def __init__(self, sample_rate=48000, pre_buffer_sec=3,
                 post_buffer_sec=3, output_dir="recordings"):
        self._sr = sample_rate
        self._pre_sec = pre_buffer_sec
        self._post_sec = post_buffer_sec
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # 环形缓冲: 存储最近 pre_buffer_sec 的音频
        buf_size = int(sample_rate * pre_buffer_sec / 2048) + 2
        self._ring = collections.deque(maxlen=buf_size)

        self._recording = False
        self._rec_frames = []
        self._post_countdown = 0
        self._lock = threading.Lock()

    def feed(self, audio: np.ndarray):
        """每帧音频都喂入，维护环形缓冲"""
        with self._lock:
            self._ring.append(audio.copy())
            if self._recording:
                self._rec_frames.append(audio.copy())
                if self._post_countdown > 0:
                    self._post_countdown -= 1
                    if self._post_countdown <= 0:
                        self._save_and_reset()

    def start_recording(self):
        """事件开始 → 开始录音（包含 pre-buffer）"""
        with self._lock:
            if self._recording:
                # 已在录音，取消倒计时
                self._post_countdown = 0
                return
            self._recording = True
            self._rec_frames = list(self._ring)  # 拷贝 pre-buffer
            self._post_countdown = 0

    def stop_recording(self):
        """事件结束 → 开始 post-buffer 倒计时"""
        with self._lock:
            if not self._recording:
                return
            frames_per_sec = self._sr / 2048
            self._post_countdown = int(self._post_sec * frames_per_sec) + 1

    def _save_and_reset(self):
        """保存录音文件"""
        frames = self._rec_frames
        self._rec_frames = []
        self._recording = False
        self._post_countdown = 0

        if not frames:
            return

        # 异步保存
        threading.Thread(
            target=self._write_wav, args=(frames,), daemon=True
        ).start()

    def _write_wav(self, frames):
        audio = np.concatenate(frames)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._output_dir, f"noise_{ts}.wav")
        try:
            with wave.open(path, 'w') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self._sr)
                pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
                wf.writeframes(pcm.tobytes())
        except Exception:
            pass

    def cleanup_old(self, max_days=30):
        """清理旧录音"""
        cutoff = time.time() - max_days * 86400
        if not os.path.exists(self._output_dir):
            return
        for f in os.listdir(self._output_dir):
            fp = os.path.join(self._output_dir, f)
            if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                try:
                    os.remove(fp)
                except OSError:
                    pass
