import pytest

from app.domains.user.links import LinkError, normalize_github, normalize_linkedin
from tests.factories import make_student, make_teacher


@pytest.mark.parametrize(
    "value,expected",
    [
        ("octocat", "https://github.com/octocat"),
        ("@octocat", "https://github.com/octocat"),
        ("github.com/octocat", "https://github.com/octocat"),
        ("  https://www.github.com/OctoCat/repo  ", "https://github.com/OctoCat"),
        ("HTTPS://GITHUB.COM/octocat", "https://github.com/octocat"),
        ("", None),
        ("   ", None),
    ],
)
def test_github_ok(value, expected):
    assert normalize_github(value) == expected


@pytest.mark.parametrize(
    "value,reason",
    [
        ("https://github.com.evil.com/octocat", "INVALID_HOST"),
        ("https://evil.com/github.com/octocat", "INVALID_HOST"),
        ("https://gist.github.com/octocat", "INVALID_HOST"),
        ("javascript:alert(1)", "INVALID_SCHEME"),
        ("data:text/html,x", "INVALID_SCHEME"),
        ("ftp://github.com/octocat", "INVALID_SCHEME"),
        ("https://user:pw@github.com/octocat", "INVALID_SCHEME"),
        ("https://github.com", "MISSING_ID"),
        ("@", "MISSING_ID"),
        ("https://github.com/settings", "RESERVED_PATH"),
        ("https://github.com/orgs/foo", "RESERVED_PATH"),
        ("-octocat", "INVALID_ID"),
        ("octocat-", "INVALID_ID"),
        ("a" * 40, "INVALID_ID"),
        ("octo_cat", "INVALID_ID"),
    ],
)
def test_github_rejected(value, reason):
    with pytest.raises(LinkError) as e:
        normalize_github(value)
    assert e.value.reason == reason


@pytest.mark.parametrize(
    "value,expected",
    [
        ("honggildong", "https://www.linkedin.com/in/honggildong"),
        ("linkedin.com/in/hong-gil", "https://www.linkedin.com/in/hong-gil"),
        ("https://kr.linkedin.com/in/hong-gil/", "https://www.linkedin.com/in/hong-gil"),
        ("", None),
    ],
)
def test_linkedin_ok(value, expected):
    assert normalize_linkedin(value) == expected


@pytest.mark.parametrize(
    "value,reason",
    [
        ("https://www.linkedin.com/company/acme", "NOT_PERSONAL_PROFILE"),
        ("https://www.linkedin.com/school/x", "NOT_PERSONAL_PROFILE"),
        ("https://www.linkedin.com/in/", "MISSING_ID"),
        ("https://linkedin.com", "MISSING_ID"),
        ("https://notlinkedin.com/in/abc", "INVALID_HOST"),
        ("https://linkedin.com.evil.com/in/abc", "INVALID_HOST"),
        ("ab", "INVALID_ID"),
    ],
)
def test_linkedin_rejected(value, reason):
    with pytest.raises(LinkError) as e:
        normalize_linkedin(value)
    assert e.value.reason == reason


async def test_profile_patch_semantics(make_client, db):
    s = await make_student(db)
    c = await make_client(s)
    assert (await c.get("/api/me/profile")).json() == {"githubUrl": None, "linkedinUrl": None}

    r = await c.patch("/api/me/profile", json={"githubUrl": "@octocat", "linkedinUrl": "hong-gil"})
    assert r.status_code == 200
    assert r.json() == {"githubUrl": "https://github.com/octocat",
                        "linkedinUrl": "https://www.linkedin.com/in/hong-gil"}
    # 키를 보내지 않으면 변경 없음
    r = await c.patch("/api/me/profile", json={"githubUrl": "other"})
    assert r.json() == {"githubUrl": "https://github.com/other",
                        "linkedinUrl": "https://www.linkedin.com/in/hong-gil"}
    # null 또는 빈 문자열은 삭제
    r = await c.patch("/api/me/profile", json={"githubUrl": None, "linkedinUrl": ""})
    assert r.json() == {"githubUrl": None, "linkedinUrl": None}
    # 같은 값을 다시 저장해도 200
    assert (await c.patch("/api/me/profile", json={})).status_code == 200


async def test_profile_patch_is_atomic_on_failure(make_client, db):
    s = await make_student(db)
    c = await make_client(s)
    await c.patch("/api/me/profile", json={"githubUrl": "octocat"})
    r = await c.patch(
        "/api/me/profile",
        json={"githubUrl": "newone", "linkedinUrl": "https://www.linkedin.com/company/x"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["fieldErrors"] == [
        {"field": "linkedinUrl", "reason": "NOT_PERSONAL_PROFILE",
         "message": "개인 프로필 주소(linkedin.com/in/아이디)를 입력하세요."}
    ]
    assert (await c.get("/api/me/profile")).json()["githubUrl"] == "https://github.com/octocat"


async def test_profile_patch_students_only(make_client, db):
    t = await make_teacher(db)
    c = await make_client(t)
    assert (await c.patch("/api/me/profile", json={"githubUrl": "x"})).status_code == 403
    assert (await (await make_client()).patch("/api/me/profile", json={})).status_code == 401


async def test_me_for_student_and_teacher(make_client, db):
    s = await make_student(db, grade=2, class_no=1, number=5)
    t = await make_teacher(db)
    me = (await (await make_client(s)).get("/api/me")).json()
    assert me["student"] == {"grade": 2, "classNo": 1, "number": 5} and me["role"] == "STUDENT"
    me = (await (await make_client(t)).get("/api/me")).json()
    assert me["student"] is None and me["role"] == "TEACHER"


async def test_teacher_search_and_roster(make_client, db):
    t1 = await make_teacher(db, "박수학", subject="수학", position="2학년 부장")
    await make_teacher(db, "김상담", position="상담교사")
    await make_student(db, "이마이", grade=2, class_no=1, number=2)
    await make_student(db, "김송프", grade=2, class_no=1, number=1)
    await make_student(db, "다른반", grade=2, class_no=2, number=1)
    c = await make_client(t1)

    items = (await c.get("/api/teachers", params={"q": "박"})).json()["items"]
    assert items == [{"teacherId": t1.user_id, "name": "박수학", "subject": "수학", "position": "2학년 부장"}]
    assert len((await c.get("/api/teachers")).json()["items"]) == 2
    assert (await c.get("/api/teachers", params={"q": "박", "position": "상담"})).json()["items"] == []

    r = (await c.get("/api/classes/2/1/students")).json()
    assert [s["number"] for s in r["students"]] == [1, 2]
    assert r["students"][0]["name"] == "김송프"
    for path in ("/api/classes/4/1/students", "/api/classes/2/5/students", "/api/classes/0/1/students"):
        assert (await c.get(path)).json()["code"] == "CLASS_NOT_FOUND"
    assert (await c.get("/api/classes/3/4/students")).json()["students"] == []


async def test_me_includes_homeroom_for_teacher(make_client, db):
    homeroom = await make_teacher(db, "담임", subject="수학", position="2학년 1반 담임", homeroom=(2, 1))
    plain = await make_teacher(db, "교과", subject="영어")
    me = (await (await make_client(homeroom)).get("/api/me")).json()
    assert me["teacher"] == {"subject": "수학", "position": "2학년 1반 담임", "homeroomGrade": 2, "homeroomClass": 1}
    assert me["student"] is None
    me = (await (await make_client(plain)).get("/api/me")).json()
    assert me["teacher"] == {"subject": "영어", "position": None, "homeroomGrade": None, "homeroomClass": None}
    student = (await (await make_client(await make_student(db))).get("/api/me")).json()
    assert student["teacher"] is None
