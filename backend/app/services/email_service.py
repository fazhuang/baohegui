"""邮件服务 — Resend API 集成（开发模式降级到日志输出）"""

from __future__ import annotations

import logging
import random
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def _generate_verification_code() -> str:
    """生成 6 位数字验证码"""
    return f"{random.randint(100000, 999999)}"


def _generate_reset_token() -> str:
    """生成密码重置令牌"""
    import secrets
    return secrets.token_urlsafe(32)


async def send_verification_email(email: str) -> tuple[str, bool]:
    """
    发送邮箱验证码。

    Returns:
        (code, success) — code 用于存入数据库验证，success 表示是否发送成功
    """
    code = _generate_verification_code()
    subject = "包合规 - 邮箱验证码"
    body = f"""您好！

您的包合规账号验证码为：{code}

验证码 10 分钟内有效。如非本人操作，请忽略此邮件。

包合规团队
https://baohegui.com"""

    success = await _send_email(email, subject, body)
    return code, success


async def send_password_reset_email(email: str) -> tuple[str, bool]:
    """
    发送密码重置邮件。

    Returns:
        (token, success) — token 用于存入数据库验证，success 表示是否发送成功
    """
    token = _generate_reset_token()
    subject = "包合规 - 密码重置"
    body = f"""您好！

您申请了密码重置。请使用以下链接重置密码：

https://baohegui.com/reset-password?token={token}

该链接 30 分钟内有效。如非本人操作，请忽略此邮件。

包合规团队"""

    success = await _send_email(email, subject, body)
    return token, success


async def _send_email(to_email: str, subject: str, body: str) -> bool:
    """
    发送邮件。

    优先级：
    1. Resend API（如果配置了 API Key）
    2. 日志输出（开发环境，无 API Key）
    """
    if settings.resend_api_key:
        return await _send_via_resend(to_email, subject, body)
    else:
        return _send_via_log(to_email, subject, body)


async def _send_via_resend(to_email: str, subject: str, body: str) -> bool:
    """通过 Resend API 发送邮件"""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"包合规 <{settings.email_from_address}>",
                    "to": [to_email],
                    "subject": subject,
                    "text": body,
                },
            )
            if resp.status_code in (200, 201):
                logger.info("邮件已发送至 %s", to_email)
                return True
            else:
                logger.error("Resend 发送失败: %s %s", resp.status_code, resp.text)
                return False
    except Exception as e:
        logger.error("Resend 发送异常: %s", e)
        return False


def _send_via_log(to_email: str, subject: str, body: str) -> bool:
    """
    开发环境：不真正发送邮件，而是输出到日志。
    部署后设置 BHG_RESEND_API_KEY 即可自动切换为真实发送。
    """
    logger.info("=" * 60)
    logger.info("📧 开发模式 — 邮件内容如下（未实际发送）")
    logger.info(f"   收件人: {to_email}")
    logger.info(f"   主题: {subject}")
    logger.info(f"   正文: {body[:200]}...")
    logger.info("=" * 60)
    return True
