# ─────────────────────────────────────────────────────────────
# helpers/auth_utils.py
#
# Utilidades de autenticación compartidas entre todos los blueprints.
# Centralizar aquí evita duplicar lógica de JWT y acceso a usuarios
# en cada archivo de rutas.
# ─────────────────────────────────────────────────────────────

from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app import mysql


def usuario_actual():
    """Devuelve el usuario logueado como dict, o None si no hay sesión activa.

    Usa optional=True para no lanzar error cuando no hay cookie JWT.
    Todos los blueprints deben llamar a esta función en lugar de
    duplicar la lógica de verificación.
    """
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
        if user_id:
            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT id, nombre, email, rol FROM usuarios WHERE id = %s AND activo = 1",
                (user_id,)
            )
            usuario = cur.fetchone()
            cur.close()
            return usuario
    except Exception:
        pass
    return None