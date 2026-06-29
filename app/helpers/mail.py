# ─────────────────────────────────────────────────────────────
# helpers/mail.py
#
# Lógica de generación de tokens y envío de correos.
# Separado de auth_utils para que el módulo de correos pueda
# crecer de forma independiente (ej: notificaciones de pedidos).
# ─────────────────────────────────────────────────────────────

import smtplib
from email.message import EmailMessage
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


def _get_serializer():
    """Instancia el serializador usando la SECRET_KEY de la app."""
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='password-reset-salt'
    )


def generate_password_reset_token(email):
    """Genera un token firmado con el email del usuario.

    El token expira en 1 hora (validado al verificarlo).
    """
    return _get_serializer().dumps(email)


def verify_password_reset_token(token, max_age=3600):
    """Valida el token y devuelve el email si es válido, None si expiró o es inválido."""
    try:
        return _get_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def send_password_reset_email(to_email, reset_link):
    """Envía el correo de recuperación de contraseña.

    Devuelve True si el envío fue exitoso, False en cualquier otro caso.
    Requiere que MAIL_SERVER, MAIL_USERNAME y MAIL_PASSWORD estén configurados en .env
    """
    cfg = current_app.config

    # Si no hay configuración de correo, no intentamos enviar
    if not cfg.get('MAIL_SERVER') or not cfg.get('MAIL_USERNAME') or not cfg.get('MAIL_PASSWORD'):
        return False

    message = EmailMessage()
    message['Subject'] = 'Recuperar contraseña - SayerBarn'
    message['From'] = cfg.get('MAIL_DEFAULT_SENDER', cfg['MAIL_USERNAME'])
    message['To'] = to_email
    message.set_content(
        f"Hola,\n\n"
        f"Haz clic en el siguiente enlace para restablecer tu contraseña:\n\n"
        f"{reset_link}\n\n"
        f"Este enlace expirará en 1 hora. "
        f"Si no solicitaste este cambio, ignora este mensaje.\n"
    )

    try:
        if cfg.get('MAIL_USE_SSL'):
            with smtplib.SMTP_SSL(cfg['MAIL_SERVER'], cfg['MAIL_PORT']) as server:
                server.login(cfg['MAIL_USERNAME'], cfg['MAIL_PASSWORD'])
                server.send_message(message)
        else:
            with smtplib.SMTP(cfg['MAIL_SERVER'], cfg['MAIL_PORT']) as server:
                if cfg.get('MAIL_USE_TLS'):
                    server.starttls()
                server.login(cfg['MAIL_USERNAME'], cfg['MAIL_PASSWORD'])
                server.send_message(message)
        return True
    except Exception as e:
        print(f"[ERROR EMAIL] No se pudo enviar correo a {to_email}: {e}")
        return False