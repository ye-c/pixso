import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import ffmpeg
from exifread import process_file

from .utils import get_hash8


@dataclass
class PixMeta:
    timestamp: str = None  # 20260520152033
    device: str = "unknown"
    original_name: str = None
    suffix: str = None
    is_unknown_time: bool = False

    @property
    def name(self):
        return f'{self.original_name}{self.suffix}'


class PixExif:
    _IMAGES = {".jpg", ".jpeg", ".png", ".cr2", ".arw", ".heif"}  # , ".heic"
    _VIDEOS = {".mov", ".mp4", ".avi", ".mkv"}

    # 设备名称映射表
    _DEVICE_MAP = {
        "iPhone_15_Pro": "iP15P",
        "iPhone_15_Pro_Max": "iP15PM",
        "iPhone_14_Pro": "iP14P",
        "ILCE-7CM2": "A7C2",
        "ILCE-7RM4": "A7R4",
        "ILCE-7M4": "A7M4",
        "GoPro": "GoPro",
    }

    def __init__(self, path):
        self._path = Path(path)

        self._meta = PixMeta(
            original_name=self._path.stem,
            suffix=self._path.suffix,
        )
        self.raw_tags = {}
        self._extract()

    def _extract(self):
        """提取元数据"""
        if self.is_image:
            self._extract_image()
        elif self.is_video:
            self._extract_video()
        else:
            raise ValueError(f"不支持的格式: {self._path.suffix}")

        if not self._meta.timestamp:
            self._meta.is_unknown_time = True
            self._fallback_timestamp()

    def _extract_image(self):
        """提取图片EXIF数据"""
        with self._path.open('rb') as f:
            tags = process_file(f, details=False)

            # 保存原始标签，只过滤掉二进制缩略图
            for k, v in tags.items():
                if k not in ('JPEGThumbnail', 'TIFFThumbnail'):
                    self.raw_tags[k] = str(v)

            # 提取设备型号
            if 'Image Model' in tags:
                model = str(tags['Image Model']).strip().replace(" ", "_")
                if self._meta.device == "unknown":
                    self._meta.device = model

            # 提取拍摄时间
            if 'EXIF DateTimeOriginal' in tags:
                dt = str(tags['EXIF DateTimeOriginal'])
                self._meta.timestamp = dt.replace(':', '').replace(' ', '')

    def _parse_video_time(self, time_str: str) -> str:
        """尝试多种格式解析视频时间，并处理 UTC+8 时区偏移"""
        from datetime import timedelta
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.000000Z',
            '%Y-%m-%dT%H:%M:%S%z',
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                # 如果是 UTC 时间 (包含 Z 或时区偏移为 0)，增加 8 小时
                if 'Z' in time_str or '+0000' in time_str or '.000000Z' in time_str:
                    dt = dt + timedelta(hours=8)
                return dt.strftime('%Y%m%d%H%M%S')
            except ValueError:
                continue
        return None

    def _fallback_timestamp(self):
        """回退使用文件系统创建时间"""
        self._meta.timestamp = datetime.fromtimestamp(
            self._path.stat().st_ctime
        ).strftime('%Y%m%d%H%M%S')

    def _extract_video(self):
        """提取视频元数据"""
        try:
            probe = ffmpeg.probe(str(self._path))

            # 1. 获取 format 层级和 stream 层级的 tags
            format_tags = probe.get('format', {}).get('tags', {})
            video_stream = next(
                (
                    stream
                    for stream in probe.get('streams', [])
                    if stream.get('codec_type') == 'video'
                ),
                {},
            )
            stream_tags = video_stream.get('tags', {})

            # 保存原始标签
            self.raw_tags = {
                **{f"format_{k}": v for k, v in format_tags.items()},
                **{f"stream_{k}": v for k, v in stream_tags.items()},
            }

            # 2. 提取时间戳
            creation_time = (
                format_tags.get('com.apple.quicktime.creationdate')
                or stream_tags.get('creation_time')
                or format_tags.get('creation_time')
            )
            if creation_time:
                parsed_time = self._parse_video_time(creation_time)
                if parsed_time:
                    self._meta.timestamp = parsed_time

            # 3. 提取设备信息
            model = (
                stream_tags.get('model')
                or format_tags.get('model')
                or format_tags.get('com.apple.quicktime.model')
            )

            if not model:
                encoder = str(stream_tags.get('encoder', '') or stream_tags.get('handler_name', ''))
                if 'GoPro' in encoder:
                    model = 'GoPro'

            if not model:
                brand = format_tags.get('major_brand')
                if brand and brand.lower().strip() not in ('isom', 'mp41', 'mp42', 'qt', 'avc1'):
                    model = brand

            if model:
                model_str = str(model).strip().replace(" ", "_")
                if self._meta.device == "unknown":
                    self._meta.device = model_str

        except Exception:
            if self._meta.device == "unknown":
                self._meta.device = "unknown"

    @property
    def is_image(self) -> bool:
        return self._path.suffix.lower() in self._IMAGES

    @property
    def is_video(self) -> bool:
        return self._path.suffix.lower() in self._VIDEOS

    def get_device_short(self) -> str:
        """获取简短的设备代号"""
        device = self._meta.device
        # 尝试精确匹配
        if device in self._DEVICE_MAP:
            return self._DEVICE_MAP[device]

        # 尝试模糊匹配 (部分匹配)
        for full, short in self._DEVICE_MAP.items():
            if full.lower() in device.lower() or device.lower() in full.lower():
                return short

        return "unknown"

    def rename(self):
        """生成标准化的文件名: {timestamp}_{device_short}_{hash8}{suffix}"""
        device_short = self.get_device_short()
        hash8 = get_hash8(self._path)
        return f"{self._meta.timestamp}_{device_short}_{hash8}{self._meta.suffix}"
