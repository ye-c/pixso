import json
import os
from typing import Dict, Set

# 默认配置
DEFAULT_IMAGES = {".jpg", ".jpeg", ".png", ".cr2", ".arw", ".heif", ".heic"}
DEFAULT_VIDEOS = {".mov", ".mp4", ".avi", ".mkv"}
DEFAULT_DEVICE_MAP = {
    "iPhone_15_Pro_Max": "iPone15PM",
    "iPhone_15_Pro": "iPone15P",
    "iPhone_15": "iPone15",
    "iPhone_14_Pro": "iPone14P",
    "ILCE-7CM2": "A7C2",
    "ILCE-7RM4": "A7R4",
    "ILCE-7M4": "A7M4",
    "GoPro": "GoPro",
    "Canon_EOS_550D": "CanonEOS550D",
}


def get_config_set(env_name: str, default: Set[str]) -> Set[str]:
    val = os.environ.get(env_name)
    if not val:
        return default
    return {s.strip() for s in val.split(",")}


def get_config_dict(env_name: str, default: Dict[str, str]) -> Dict[str, str]:
    val = os.environ.get(env_name)
    if not val:
        return default
    try:
        # 支持 JSON 格式的环境变量
        return json.loads(val)
    except json.JSONDecodeError:
        # 支持 key:value,key:value 格式
        result = default.copy()
        for item in val.split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                result[k.strip()] = v.strip()
        return result


# 导出的配置对象
class Config:
    def __init__(self):
        self.IMAGES = get_config_set("PIXSO_IMAGES", DEFAULT_IMAGES)
        self.VIDEOS = get_config_set("PIXSO_VIDEOS", DEFAULT_VIDEOS)
        self.DEVICE_MAP = get_config_dict("PIXSO_DEVICE_MAP", DEFAULT_DEVICE_MAP)

        # 预先计算所有扩展名
        self.ALL_EXTENSIONS = {ext.lower() for ext in self.IMAGES | self.VIDEOS}


config = Config()
