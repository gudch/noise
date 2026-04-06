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
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                    self._data = json.load(f)
                return
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[CONFIG] ⚠ config.json 损坏: {e}")
                # 尝试从备份恢复
                bak = CONFIG_PATH + ".bak"
                if os.path.exists(bak):
                    try:
                        with open(bak, "r", encoding="utf-8-sig") as f:
                            self._data = json.load(f)
                        # 用备份覆盖损坏的文件
                        self.save()
                        print("[CONFIG] ✓ 已从 config.json.bak 恢复")
                        return
                    except Exception:
                        pass
                print("[CONFIG] 使用默认配置启动")
                self._data = {}

    def save(self):
        # 保存前先备份当前文件
        if os.path.exists(CONFIG_PATH):
            try:
                import shutil
                shutil.copy2(CONFIG_PATH, CONFIG_PATH + ".bak")
            except Exception:
                pass
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
