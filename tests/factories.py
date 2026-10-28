import itertools

from app.common.enums import Role
from app.domains.user.models import Student, Teacher, User

_seq = itertools.count(1)


async def make_student(db, name="홍길동", grade=2, class_no=1, number=None, **points) -> User:
    n = next(_seq)
    user = User(name=name, email=f"s{n}@bssm.hs.kr", role=Role.STUDENT, google_id=f"g-s{n}")
    db.add(user)
    await db.flush()
    db.add(
        Student(
            student_id=user.user_id,
            grade=grade,
            class_no=class_no,
            student_number=number if number is not None else n,
            **points,
        )
    )
    await db.commit()
    return user


async def make_teacher(
    db, name="박선생", role=Role.TEACHER, subject=None, position=None, homeroom=None
) -> User:
    n = next(_seq)
    user = User(name=name, email=f"t{n}@bssm.hs.kr", role=role, google_id=f"g-t{n}")
    db.add(user)
    await db.flush()
    db.add(
        Teacher(
            teacher_id=user.user_id,
            subject=subject,
            position=position,
            homeroom_grade=homeroom[0] if homeroom else None,
            homeroom_class=homeroom[1] if homeroom else None,
        )
    )
    await db.commit()
    return user


async def make_admin(db, name="관리자") -> User:
    return await make_teacher(db, name=name, role=Role.ADMIN)
