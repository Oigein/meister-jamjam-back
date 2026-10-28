"""GitHub·LinkedIn 입력을 표준 URL로 정리한다. 형식만 검사하고 존재 여부는 확인하지 않는다."""
import re
from urllib.parse import urlparse

_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_GITHUB_ID = re.compile(r"^(?!-)[A-Za-z0-9-]{1,39}(?<!-)$")
_LINKEDIN_ID = re.compile(r"^[A-Za-z0-9\-%]{3,100}$")
_GITHUB_RESERVED = {
    "settings", "orgs", "organizations", "topics", "marketplace", "features", "pricing", "about", "login",
    "join", "explore", "notifications", "sponsors", "apps", "enterprise", "search", "pulls", "issues", "new",
    "collections", "trending", "events", "codespaces", "readme", "security", "site", "contact", "solutions",
    "resources", "team", "customer-stories", "sessions", "account", "dashboard", "watching", "stars",
}


class LinkError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _split(value: str, host_ok) -> tuple[str | None, list[str]]:
    """(호스트 또는 None, 경로 조각들). 호스트가 없으면 아이디만 입력한 것이다."""
    v = value.strip()
    if v.startswith("@"):
        v = v[1:].strip()
    if not v:
        raise LinkError("MISSING_ID")
    m = _SCHEME.match(v)
    if m and not v.lower().startswith(("http://", "https://")):
        raise LinkError("INVALID_SCHEME")
    if not m and "/" not in v and "." not in v:
        return None, [v]  # 아이디만 입력
    if not m:
        v = "https://" + v
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise LinkError("INVALID_SCHEME")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise LinkError("INVALID_SCHEME")
    try:
        port = parsed.port
    except ValueError:
        raise LinkError("INVALID_HOST")
    host = (parsed.hostname or "").lower()  # 호스트만 소문자로 바꾸고 아이디는 그대로 둔다
    if port is not None or not host_ok(host):
        raise LinkError("INVALID_HOST")
    return host, [s for s in parsed.path.split("/") if s]


def normalize_github(value: str) -> str | None:
    if value is None or not value.strip():
        return None
    host, parts = _split(value, lambda h: h in ("github.com", "www.github.com"))
    if not parts:
        raise LinkError("MISSING_ID")
    ident = parts[0]
    if ident.lower() in _GITHUB_RESERVED:
        raise LinkError("RESERVED_PATH")
    if not _GITHUB_ID.match(ident):
        raise LinkError("INVALID_ID")
    return f"https://github.com/{ident}"


def normalize_linkedin(value: str) -> str | None:
    if value is None or not value.strip():
        return None
    host, parts = _split(value, lambda h: h == "linkedin.com" or h.endswith(".linkedin.com"))
    if host is None:
        ident = parts[0]
    else:
        if not parts:
            raise LinkError("MISSING_ID")
        if parts[0].lower() != "in":
            raise LinkError("NOT_PERSONAL_PROFILE")
        if len(parts) < 2:
            raise LinkError("MISSING_ID")
        ident = parts[1]
    if not _LINKEDIN_ID.match(ident):
        raise LinkError("INVALID_ID")
    return f"https://www.linkedin.com/in/{ident}"
