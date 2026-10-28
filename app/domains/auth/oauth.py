"""구글 OIDC(Authorization Code + PKCE) 클라이언트. 테스트에서는 `get_google_client`를 가짜로 바꾼다."""
from typing import Protocol
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet

from app.core.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]


class GoogleError(Exception):
    """토큰 검증 실패 등 (AUTH_FAILED)."""


class GoogleUnavailable(Exception):
    """구글 서버 오류·지연 (GOOGLE_UNAVAILABLE)."""


class GoogleClient(Protocol):
    def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str: ...

    async def fetch_claims(self, code: str, code_verifier: str, nonce: str) -> dict: ...


class RealGoogleClient:
    def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "hd": settings.allowed_email_domain,  # 힌트일 뿐이라 콜백에서 토큰으로 다시 검사한다
            "prompt": "select_account",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def fetch_claims(self, code: str, code_verifier: str, nonce: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                token_res = await http.post(
                    TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "redirect_uri": settings.google_redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                )
                if token_res.status_code >= 500:
                    raise GoogleUnavailable()
                if token_res.status_code != 200:
                    raise GoogleError("token exchange failed")
                id_token = token_res.json().get("id_token")
                jwks_res = await http.get(JWKS_URL)
                if jwks_res.status_code != 200:
                    raise GoogleUnavailable()
                jwks = KeySet.import_key_set(jwks_res.json())
        except httpx.HTTPError as exc:
            raise GoogleUnavailable() from exc
        if not id_token:
            raise GoogleError("no id_token")
        try:
            token = jwt.decode(id_token, jwks)
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "values": ISSUERS},
                aud={"essential": True, "value": settings.google_client_id},
                nonce={"essential": True, "value": nonce},
                exp={"essential": True},
            ).validate(token.claims)
            claims = token.claims
        except Exception as exc:
            raise GoogleError("id_token invalid") from exc
        return dict(claims)


def get_google_client() -> GoogleClient:
    return RealGoogleClient()
