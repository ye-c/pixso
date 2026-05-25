from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import ffmpeg
from exifread import process_file


@dataclass
class PixMeta:
    timestamp = "timestamp"  # 20260520152033
    device: str = "unknown"
    original_name: str = None
    suffix: str = None

    @property
    def name(self):
        return f'{self.timestamp}_{self.device}_{self.original_name}.{self.suffix[1:]}'


class PixExif:
    _IMAGES = {".jpg", ".jpeg", ".png", ".cr2", ".arw"}  # , ".heic"
    _VIDEOS = {".mov", ".mp4", ".avi", ".mkv"}

    def __init__(self, path):
        self._path = Path(path)
        self._meta = PixMeta(
            original_name=self._path.stem,
            suffix=self._path.suffix,
        )
        self._extract()

    def _extract(self):
        """提取元数据"""
        if self._path.suffix.lower() in self._IMAGES:
            self._extract_image()
        elif self._path.suffix.lower() in self._VIDEOS:
            self._extract_video()
        else:
            raise ValueError(f"不支持的格式: {self._path.suffix}")

    def _extract_image(self):
        """提取图片EXIF数据"""
        with self._path.open('rb') as f:
            tags = process_file(f, details=False)

            # 提取设备型号
            if 'Image Model' in tags:
                self._meta.device = str(tags['Image Model']).strip().replace(" ", "_")

            # 提取拍摄时间
            if 'EXIF DateTimeOriginal' in tags:
                dt = str(tags['EXIF DateTimeOriginal'])
                self._meta.timestamp = dt.replace(':', '').replace(' ', '')

    def _parse_video_time(self, time_str: str) -> str:
        """尝试多种格式解析视频时间"""
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.000000Z'
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
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
                (stream for stream in probe.get('streams', []) if stream.get('codec_type') == 'video'),
                {}
            )
            stream_tags = video_stream.get('tags', {})

            # 2. 提取时间戳
            creation_time = stream_tags.get('creation_time') or format_tags.get('creation_time')
            if creation_time:
                parsed_time = self._parse_video_time(creation_time)
                if parsed_time:
                    self._meta.timestamp = parsed_time
                else:
                    self._fallback_timestamp()
            else:
                self._fallback_timestamp()

            # 3. 提取设备信息
            model = (
                stream_tags.get('model') or
                format_tags.get('model') or
                format_tags.get('com.apple.quicktime.model')
            )

            if model:
                self._meta.device = str(model).strip().replace(" ", "_")
            else:
                self._meta.device = "video_device"

        except Exception:
            # 解析完全失败时回退
            self._fallback_timestamp()
            self._meta.device = "video_device"

    @property
    def is_image(self) -> bool:
        return self._path.suffix.lower() in self._IMAGES

    @property
    def is_video(self) -> bool:
        return self._path.suffix.lower() in self._VIDEOS

    def rename(self):
        """生成标准化的文件名"""
        return self._meta.name
