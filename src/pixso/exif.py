import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import ffmpeg
from exifread import process_file

from .utils import get_clean_name, parse_filename_stem


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

    def __init__(self, path):
        self._path = Path(path)

        stem = self._path.stem
        _, clean_name = parse_filename_stem(stem)

        # 剥离冲突后缀 (如 _1, _2)
        clean_name = re.sub(r'_\d+$', '', clean_name)

        self._meta = PixMeta(
            original_name=clean_name,
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
            # print(probe)

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
                else:
                    print(
                        f"Warning: Failed to parse video creation_time '{creation_time}' for {self._path}"
                    )

            # 3. 提取设备信息
            model = (
                stream_tags.get('model')
                or format_tags.get('model')
                or format_tags.get('com.apple.quicktime.model')
            )

            # 尝试从 encoder 或 handler_name 中提取特征 (例如 GoPro)
            if not model:
                encoder = str(stream_tags.get('encoder', '') or stream_tags.get('handler_name', ''))
                if 'GoPro' in encoder:
                    model = 'GoPro'

            # 如果没有明确的 model，尝试使用 major_brand
            if not model:
                brand = format_tags.get('major_brand')
                # 过滤掉太宽泛的通用格式名
                if brand and brand.lower().strip() not in ('isom', 'mp41', 'mp42', 'qt', 'avc1'):
                    model = brand

            if not model:
                # 尝试从 compatible_brands 提取有意义的名字 (比如 XAVCmp42iso6 -> XAVC)
                comp_brands = str(format_tags.get('compatible_brands', ''))
                if 'XAVC' in comp_brands.upper():
                    model = 'XAVC'
                elif 'avc1' in comp_brands.lower():
                    model = 'AVC'

            if model:
                model_str = str(model).strip().replace(" ", "_")
                if self._meta.device == "unknown":
                    self._meta.device = model_str

        except Exception as e:
            print(f"Error extracting video metadata for {self._path}: {e}")
            if self._meta.device == "unknown":
                self._meta.device = "unknown"

    @property
    def is_image(self) -> bool:
        return self._path.suffix.lower() in self._IMAGES

    @property
    def is_video(self) -> bool:
        return self._path.suffix.lower() in self._VIDEOS

    def rename(self):
        """生成标准化的文件名: {timestamp}_{clean_device}_{clean_name}"""
        clean_device = get_clean_name(self._meta.device)
        # 核心逻辑：dirty_name 也先清洗，再匹配剥离 device
        dirty_name_clean = get_clean_name(self._meta.original_name)

        clean_name = dirty_name_clean
        if clean_device and clean_device != 'unknown':
            # 如果 clean_name 以 clean_device 开头，剥离它
            if clean_name.lower().startswith(clean_device.lower()):
                # 剥离 clean_device
                clean_name = clean_name[len(clean_device):]
                # 剥离可能残留的下划线等分隔符（因为 get_clean_name 已经去掉了非字母数字，所以这里不需要再剥离下划线）
                # 但是，如果原始名是 ILCE7CM2_DSC01986，get_clean_name 之后变成 ILCE7CM2DSC01986
                # 剥离 ILCE7CM2 之后剩下 DSC01986，这正是我们想要的。

                # 如果剥离后空了（说明原文件名就是设备名），则还原回设备名
                if not clean_name:
                    clean_name = clean_device

        return f"{self._meta.timestamp}_{clean_device}_{clean_name}{self._meta.suffix}"
