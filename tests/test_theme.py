import io
import struct

import pytest
from PIL import Image
from sqlalchemy import select

from app.common.storage import public_storage
from app.core.config import settings
from app.domains.theme.media import mp4_duration
from app.domains.theme.models import ThemeAsset, ThemePreset
from tests.factories import make_student


def make_gif(size=(8, 8)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "GIF")
    return out.getvalue()


def make_mp4(seconds: float, version: int = 0) -> bytes:
    ftyp = struct.pack(">I4s", 24, b"ftyp") + b"isom" + b"\x00\x00\x02\x00" + b"isomiso2"
    timescale = 1000
    if version == 0:
        mvhd_body = struct.pack(">B3xIIII", 0, 0, 0, timescale, int(seconds * timescale)) + b"\x00" * 80
    else:
        mvhd_body = struct.pack(">B3xQQIQ", 1, 0, 0, timescale, int(seconds * timescale)) + b"\x00" * 80
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    return ftyp + moov


async def upload(client, data, name="bg.gif"):
    return await client.post("/api/me/theme/assets", files={"file": (name, data, "application/octet-stream")})


def theme_body(**bg):
    return {"background": {"type": "NONE", **bg}, "fontScale": "M", "textShadow": True,
            "pauseOnLowPower": True, "autoplayOnDataSaver": False}


def test_mp4_duration_parser():
    assert mp4_duration(make_mp4(14.8)) == pytest.approx(14.8, abs=0.01)
    assert mp4_duration(make_mp4(61, version=1)) == 61
    assert mp4_duration(b"\x00\x00\x00\x18ftypisom" + b"0" * 20) is None


async def test_default_theme_and_reset(make_client, db):
    c = await make_client(await make_student(db))
    t = (await c.get("/api/me/theme")).json()
    assert t == {"background": {"type": "NONE", "source": None, "presetId": None, "assetId": None, "url": None,
                                "thumbnailUrl": None, "fit": "COVER", "opacity": 100, "dim": 0, "blur": 0},
                 "fontScale": "M", "textShadow": True, "pauseOnLowPower": True, "autoplayOnDataSaver": False,
                 "updatedAt": None}
    saved = await c.put("/api/me/theme", json={**theme_body(opacity=80, dim=20), "fontScale": "XL", "textShadow": False})
    assert saved.status_code == 200 and saved.json()["fontScale"] == "XL" and saved.json()["updatedAt"].endswith("+09:00")
    assert (await c.get("/api/me/theme")).json()["background"]["dim"] == 20
    reset = await c.delete("/api/me/theme")
    assert reset.status_code == 200 and reset.json() == t
    assert (await c.get("/api/me/theme")).json() == t
    assert (await (await make_client()).get("/api/me/theme")).status_code == 401


async def test_presets_and_preset_background(make_client, db):
    db.add_all([ThemePreset(type="GIF", name="밤하늘 별", file_url="https://cdn.example.com/p/stars.gif",
                            thumbnail_url="https://cdn.example.com/p/stars.jpg", sort_order=2),
                ThemePreset(type="MP4", name="바다", file_url="https://cdn.example.com/p/sea.mp4", sort_order=1)])
    await db.commit()
    c = await make_client(await make_student(db))
    all_items = (await c.get("/api/theme/presets")).json()["items"]
    assert [i["name"] for i in all_items] == ["바다", "밤하늘 별"]
    gif = (await c.get("/api/theme/presets", params={"type": "GIF"})).json()["items"]
    assert gif[0]["url"].endswith("stars.gif") and gif[0]["thumbnailUrl"].endswith("stars.jpg")
    pid = gif[0]["presetId"]

    ok = await c.put("/api/me/theme", json=theme_body(type="GIF", source="PRESET", presetId=pid, fit="TILE", opacity=80))
    assert ok.status_code == 200
    bg = ok.json()["background"]
    assert bg["url"].endswith("stars.gif") and bg["fit"] == "TILE" and bg["presetId"] == pid and bg["assetId"] is None

    for bad in (theme_body(type="GIF", source="PRESET"),                       # presetId 없음
                theme_body(type="MP4", source="PRESET", presetId=pid),          # 종류 불일치
                theme_body(type="GIF", source="PRESET", presetId=999),
                theme_body(type="GIF")):                                         # source 없음
        r = await c.put("/api/me/theme", json=bad)
        assert r.status_code == 400 and r.json()["code"] == "INVALID_BACKGROUND", bad
    for field in ("opacity", "dim", "blur"):
        for value in (-1, 101):
            r = await c.put("/api/me/theme", json=theme_body(**{field: value}))
            assert r.status_code == 400 and r.json()["code"] == "VALIDATION_FAILED"
    # 실패한 저장은 기존 설정을 바꾸지 않는다
    assert (await c.get("/api/me/theme")).json()["background"]["presetId"] == pid

    mp4 = (await c.get("/api/theme/presets", params={"type": "MP4"})).json()["items"][0]["presetId"]
    forced = await c.put("/api/me/theme", json=theme_body(type="MP4", source="PRESET", presetId=mp4, fit="TILE"))
    assert forced.json()["background"]["fit"] == "COVER"  # MP4는 항상 COVER
    # NONE이면 source·id는 비운다
    none = await c.put("/api/me/theme", json=theme_body(type="NONE", source="PRESET", presetId=mp4))
    assert none.json()["background"]["source"] is None and none.json()["background"]["presetId"] is None


async def test_upload_gif_and_mp4(make_client, db):
    s = await make_student(db)
    c = await make_client(s)
    g = await upload(c, make_gif())
    assert g.status_code == 201
    out = g.json()
    assert out["type"] == "GIF" and out["url"].startswith("/media/themes/") and out["thumbnailUrl"].endswith(".jpg")
    assert out["durationSec"] is None and out["sizeBytes"] == len(make_gif())
    assert (await public_storage().read(out["thumbnailUrl"].removeprefix("/media/")))[:3] == b"\xff\xd8\xff"  # 썸네일 JPEG
    served = await c.get(out["url"])  # 정적 서빙
    assert served.status_code == 200 and served.content == make_gif()

    m = await upload(c, make_mp4(14.8), "loop.mp4")
    assert m.status_code == 201 and m.json()["type"] == "MP4" and m.json()["durationSec"] == pytest.approx(14.8, abs=0.01)


async def test_upload_rejections(make_client, db):
    c = await make_client(await make_student(db))
    assert (await upload(c, b"not an image at all")).status_code == 415
    assert (await upload(c, b"GIF89a-but-broken")).status_code == 415       # 형식은 맞지만 깨진 GIF
    assert (await upload(c, b"\x89PNG\r\n\x1a\n" + b"0" * 40)).status_code == 415  # PNG는 허용 안 함
    long = await upload(c, make_mp4(31), "long.mp4")
    assert long.status_code == 400 and long.json()["code"] == "VIDEO_TOO_LONG"
    assert (await upload(c, make_mp4(30), "ok.mp4")).status_code == 201     # 30초 이하는 허용
    bad_mp4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 40
    assert (await upload(c, bad_mp4, "broken.mp4")).status_code == 415
    settings.theme_gif_max_bytes = 10
    try:
        too_big = await upload(c, make_gif())
        assert too_big.status_code == 413 and too_big.json()["code"] == "FILE_TOO_LARGE"
    finally:
        settings.theme_gif_max_bytes = 10 * 1024 * 1024


async def test_asset_limit_delete_and_background_fallback(make_client, db):
    s, other = await make_student(db), await make_student(db, "타인")
    c, oc = await make_client(s), await make_client(other)
    ids = []
    for _ in range(settings.theme_asset_limit):
        r = await upload(c, make_gif())
        assert r.status_code == 201
        ids.append(r.json())
    limit = await upload(c, make_gif())
    assert limit.status_code == 409 and limit.json()["code"] == "ASSET_LIMIT_EXCEEDED"
    assert (await upload(oc, make_gif())).status_code == 201  # 한도는 사용자별

    first = ids[0]
    ok = await c.put("/api/me/theme", json={**theme_body(type="GIF", source="UPLOAD", assetId=first["assetId"], dim=40),
                                           "fontScale": "L"})
    assert ok.status_code == 200 and ok.json()["background"]["url"] == first["url"]
    # 남의 파일·종류 불일치는 사용 불가
    foreign = (await upload(oc, make_gif())).json()["assetId"]
    assert (await c.put("/api/me/theme", json=theme_body(type="GIF", source="UPLOAD", assetId=foreign))).json()["code"] == "INVALID_BACKGROUND"
    assert (await c.put("/api/me/theme", json=theme_body(type="MP4", source="UPLOAD", assetId=first["assetId"]))).status_code == 400
    assert (await c.put("/api/me/theme", json=theme_body(type="GIF", source="UPLOAD", assetId="nope"))).status_code == 400

    # 남의 파일 삭제는 404
    assert (await oc.delete(f"/api/me/theme/assets/{first['assetId']}")).status_code == 404
    assert (await c.delete("/api/me/theme/assets/nope")).status_code == 404
    # 현재 배경으로 쓰는 파일을 지우면 배경만 NONE, 나머지 설정은 유지
    assert (await c.delete(f"/api/me/theme/assets/{first['assetId']}")).status_code == 204
    t = (await c.get("/api/me/theme")).json()
    assert t["background"]["type"] == "NONE" and t["background"]["assetId"] is None
    assert t["background"]["dim"] == 40 and t["fontScale"] == "L"
    assert await db.scalar(select(ThemeAsset).where(ThemeAsset.asset_id == first["assetId"])) is None
    assert (await c.get(first["url"])).status_code == 404  # 파일도 삭제
    assert (await upload(c, make_gif())).status_code == 201  # 한도에 여유가 생김

    # 초기화해도 업로드한 파일은 남는다
    keep = ids[1]
    await c.put("/api/me/theme", json=theme_body(type="GIF", source="UPLOAD", assetId=keep["assetId"]))
    await c.delete("/api/me/theme")
    assert (await c.get(keep["url"])).status_code == 200
    assert (await c.put("/api/me/theme", json=theme_body(type="GIF", source="UPLOAD", assetId=keep["assetId"]))).status_code == 200
