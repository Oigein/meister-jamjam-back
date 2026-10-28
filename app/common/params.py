from app.common.exceptions import field_error, validation_failed


def opt_int(name: str, value: str | None, minimum: int | None = None, maximum: int | None = None) -> int | None:
    """`?grade=` 처럼 빈 값으로 오는 쿼리도 '없음'으로 받는다. 숫자가 아니거나 범위 밖이면 400."""
    if value is None or not value.strip():
        return None
    try:
        n = int(value.strip())
    except ValueError:
        raise validation_failed(field_error(name, "INVALID_TYPE", "숫자를 입력해 주세요."))
    if (minimum is not None and n < minimum) or (maximum is not None and n > maximum):
        raise validation_failed(field_error(name, "OUT_OF_RANGE", "허용 범위를 벗어났습니다."))
    return n
