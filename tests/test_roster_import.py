import textwrap

from sqlalchemy import select

from app.domains.user.models import Student, Teacher, User
from scripts.import_roster import import_roster


async def test_import_roster_creates_users_without_google_id(db, tmp_path):
    csv_file = tmp_path / "roster.csv"
    csv_file.write_text(textwrap.dedent("""\
        role,email,name,grade,class_no,number,subject,position,homeroom_grade,homeroom_class
        STUDENT,S2401@bssm.hs.kr,홍길동,2,1,5,,,,
        TEACHER,t1@bssm.hs.kr,박선생,,,,수학,2학년 1반 담임,2,1
        ADMIN,admin@bssm.hs.kr,관리자,,,,,,,
    """), encoding="utf-8")
    assert await import_roster(str(csv_file)) == (3, 0)
    assert await import_roster(str(csv_file)) == (0, 3)  # 다시 실행해도 중복 등록하지 않는다

    student = await db.scalar(select(User).where(User.email == "s2401@bssm.hs.kr"))
    assert student.google_id is None and student.role.value == "STUDENT"
    row = await db.get(Student, student.user_id)
    assert (row.grade, row.class_no, row.student_number) == (2, 1, 5)
    teacher = await db.scalar(select(Teacher).join(User, User.user_id == Teacher.teacher_id).where(User.email == "t1@bssm.hs.kr"))
    assert (teacher.subject, teacher.homeroom_grade, teacher.homeroom_class) == ("수학", 2, 1)
