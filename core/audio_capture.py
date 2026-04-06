"""音频采集模块 - sounddevice 封装"""
import numpy as np
import sounddevice as sd
from PyQt5.QtCore import QObject, pyqtSignal, QThread


def list_input_devices():
    """列出可用输入设备，过滤虚拟设备和 WDM-KS"""
    devices = sd.query_devices()
    result = []
    for i, d in enumerate(devices):
        if d['max_input_channels'] <= 0:
            continue
        api = sd.query_hostapis(d['hostapi'])['name']
        name_lower = d['name'].lower()
        if any(kw in name_lower for kw in ['映射', 'mapper', '主声音', 'primary']):
            continue
        if 'WDM-KS' in api:
            continue
        if '扬声器' in d['name'] or 'speaker' in name_lower or 'output' in name_lower:
            continue
        result.append({
            'index': i,
            'name': d['name'],
            'host_api': api,
            'channels': d['max_input_channels'],
            'sample_rate': int(d['default_samplerate']),
        })
    return result


class AudioCapture(QObject):
    """实时音频采集，运行在独立线程"""
    # 信号: numpy 数组(float32 mono), 采样率
    audio_frame = pyqtSignal(np.ndarray, int)
    error = pyqtSignal(str)

    def __init__(self, device_index=-1, sample_rate=48000, block_size=2048):
        super().__init__()
        self._device_index = device_index if device_index >= 0 else None
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._stream = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            self._stream = sd.InputStream(
                device=self._device_index,
                samplerate=self._sample_rate,
                channels=1,
                dtype='float32',
                blocksize=self._block_size,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._running = False
            self.error.emit(str(e))

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(self, indata, frames, time_info, status):
        if not self._running:
            return
        audio = indata[:, 0].copy()
        self.audio_frame.emit(audio, self._sample_rate)

    @property
    def is_running(self):
        return self._running

    @property
    def sample_rate(self):
        return self._sample_rate
