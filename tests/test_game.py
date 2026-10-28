import pytest

from app.common.enums import DrawType
from app.domains.game.pinball import draw_winners
from app.domains.game.rng import SeededRandom
from app.domains.game.seat import SeatPlan, assign_seats
from app.domains.game.service import replay
from tests.factories import make_admin, make_student, make_teacher


# ---------- 순수 로직 ----------


def test_rng_is_deterministic_and_seed_sensitive():
    a, b = SeededRandom("seed-1"), SeededRandom("seed-1")
    assert [a.randbelow(1000) for _ in range(50)] == [b.randbelow(1000) for _ in range(50)]
    assert SeededRandom("seed-1").shuffle(list(range(20))) != SeededRandom("seed-2").shuffle(list(range(20)))
    # 알고리즘 v1 고정값 (바뀌면 과거 결과를 검증할 수 없게 된다)
    assert SeededRandom("fixed").shuffle(list(range(1, 11))) == [3, 10, 2, 5, 6, 9, 4, 1, 8, 7]
    assert SeededRandom("fixed").randbelow(100) == 16


def test_rng_uniformity_roughly():
    rng = SeededRandom("uniform")
    counts = [0] * 6
    for _ in range(6000):
        counts[rng.randbelow(6)] += 1
    assert all(800 < c < 1200 for c in counts)
    with pytest.raises(ValueError):
        rng.randbelow(0)


def test_shuffle_is_a_permutation_and_does_not_mutate():
    items = list(range(30))
    out = SeededRandom("x").shuffle(items)
    assert sorted(out) == items and items == list(range(30))
    assert SeededRandom("x").shuffle([]) == [] and SeededRandom("x").shuffle([7]) == [7]


def test_pinball_winners():
    cands = [1, 2, 3, 4, 5, 6, 7, 8]
    w = draw_winners("seed", cands, 3)
    assert len(w) == 3 and len(set(w)) == 3 and set(w) <= set(cands)
    assert draw_winners("seed", cands, 3) == w and draw_winners("seed", list(reversed(cands)), 3) == w  # 입력 순서 무관
    with pytest.raises(ValueError):
        draw_winners("seed", cands, 9)
    with pytest.raises(ValueError):
        draw_winners("seed", cands, 0)


def test_seat_assignment_rules():
    plan = SeatPlan(4, 4, {(4, 4)}, list(range(1, 16)), fixed={3: (1, 2)})
    out = assign_seats("seed", plan)
    seats = [(r, c) for r, c, _, _ in out.placements]
    assert len(out.placements) == 15 and len(set(seats)) == 15 and (4, 4) not in seats
    assert (1, 2, 3, True) in out.placements and out.empty == [] and out.warnings == []
    assert assign_seats("seed", plan) == out  # 같은 시드 = 같은 결과
    assert assign_seats("other", plan) != out


def test_seat_avoid_previous():
    students = list(range(1, 9))
    previous = {n: (1, n) for n in students}
    plan = SeatPlan(2, 4, set(), students, avoid_previous=True, previous=previous)
    out = assign_seats("seed", plan)
    assert all(previous[n] != (r, c) for r, c, n, _ in out.placements) and out.warnings == []

    # 자리가 학생 수와 같고 직전 자리와 같은 배치를 피할 수 없는 경우 (자리 1개)
    stuck = assign_seats("s", SeatPlan(1, 1, set(), [1], avoid_previous=True, previous={1: (1, 1)}))
    assert stuck.warnings == ["PREVIOUS_SEAT_UNAVOIDABLE"] and stuck.placements == [(1, 1, 1, False)]


def test_seat_empty_seats_reported():
    out = assign_seats("s", SeatPlan(2, 2, set(), [1, 2, 3]))
    assert len(out.empty) == 1


# ---------- API ----------


@pytest.fixture
async def klass(db, make_client):
    students = [await make_student(db, f"학생{n:02d}", 2, 1, n) for n in range(1, 11)]
    await make_student(db, "다른반", 2, 2, 1)
    teacher = await make_teacher(db, "박선생")
    return {"students": students, "teacher": teacher, "t": await make_client(teacher),
            "s": await make_client(students[0]), "ids": [s.user_id for s in students]}


def seat_body(**over):
    base = {"grade": 2, "classNo": 1, "layout": {"rows": 4, "cols": 4, "groupShape": None, "disabledSeats": [{"row": 4, "col": 4}]},
            "excludedStudentIds": [], "fixedSeats": [], "avoidPreviousSeat": False}
    base.update(over)
    return base


async def test_seat_draw_response_and_persistence(klass):
    t = klass["t"]
    ids = klass["ids"]
    r = await t.post("/api/draws/seats", json=seat_body(excludedStudentIds=[ids[9]],
                                                      fixedSeats=[{"studentId": ids[2], "row": 1, "col": 2}]))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["type"] == "SEAT" and len(d["seed"]) == 64 and d["grade"] == 2 and d["classNo"] == 1
    assert len(d["assignments"]) == 9 and len(d["emptySeats"]) == 15 - 9 and d["warnings"] == []
    fixed = [a for a in d["assignments"] if a["fixed"]]
    assert fixed == [{"row": 1, "col": 2, "studentId": ids[2], "number": 3, "name": "학생03", "fixed": True}]
    assert {a["studentId"] for a in d["assignments"]} == set(ids) - {ids[9]}  # 제외 학생은 배치하지 않는다
    assert all((a["row"], a["col"]) != (4, 4) for a in d["assignments"]) and {"row": 4, "col": 4} not in d["emptySeats"]
    assert (await t.get(f"/api/draws/{d['drawId']}")).json() == d  # 다시 보기


async def test_seat_draw_errors(klass):
    t, ids = klass["t"], klass["ids"]
    post = lambda **o: t.post("/api/draws/seats", json=seat_body(**o))  # noqa: E731
    small = {"rows": 2, "cols": 2, "groupShape": None, "disabledSeats": []}
    assert (await post(layout=small)).json()["code"] == "NOT_ENOUGH_SEATS"
    cases = [
        [{"studentId": ids[0], "row": 5, "col": 1}],                                   # 범위 밖
        [{"studentId": ids[0], "row": 4, "col": 4}],                                   # 사용 안 하는 자리
        [{"studentId": ids[0], "row": 1, "col": 1}, {"studentId": ids[1], "row": 1, "col": 1}],  # 자리 중복
        [{"studentId": ids[0], "row": 1, "col": 1}, {"studentId": ids[0], "row": 1, "col": 2}],  # 학생 중복
    ]
    for fixed in cases:
        assert (await post(fixedSeats=fixed)).json()["code"] == "FIXED_SEAT_CONFLICT", fixed
    assert (await post(fixedSeats=[{"studentId": ids[0], "row": 1, "col": 1}], excludedStudentIds=[ids[0]])).json()["code"] == "FIXED_SEAT_CONFLICT"
    assert (await post(excludedStudentIds=["nope"])).json()["code"] == "STUDENT_NOT_IN_CLASS"
    assert (await post(fixedSeats=[{"studentId": "nope", "row": 1, "col": 1}])).json()["code"] == "STUDENT_NOT_IN_CLASS"
    assert (await post(layout={**small, "rows": 11})).status_code == 400
    assert (await post(layout={**small, "groupShape": "2by2"})).status_code == 400
    assert (await post(grade=4)).json()["code"] == "CLASS_NOT_FOUND"
    assert (await post(layout={"rows": 2, "cols": 2, "disabledSeats": [{"row": 9, "col": 9}]})).json()["code"] == "FIXED_SEAT_CONFLICT"


async def test_draw_permissions(klass, make_client, db):
    ids = klass["ids"]
    own = klass["s"]  # 2학년 1반 학생
    assert (await own.post("/api/draws/seats", json=seat_body())).status_code == 201
    other_class = await make_client(await make_student(db, "타반학생", 3, 1, 1))
    assert (await other_class.post("/api/draws/seats", json=seat_body())).status_code == 403
    assert (await other_class.post("/api/draws/pinball", json={"grade": 2, "classNo": 1, "mode": "DROP", "winnerCount": 1})).status_code == 403
    admin = await make_client(await make_admin(db))
    assert (await admin.post("/api/draws/pinball", json={"grade": 2, "classNo": 1, "mode": "DROP", "winnerCount": 1})).status_code == 201
    assert (await (await make_client()).post("/api/draws/seats", json=seat_body())).status_code == 401
    assert ids


async def test_avoid_previous_seat_via_api(klass):
    t = klass["t"]
    first = (await t.post("/api/draws/seats", json=seat_body())).json()
    prev = {a["studentId"]: (a["row"], a["col"]) for a in first["assignments"]}
    second = (await t.post("/api/draws/seats", json=seat_body(avoidPreviousSeat=True))).json()
    assert second["warnings"] == []
    assert all(prev[a["studentId"]] != (a["row"], a["col"]) for a in second["assignments"])
    ver = (await t.get(f"/api/draws/{second['drawId']}/verification")).json()
    assert ver["input"]["options"]["avoidPreviousSeat"] is True and len(ver["input"]["options"]["previousSeats"]) == 10


async def test_pinball_chain_excludes_previous_winners(klass):
    t, ids = klass["t"], klass["ids"]
    body = {"grade": 2, "classNo": 1, "mode": "BUMPER", "winnerCount": 4, "excludedStudentIds": [ids[0]],
            "allowDuplicate": False}
    first = (await t.post("/api/draws/pinball", json=body)).json()
    assert first["type"] == "PINBALL" and first["mode"] == "BUMPER" and first["candidateCount"] == 9
    assert [w["order"] for w in first["winners"]] == [1, 2, 3, 4] and ids[0] not in {w["studentId"] for w in first["winners"]}
    won1 = {w["studentId"] for w in first["winners"]}

    second = (await t.post("/api/draws/pinball", json={**body, "winnerCount": 3, "previousDrawId": first["drawId"]})).json()
    won2 = {w["studentId"] for w in second["winners"]}
    assert second["candidateCount"] == 5 and not (won1 & won2) and ids[0] not in won2  # 이미 뽑힌 학생 제외

    third = await t.post("/api/draws/pinball", json={**body, "winnerCount": 3, "previousDrawId": second["drawId"]})
    assert third.json()["code"] == "NOT_ENOUGH_CANDIDATES"  # 남은 2명 < 3명
    dup = (await t.post("/api/draws/pinball", json={**body, "winnerCount": 5, "previousDrawId": first["drawId"], "allowDuplicate": True})).json()
    assert dup["candidateCount"] == 9

    assert (await t.post("/api/draws/pinball", json={**body, "winnerCount": 0})).status_code == 400
    assert (await t.post("/api/draws/pinball", json={**body, "winnerCount": 10})).json()["code"] == "NOT_ENOUGH_CANDIDATES"
    assert (await t.post("/api/draws/pinball", json={**body, "previousDrawId": "nope"})).json()["code"] == "INVALID_PREVIOUS_DRAW"
    seat = (await t.post("/api/draws/seats", json=seat_body())).json()
    assert (await t.post("/api/draws/pinball", json={**body, "previousDrawId": seat["drawId"]})).json()["code"] == "INVALID_PREVIOUS_DRAW"
    other = (await t.post("/api/draws/pinball", json={"grade": 2, "classNo": 2, "mode": "DROP", "winnerCount": 1})).json()
    assert (await t.post("/api/draws/pinball", json={**body, "previousDrawId": other["drawId"]})).json()["code"] == "INVALID_PREVIOUS_DRAW"
    assert (await t.post("/api/draws/pinball", json={**body, "mode": "FLY"})).status_code == 400
    assert (await t.post("/api/draws/pinball", json={**body, "excludedStudentIds": ["x"]})).json()["code"] == "STUDENT_NOT_IN_CLASS"


async def test_verification_replays_to_same_result(klass):
    t, ids = klass["t"], klass["ids"]
    seat = (await t.post("/api/draws/seats", json=seat_body(avoidPreviousSeat=False,
                                                          fixedSeats=[{"studentId": ids[4], "row": 2, "col": 2}]))).json()
    pin = (await t.post("/api/draws/pinball", json={"grade": 2, "classNo": 1, "mode": "DROP", "winnerCount": 3,
                                                   "excludedStudentIds": [ids[1]]})).json()
    for draw, kind in ((seat, DrawType.SEAT), (pin, DrawType.PINBALL)):
        v = (await klass["s"].get(f"/api/draws/{draw['drawId']}/verification")).json()  # 로그인한 누구나
        assert v["seed"] == draw["seed"] and v["algorithm"] == "SHA-256 카운터 모드 PRNG + Fisher-Yates 셔플, v1"
        assert len(v["resultHash"]) == 64 and "name" not in str(v)  # 이름 대신 번호만
        # 공개된 알고리즘에 입력과 시드를 넣으면 누구나 같은 결과
        assert replay(kind, v["seed"], v["input"]["candidates"], v["input"]["options"]) == v["result"]
    pv = (await t.get(f"/api/draws/{pin['drawId']}/verification")).json()
    assert pv["input"]["candidates"] == [1, 3, 4, 5, 6, 7, 8, 9, 10] and pv["input"]["options"] == {
        "mode": "DROP", "winnerCount": 3, "allowDuplicate": False}
    assert pv["result"] == [w["number"] for w in pin["winners"]]
    assert (await t.get("/api/draws/nope/verification")).status_code == 404
    assert (await t.get("/api/draws/00000000-0000-4000-8000-000000000000")).json()["code"] == "DRAW_NOT_FOUND"


async def test_history_filters_and_limits(klass):
    t = klass["t"]
    for _ in range(3):
        await t.post("/api/draws/seats", json=seat_body())
    pin = (await t.post("/api/draws/pinball", json={"grade": 2, "classNo": 1, "mode": "DROP", "winnerCount": 2})).json()
    await t.post("/api/draws/pinball", json={"grade": 2, "classNo": 2, "mode": "DROP", "winnerCount": 1})
    items = (await t.get("/api/draws")).json()["items"]
    assert len(items) == 5 and items[0]["type"] == "PINBALL" and items[0]["classNo"] == 2  # 최신순
    assert items[0]["createdBy"] == "박선생"
    mine = (await t.get("/api/draws", params={"grade": 2, "classNo": 1, "type": "SEAT"})).json()["items"]
    assert len(mine) == 3 and mine[0]["summary"] == "배치 인원 10명"
    p = (await t.get("/api/draws", params={"classNo": 1, "type": "PINBALL"})).json()["items"]
    assert [i["drawId"] for i in p] == [pin["drawId"]] and p[0]["summary"].startswith("당첨자: 학생") and p[0]["mode"] == "DROP"
    assert len((await t.get("/api/draws", params={"limit": 2})).json()["items"]) == 2
    assert len((await t.get("/api/draws", params={"limit": 999})).json()["items"]) == 5  # 최대 50으로 제한
    assert (await t.get("/api/draws", params={"grade": "x"})).status_code == 400
    assert (await t.get("/api/draws", params={"type": "NOPE"})).status_code == 400
