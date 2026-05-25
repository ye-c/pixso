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
    is_fallback_time: bool = False

    @property
    def name(self):
        if self.device == "unknown":
            return f'{self.timestamp}_{self.original_name}.{self.suffix[1:]}'
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
        self._has_filename_time = self._parse_filename()
        self._extract()

    def _parse_filename(self) -> bool:
        """解析文件名，提取可能的时间戳、设备信息，并清理 original_name 防止重复追加前缀"""
        import re

        name = self._meta.original_name

        # 1. 尝试完整匹配: 时间戳_设备名_原始名 (例如: 20251116133758_XAVC_C0419)
        full_match = re.search(r'^(20\d{12})_([^_]+)_(.+)$', name)
        if full_match:
            self._meta.timestamp = full_match.group(1)
            self._meta.device = full_match.group(2)
            self._meta.original_name = full_match.group(3)
            return True

        # 2. 尝试匹配: 时间戳_原始名 (例如: 20260524110710_C0576)
        partial_match = re.search(r'^(20\d{12})_(.+)$', name)
        if partial_match:
            self._meta.timestamp = partial_match.group(1)
            self._meta.original_name = partial_match.group(2)
            return True

        # 3. 尝试从文件名开头匹配 14 位时间戳
        match = re.search(r'^(20\d{12})', name)
        if not match:
            # 4. 尝试在文件名的任意位置匹配 14 位时间戳
            match = re.search(r'(20\d{12})', name)

        if match:
            self._meta.timestamp = match.group(1)
            return True

        return False

    def _extract(self):
        """提取元数据"""
        if self._path.suffix.lower() in self._IMAGES:
            self._extract_image()
        elif self._path.suffix.lower() in self._VIDEOS:
            self._extract_video()
        else:
            raise ValueError(f"不支持的格式: {self._path.suffix}")

        if self._has_filename_time:
            # 如果从文件名解析到了信息，且 exif 提取没有覆盖或者覆盖的是 unknown，则保持文件名的信息
            pass

    def _extract_image(self):
        """提取图片EXIF数据"""
        with self._path.open('rb') as f:
            tags = process_file(f, details=False)

            # 提取设备型号
            if 'Image Model' in tags:
                model = str(tags['Image Model']).strip().replace(" ", "_")
                if self._meta.device == "unknown":
                    self._meta.device = model

            # 提取拍摄时间
            if 'EXIF DateTimeOriginal' in tags:
                dt = str(tags['EXIF DateTimeOriginal'])
                if not self._has_filename_time:
                    self._meta.timestamp = dt.replace(':', '').replace(' ', '')
            else:
                if not self._has_filename_time:
                    self._fallback_timestamp()

    def _parse_video_time(self, time_str: str) -> str:
        """尝试多种格式解析视频时间"""
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.000000Z',
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
        self._meta.is_fallback_time = True

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

            # 2. 提取时间戳
            creation_time = stream_tags.get('creation_time') or format_tags.get(
                'creation_time'
            )
            if creation_time:
                parsed_time = self._parse_video_time(creation_time)
                if parsed_time:
                    if not self._has_filename_time:
                        self._meta.timestamp = parsed_time
                else:
                    import typer

                    typer.echo(
                        f"Warning: Failed to parse video creation_time '{creation_time}' for {self._path}",
                        err=True,
                    )
                    if not self._has_filename_time:
                        self._fallback_timestamp()
            else:
                if not self._has_filename_time:
                    self._fallback_timestamp()

            # 3. 提取设备信息
            model = (
                stream_tags.get('model')
                or format_tags.get('model')
                or format_tags.get('com.apple.quicktime.model')
            )

            if model:
                model_str = str(model).strip().replace(" ", "_")
                if self._meta.device == "unknown":
                    self._meta.device = model_str

        except Exception as e:
            import typer

            typer.echo(
                f"Error extracting video metadata for {self._path}: {e}", err=True
            )
            # 解析完全失败时回退
            if not self._has_filename_time:
                self._fallback_timestamp()
            if self._meta.device == "unknown":
                self._meta.device = "unknown"

    @property
    def is_image(self) -> bool:
        return self._path.suffix.lower() in self._IMAGES

    @property
    def is_video(self) -> bool:
        return self._path.suffix.lower() in self._VIDEOS

    def rename(self):
        """生成标准化的文件名"""
        return self._meta.name
