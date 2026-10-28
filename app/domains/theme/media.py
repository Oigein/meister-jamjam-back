"""테마 배경 파일(GIF·MP4) 검사와 썸네일 생성."""
import asyncio
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def _boxes(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(buf[pos : pos + 4], "big")
        kind = buf[pos + 4 : pos + 8]
        header = 8
        if size == 1:
            size = int.from_bytes(buf[pos + 8 : pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind, pos + header, min(pos + size, end)
        pos += size


def mp4_duration(data: bytes) -> float | None:
    """moov/mvhd 박스에서 재생 길이(초)를 읽는다. 읽을 수 없으면 None."""
    for kind, start, end in _boxes(data, 0, len(data)):
        if kind != b"moov":
            continue
        for kind2, s2, _ in _boxes(data, start, end):
            if kind2 != b"mvhd":
                continue
            if data[s2] == 1:
                timescale = int.from_bytes(data[s2 + 20 : s2 + 24], "big")
                duration = int.from_bytes(data[s2 + 24 : s2 + 32], "big")
            else:
                timescale = int.from_bytes(data[s2 + 12 : s2 + 16], "big")
                duration = int.from_bytes(data[s2 + 16 : s2 + 20], "big")
            return duration / timescale if timescale else None
    return None


def gif_thumbnail(data: bytes) -> bytes | None:
    """GIF의 첫 프레임을 JPEG로. GIF가 아니거나 깨졌으면 None."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.seek(0)
            out = io.BytesIO()
            img.convert("RGB").save(out, "JPEG", quality=80)
            return out.getvalue()
    except Exception:
        return None


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _run_ffmpeg(args: list[str], data: bytes, suffix: str) -> bytes | None:
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.mp4", Path(tmp) / f"out{suffix}"
        src.write_bytes(data)
        try:
            subprocess.run([ffmpeg, "-y", "-i", str(src), *args, str(dst)], check=True, capture_output=True, timeout=60)
            return dst.read_bytes()
        except (subprocess.SubprocessError, OSError):
            return None


async def mp4_thumbnail(data: bytes) -> bytes | None:
    """ffmpeg가 있을 때만 첫 프레임을 만든다. 없으면 None (정지 화면 없이 동작)."""
    return await asyncio.to_thread(_run_ffmpeg, ["-frames:v", "1", "-q:v", "3"], data, ".jpg")


async def strip_audio(data: bytes) -> bytes:
    """오디오 트랙을 제거한다. ffmpeg가 없거나 실패하면 원본을 그대로 둔다."""
    stripped = await asyncio.to_thread(_run_ffmpeg, ["-c", "copy", "-an", "-movflags", "+faststart"], data, ".mp4")
    return stripped or data
