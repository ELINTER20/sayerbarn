# ─────────────────────────────────────────────────────────────
# routes/usuario.py
#
# Blueprint del área privada del usuario registrado.
#
# Rutas:
#   GET       /favoritos
#   POST      /favoritos/agregar/<id>
#   POST      /favoritos/eliminar/<id>
#   GET       /historial
#   GET       /mi-cuenta
#   GET/POST  /mi-cuenta/configuracion
# ─────────────────────────────────────────────────────────────

from flask import Blueprint, render_template, request, redirect, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import mysql, bcrypt
from app.helpers.auth_utils import usuario_actual

usuario_bp = Blueprint('usuario', __name__)


# ── Favoritos ─────────────────────────────────────────────────

@usuario_bp.route('/favoritos')
@jwt_required()
def favoritos():
    """Lista de productos marcados como favoritos por el usuario."""
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.precio_referencia, p.acabado, p.activo "
        "FROM favoritos f "
        "JOIN productos p ON f.producto_id = p.id "
        "WHERE f.usuario_id = %s ORDER BY f.created_at DESC",
        (user_id,)
    )
    productos = cur.fetchall()
    cur.close()
    return render_template('usuario/favoritos.html', productos=productos, usuario=usuario_actual())


@usuario_bp.route('/favoritos/agregar/<int:producto_id>', methods=['POST'])
@jwt_required()
def agregar_favorito(producto_id):
    """Agrega un producto a favoritos. INSERT IGNORE evita duplicados."""
    user_id = get_jwt_identity()
    cur = None
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT IGNORE INTO favoritos (usuario_id, producto_id) VALUES (%s, %s)",
            (user_id, producto_id)
        )
        mysql.connection.commit()
    except Exception:
        pass
    finally:
        if cur:
            cur.close()
    return redirect(request.referrer or url_for('public.catalogo'))


@usuario_bp.route('/favoritos/eliminar/<int:producto_id>', methods=['POST'])
@jwt_required()
def eliminar_favorito(producto_id):
    """Elimina un producto de la lista de favoritos del usuario."""
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
        (user_id, producto_id)
    )
    mysql.connection.commit()
    cur.close()
    return redirect(request.referrer or url_for('usuario.favoritos'))


# ── Historial de asesorías ────────────────────────────────────

@usuario_bp.route('/historial')
@jwt_required()
def historial():
    """Historial de asesorías realizadas por el usuario."""
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT a.id, a.superficie, a.uso, a.area_m2, a.litros_estimados, "
        "a.resultado, a.created_at, p.nombre AS producto_nombre, p.imagen_url "
        "FROM asesorias a "
        "LEFT JOIN productos p ON a.producto_recomendado_id = p.id "
        "WHERE a.usuario_id = %s ORDER BY a.created_at DESC",
        (user_id,)
    )
    asesorias = cur.fetchall()
    cur.close()
    return render_template('usuario/historial.html', asesorias=asesorias, usuario=usuario_actual())


# ── Mi cuenta ─────────────────────────────────────────────────

@usuario_bp.route('/mi-cuenta')
@jwt_required()
def mi_cuenta():
    """Hub de cuenta del usuario: accesos a pedidos, historial y favoritos."""
    return render_template('usuario/mi-cuenta.html', usuario=usuario_actual())


@usuario_bp.route('/mi-cuenta/configuracion', methods=['GET', 'POST'])
@jwt_required()
def configuracion():
    """Permite al usuario cambiar su nombre, correo o contraseña."""
    user_id = get_jwt_identity()
    usuario = usuario_actual()
    error   = None
    exito   = None

    if request.method == 'POST':
        accion = request.form.get('accion', '')

        if accion == 'datos':
            nuevo_nombre  = request.form.get('nombre', '').strip()
            nuevo_email   = request.form.get('email', '').strip().lower()
            confirm_datos = request.form.get('confirm_datos', '')

            if not nuevo_nombre or not nuevo_email or not confirm_datos:
                error = 'El nombre, el correo y la contraseña de confirmación son obligatorios.'
            else:
                cur = mysql.connection.cursor()
                cur.execute("SELECT password_hash FROM usuarios WHERE id=%s", (user_id,))
                row = cur.fetchone()
                cur.close()

                if not row or not bcrypt.check_password_hash(row['password_hash'], confirm_datos):
                    error = 'La contraseña no es correcta. Los datos no fueron modificados.'
                else:
                    try:
                        cur = mysql.connection.cursor()
                        cur.execute(
                            "UPDATE usuarios SET nombre=%s, email=%s WHERE id=%s",
                            (nuevo_nombre, nuevo_email, user_id)
                        )
                        mysql.connection.commit()
                        cur.close()
                        exito   = 'Datos actualizados correctamente.'
                        usuario = usuario_actual()
                    except Exception as e:
                        if hasattr(e, 'args') and e.args and e.args[0] == 1062:
                            error = 'Ese correo ya está registrado por otra cuenta.'
                        else:
                            error = 'Error al actualizar los datos. Intenta de nuevo.'

        elif accion == 'password':
            actual   = request.form.get('password_actual', '')
            nueva    = request.form.get('password_nueva', '')
            confirma = request.form.get('password_confirma', '')

            if not actual or not nueva or not confirma:
                error = 'Completa todos los campos de contraseña.'
            elif nueva != confirma:
                error = 'La nueva contraseña y su confirmación no coinciden.'
            elif len(nueva) < 8:
                error = 'La nueva contraseña debe tener al menos 8 caracteres.'
            else:
                cur = mysql.connection.cursor()
                cur.execute("SELECT password_hash FROM usuarios WHERE id=%s", (user_id,))
                row = cur.fetchone()
                cur.close()

                if not row or not bcrypt.check_password_hash(row['password_hash'], actual):
                    error = 'La contraseña actual no es correcta.'
                else:
                    nuevo_hash = bcrypt.generate_password_hash(nueva).decode('utf-8')
                    cur = mysql.connection.cursor()
                    cur.execute("UPDATE usuarios SET password_hash=%s WHERE id=%s", (nuevo_hash, user_id))
                    mysql.connection.commit()
                    cur.close()
                    exito = 'Contraseña actualizada correctamente.'

    return render_template('usuario/configuracion.html', usuario=usuario, error=error, exito=exito)