import smtplib

import pytest

from app.common import mailer as mailer_module
from app.common.mailer import LogMailer, SmtpMailer, get_mailer, set_mailer
from app.core.config import settings


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _smtp_env(monkeypatch):
    FakeSMTP.instances.clear()
    set_mailer(None)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "")
    yield
    set_mailer(None)


def test_selects_log_mailer_without_smtp_host(monkeypatch):
    assert isinstance(get_mailer(), LogMailer)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    assert isinstance(get_mailer(), SmtpMailer)


async def test_smtp_send_uses_starttls_and_login(monkeypatch):
    for k, v in {"smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_user": "bot@bssm.hs.kr",
                 "smtp_password": "pw", "smtp_from": "noreply@bssm.hs.kr"}.items():
        monkeypatch.setattr(settings, k, v)
    await get_mailer().send("teacher@bssm.hs.kr", "제목", "본문")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", ("login", "bot@bssm.hs.kr", "pw")]
    msg = smtp.sent[0]
    assert msg["To"] == "teacher@bssm.hs.kr" and msg["From"] == "noreply@bssm.hs.kr" and msg["Subject"] == "제목"
    assert msg.get_content().strip() == "본문"


async def test_smtp_ssl_port_skips_starttls(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_user", "")
    await SmtpMailer().send("a@bssm.hs.kr", "s", "b")
    assert FakeSMTP.instances[0].calls == []


async def test_mail_failure_does_not_break_submission_and_logs_nothing_sensitive(monkeypatch, caplog):
    class Boom(FakeSMTP):
        def send_message(self, msg):
            raise smtplib.SMTPException("down")

    monkeypatch.setattr(smtplib, "SMTP", Boom)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    with pytest.raises(smtplib.SMTPException):
        await get_mailer().send("secret-recipient@bssm.hs.kr", "비밀 제목", "비밀 본문")
    assert "비밀" not in caplog.text and "secret-recipient" not in caplog.text
    assert mailer_module.logger.name == "app.mail"
