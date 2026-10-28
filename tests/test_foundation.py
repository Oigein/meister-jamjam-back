from tests.factories import make_student


async def test_health(anon):
    assert (await anon.get("/health")).json() == {"status": "ok"}


async def test_unauthorized_error_format(anon):
    r = await anon.get("/api/me")
    assert r.status_code == 401
    assert r.json() == {"code": "UNAUTHORIZED", "message": "로그인이 필요합니다."}


async def test_validation_error_is_400_with_field_errors(make_client, db):
    user = await make_student(db)
    c = await make_client(user)
    r = await c.get("/api/classes/abc/1/students")
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_FAILED"
    assert r.json()["fieldErrors"][0]["field"] == "grade"


async def test_origin_is_enforced_on_unsafe_methods(make_client, db):
    user = await make_student(db)
    bad = await make_client(user, origin="https://evil.example")
    assert (await bad.patch("/api/me/profile", json={})).status_code == 403
    missing = await make_client(user, origin=None)
    assert (await missing.post("/auth/logout")).status_code == 403
    # 조회(GET)는 Origin 검사를 하지 않는다
    assert (await missing.get("/api/me")).status_code == 200


async def test_unknown_route_uses_common_error_format(anon):
    r = await anon.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"
