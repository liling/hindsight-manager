"""Tests for email service."""

import pytest

from hindsight_manager.services.email import (
    SENDGRID_AVAILABLE,
    SendGridEmailService,
    SMTPEmailService,
)


@pytest.mark.asyncio
async def test_smtp_email_service_send_verification_email(monkeypatch):
    """测试SMTP邮箱服务发送验证码邮件."""
    sent_emails = []

    class MockSMTP:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, msg):
            sent_emails.append(msg)

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", MockSMTP)

    service = SMTPEmailService(
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        password="password",
        from_email="noreply@example.com",
    )

    result = await service.send_verification_email("user@example.com", "123456")
    assert result is True
    assert len(sent_emails) == 1
    assert sent_emails[0]["To"] == "user@example.com"
    assert sent_emails[0]["Subject"] == "验证您的邮箱地址"


@pytest.mark.asyncio
async def test_smtp_email_service_send_password_reset_email(monkeypatch):
    """测试SMTP邮箱服务发送密码重置邮件."""
    sent_emails = []

    class MockSMTP:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, msg):
            sent_emails.append(msg)

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", MockSMTP)

    service = SMTPEmailService(
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        password="password",
        from_email="noreply@example.com",
    )

    result = await service.send_password_reset_email(
        "user@example.com", "http://example.com/reset?token=abc123"
    )
    assert result is True
    assert len(sent_emails) == 1
    assert sent_emails[0]["To"] == "user@example.com"
    assert sent_emails[0]["Subject"] == "重置您的密码"


@pytest.mark.skipif(not SENDGRID_AVAILABLE, reason="SendGrid not installed")
@pytest.mark.asyncio
async def test_sendgrid_email_service_send_verification_email(monkeypatch):
    """测试SendGrid邮箱服务发送验证码邮件."""
    sent_messages = []

    class MockSendGridClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def send(self, message):
            sent_messages.append(message)
            class MockResponse:
                status_code = 202
            return MockResponse()

    class MockSendGridAPIClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def send(self, message):
            sent_messages.append(message)
            class MockResponse:
                status_code = 202
            return MockResponse()

    class MockMail:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    # Patch at module level
    import hindsight_manager.services.email as email_module
    monkeypatch.setattr(email_module, "SENDGRID_AVAILABLE", True)
    mock_sendgrid = type("obj", (object,), {"SendGridAPIClient": MockSendGridAPIClient})()
    monkeypatch.setattr(email_module, "sendgrid", mock_sendgrid, raising=False)
    monkeypatch.setattr(email_module, "Mail", MockMail, raising=False)

    service = SendGridEmailService(
        api_key="test-key",
        from_email="noreply@example.com",
    )

    result = await service.send_verification_email("user@example.com", "123456")
    assert result is True
    assert len(sent_messages) == 1


@pytest.mark.skipif(not SENDGRID_AVAILABLE, reason="SendGrid not installed")
@pytest.mark.asyncio
async def test_sendgrid_email_service_send_password_reset_email(monkeypatch):
    """测试SendGrid邮箱服务发送密码重置邮件."""
    sent_messages = []

    class MockSendGridClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def send(self, message):
            sent_messages.append(message)
            class MockResponse:
                status_code = 202
            return MockResponse()

    class MockSendGridAPIClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def send(self, message):
            sent_messages.append(message)
            class MockResponse:
                status_code = 202
            return MockResponse()

    class MockMail:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    # Patch at module level
    import hindsight_manager.services.email as email_module
    monkeypatch.setattr(email_module, "SENDGRID_AVAILABLE", True)
    mock_sendgrid = type("obj", (object,), {"SendGridAPIClient": MockSendGridAPIClient})()
    monkeypatch.setattr(email_module, "sendgrid", mock_sendgrid, raising=False)
    monkeypatch.setattr(email_module, "Mail", MockMail, raising=False)

    service = SendGridEmailService(
        api_key="test-key",
        from_email="noreply@example.com",
    )

    result = await service.send_password_reset_email(
        "user@example.com", "http://example.com/reset?token=abc123"
    )
    assert result is True
    assert len(sent_messages) == 1
