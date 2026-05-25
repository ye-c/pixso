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

    def _extract_video(self):
        """提取视频元数据"""
        try:
            probe = ffmpeg.probe(str(self._path))
            video_stream = next(
                (
                    stream
                    for stream in probe['streams']
                    if stream['codec_type'] == 'video'
                ),
                None,
            )

            if video_stream:
                # 从视频元数据中提取时间戳
                if 'tags' in video_stream and 'creation_time' in video_stream['tags']:
                    dt = datetime.strptime(
                        video_stream['tags']['creation_time'], '%Y-%m-%dT%H:%M:%S.%fZ'
                    )
                    self._meta.timestamp = dt.strftime('%Y%m%d%H%M%S')

                # 提取设备信息
                if 'tags' in video_stream and 'model' in video_stream['tags']:
                    self._meta.device = video_stream['tags']['model'].replace(" ", "_")

        except Exception as e:
            # 如果提取失败，使用文件创建时间
            self._meta.timestamp = datetime.fromtimestamp(
                self._path.stat().st_ctime
            ).strftime('%Y%m%d%H%M%S')
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
