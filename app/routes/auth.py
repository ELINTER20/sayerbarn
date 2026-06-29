# ─────────────────────────────────────────────────────────────
# routes/auth.py
#
# Blueprint de autenticación: registro, login, logout y
# recuperación de contraseña.
#
# Rutas:
#   GET/POST  /login
#   GET/POST  /registro
#   POST      /logout
#   GET/POST  /recuperar-password
#   GET/POST  /reset-password/<token>
# ─────────────────────────────────────────────────────────────

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, make_response, current_app
)
from flask_jwt_extended import (
    create_access_token, set_access_cookies, unset_jwt_cookies
)

from app import mysql, bcrypt
from app.helpers.auth_utils import usuario_actual
from app.helpers.mail import (
    generate_password_reset_token,
    verify_password_reset_token,
    send_password_reset_email,
)

auth_bp = Blueprint('auth', __name__)


# ── Login ─────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, nombre, password_hash, rol FROM usuarios "
            "WHERE email = %s AND activo = 1",
            (email,)
        )
        usuario = cur.fetchone()
        cur.close()

        if usuario and bcrypt.check_password_hash(usuario['password_hash'], password):
            token   = create_access_token(identity=str(usuario['id']))
            destino = url_for('admin.dashboard') if usuario['rol'] == 'admin' else url_for('public.index')
            response = make_response(redirect(destino))
            set_access_cookies(response, token)
            return response

        return render_template(
            'auth/login.html',
            error='Correo o contraseña incorrectos.',
            email=email,
            usuario=usuario_actual()
        )

    return render_template('auth/login.html', usuario=usuario_actual())


# ── Registro ──────────────────────────────────────────────────

@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre           = request.form.get('nombre', '').strip()
        email            = request.form.get('email', '').strip()
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirmPassword', '')

        if not nombre or not email or not password or not confirm_password:
            return render_template(
                'auth/registro.html',
                error='Todos los campos son requeridos.',
                nombre=nombre, email=email, usuario=usuario_actual()
            )

        if password != confirm_password:
            return render_template(
                'auth/registro.html',
                error='Las contraseñas no coinciden.',
                nombre=nombre, email=email, usuario=usuario_actual()
            )

        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO usuarios (nombre, email, password_hash) VALUES (%s, %s, %s)",
                (nombre, email, password_hash)
            )
            mysql.connection.commit()
            usuario_id = cur.lastrowid
            cur.close()
        except Exception as e:
            print(f"[ERROR REGISTRO] {type(e).__name__}: {e}")
            if hasattr(e, 'args') and e.args and e.args[0] == 1062:
                return render_template(
                    'auth/registro.html',
                    error='El correo ya está registrado.',
                    nombre=nombre, email=email, usuario=usuario_actual()
                )
            return render_template(
                'auth/registro.html',
                error=f'Error al crear la cuenta: {e}',
                nombre=nombre, email=email, usuario=usuario_actual()
            )

        token    = create_access_token(identity=str(usuario_id))
        response = make_response(redirect(url_for('public.index')))
        set_access_cookies(response, token)
        return response

    return render_template('auth/registro.html', usuario=usuario_actual())


# ── Logout ────────────────────────────────────────────────────

@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = make_response(redirect(url_for('public.index')))
    unset_jwt_cookies(response)
    return response


# ── Recuperar contraseña ──────────────────────────────────────

@auth_bp.route('/recuperar-password', methods=['GET', 'POST'])
def recuperar_password():
    error      = None
    success    = None
    reset_link = None
    email_sent = False

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            error = 'Ingresa tu correo electrónico.'
        else:
            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT id FROM usuarios WHERE email = %s AND activo = 1",
                (email,)
            )
            usuario = cur.fetchone()
            cur.close()

            if usuario:
                reset_link = url_for(
                    'auth.reset_password',
                    token=generate_password_reset_token(email),
                    _external=True
                )
                email_sent = send_password_reset_email(email, reset_link)
                success = (
                    'Si ese correo existe, hemos enviado un enlace de recuperación.'
                    if email_sent else
                    'No se pudo enviar el correo. Usa el enlace directo de prueba a continuación.'
                )
            else:
                success = 'Si ese correo existe, hemos enviado un enlace de recuperación.'

    show_reset_link = bool(
        reset_link and (
            current_app.debug or
            not current_app.config.get('MAIL_SERVER') or
            not email_sent
        )
    )
    return render_template(
        'recuperar_password.html',
        error=error,
        success=success,
        reset_link=reset_link if show_reset_link else None,
        usuario=usuario_actual()
    )


# ── Reset de contraseña ───────────────────────────────────────

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    error = None
    email = verify_password_reset_token(token)

    if not email:
        return render_template(
            'recuperar_password.html',
            error='El enlace no es válido o expiró. Solicita uno nuevo.',
            usuario=usuario_actual()
        )

    if request.method == 'POST':
        password         = request.form.get('password', '')
        confirm_password = request.form.get('confirmPassword', '')

        if not password or not confirm_password:
            error = 'Todos los campos son requeridos.'
        elif password != confirm_password:
            error = 'Las contraseñas no coinciden.'
        else:
            password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE usuarios SET password_hash = %s WHERE email = %s AND activo = 1",
                (password_hash, email)
            )
            mysql.connection.commit()
            cur.close()
            return render_template(
                'auth/login.html',
                success='Tu contraseña ha sido actualizada. Ya puedes iniciar sesión.',
                email=email,
                usuario=usuario_actual()
            )

    return render_template('reset_password.html', token=token, error=error, usuario=usuario_actual())