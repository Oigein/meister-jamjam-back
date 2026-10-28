from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    """DB에는 KST 기준 naive datetime으로 저장한다."""
    return datetime.now(KST).replace(tzinfo=None)


def today_kst() -> date:
    return now_kst().date()


def to_naive_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(KST).replace(tzinfo=None)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).isoformat()
