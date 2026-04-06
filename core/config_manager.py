"""配置管理器"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


class ConfigManager:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                self._data = json.load(f)

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=4)

    def get(self, section, key=None, default=None):
        sec = self._data.get(section, {})
        if key is None:
            return sec
        return sec.get(key, default)

    def set(self, section, key, value):
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value

    @property
    def device(self):
        return self._data.get("device", {})

    @property
    def detection(self):
        return self._data.get("detection", {})

    @property
    def recording(self):
        return self._data.get("recording", {})

    @property
    def alert(self):
        return self._data.get("alert", {})

    @property
    def calibration(self):
        return self._data.get("calibration", {})

    @property
    def ui(self):
        return self._data.get("ui", {})
