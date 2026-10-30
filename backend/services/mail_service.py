"""Transactional mail transport. Secrets and message bodies never enter logs."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def configured():
    return ((os.getenv('MAIL_PROVIDER') or '').strip().lower() == 'smtp'
            and bool(os.getenv('SMTP_HOST', '').strip())
            and bool((os.getenv('SMTP_FROM') or os.getenv('SMTP_USER') or '').strip()))


def send(to, subject, body, html_body=None):
    if not configured():
        raise RuntimeError('Mail is not configured')
    message = EmailMessage()
    message['From'] = os.getenv('SMTP_FROM') or os.getenv('SMTP_USER')
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype='html')
    for line in body.splitlines():
        if line.startswith('Unsubscribe: '):
            message['List-Unsubscribe'] = '<' + line.removeprefix('Unsubscribe: ').strip() + '>'
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USER'):
            smtp.login(os.environ['SMTP_USER'], os.getenv('SMTP_PASSWORD', ''))
        smtp.send_message(message)
    return {'status': 'sent', 'provider_message_id': None, 'error': ''}
