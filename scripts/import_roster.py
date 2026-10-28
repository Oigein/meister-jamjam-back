"""사전 등록 명단(CSV)을 DB에 넣는다. 첫 로그인 때 이메일로 찾아 구글 sub를 연결한다.

CSV 헤더: role,email,name,grade,class_no,number,subject,position,homeroom_grade,homeroom_class
- STUDENT: grade, class_no, number 필수
- TEACHER / ADMIN: subject, position, homeroom_grade, homeroom_class 선택

    python -m scripts.import_roster roster.csv
"""
import asyncio
import csv
import sys

from sqlalchemy import select

import app.models  # noqa: F401
from app.common.enums import Role
from app.core.database import get_sessionmaker
from app.domains.user.models import Student, Teacher, User


def _int(value: str | None) -> int | None:
    return int(value) if value and value.strip() else None


async def import_roster(path: str) -> tuple[int, int]:
    created = skipped = 0
    async with get_sessionmaker()() as db:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = row["email"].strip().lower()
                if await db.scalar(select(User).where(User.email == email)):
                    skipped += 1
                    continue
                role = Role(row["role"].strip().upper())
                user = User(name=row["name"].strip(), email=email, role=role)  # google_id는 첫 로그인 때 채운다
                db.add(user)
                await db.flush()
                if role == Role.STUDENT:
                    db.add(
                        Student(
                            student_id=user.user_id,
                            grade=int(row["grade"]),
                            class_no=int(row["class_no"]),
                            student_number=int(row["number"]),
                        )
                    )
                else:
                    db.add(
                        Teacher(
                            teacher_id=user.user_id,
                            subject=row.get("subject") or None,
                            position=row.get("position") or None,
                            homeroom_grade=_int(row.get("homeroom_grade")),
                            homeroom_class=_int(row.get("homeroom_class")),
                        )
                    )
                created += 1
        await db.commit()
    return created, skipped


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    made, skipped = asyncio.run(import_roster(sys.argv[1]))
    print(f"등록 {made}명, 이미 있어 건너뜀 {skipped}명")
