from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "meister-jamjam-back"
    debug: bool = False

    # DB: 운영은 mysql+aiomysql://..., 로컬·테스트는 SQLite
    database_url: str = "sqlite+aiosqlite:///./jamjam.db"
    auto_create_tables: bool = True
    seed_on_startup: bool = True
    run_background_jobs: bool = True

    # 인증·세션
    service_origins: list[str] = ["http://localhost:3000"]
    enforce_origin: bool = True
    cookie_name: str = "SESSION"
    cookie_secure: bool = True
    session_ttl_seconds: int = 604800
    allowed_email_domain: str = "bssm.hs.kr"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    login_default_redirect: str = "/ranking"

    # 암호화 (자진 신고). 32바이트를 base64로 넣는다. 비어 있으면 secret_key에서 파생(개발용)
    secret_key: str = "dev-secret-change-me"
    encryption_key: str = ""

    storage_dir: str = "./storage"

    # 이메일 (자진 신고 접수 알림). smtp_host가 비어 있으면 발송하지 않고 로그만 남긴다
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True  # 587 STARTTLS. 465는 암묵적 SSL로 자동 처리

    # --- 노션 명세의 임시값 (미확정 값은 여기서만 바꾼다) ---
    rate_login_per_min: int = 20
    rate_point_rules_per_min: int = 60
    rate_profile_per_min: int = 20
    rate_upload_per_min: int = 10
    rate_recommend_per_min: int = 10
    rate_recommend_per_day: int = 100

    ranking_page_size: int = 20
    default_page_size: int = 20
    evidence_max_bytes: int = 10 * 1024 * 1024
    evidence_title_max: int = 50
    reject_reason_max: int = 200
    self_report_max_recipients: int = 1
    self_report_attachment_max: int = 3
    self_report_attachment_bytes: int = 10 * 1024 * 1024
    self_report_orphan_hours: int = 24
    theme_asset_limit: int = 5
    theme_gif_max_bytes: int = 10 * 1024 * 1024
    theme_mp4_max_bytes: int = 30 * 1024 * 1024
    theme_mp4_max_seconds: float = 30.0
    notification_retention_days: int = 90
    sse_ping_seconds: float = 30.0
    draw_history_default: int = 10
    draw_history_max: int = 50
    draw_room_max: int = 10


settings = Settings()
