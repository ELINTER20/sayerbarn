from flask import Blueprint, render_template, request, redirect, url_for, make_response
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity,
    set_access_cookies, unset_jwt_cookies, verify_jwt_in_request
)
from app import mysql, bcrypt

main = Blueprint('main', __name__)


def usuario_actual():
    """Devuelve el usuario logueado como dict, o None."""
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


# ── Rutas públicas ────────────────────────────────────────

@main.route('/')
def index():
    return render_template('LandingPage.html', usuario=usuario_actual())


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
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
            token = create_access_token(identity=str(usuario['id']))
            response = make_response(redirect(url_for('main.index')))
            set_access_cookies(response, token)
            return response

        return render_template('Iniciosesion.html', error='Correo o contraseña incorrectos.')

    return render_template('Iniciosesion.html')


@main.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not nombre or not email or not password:
            return render_template('Registro.html', error='Todos los campos son requeridos.')

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
            # Error 1062 = Duplicate entry en MySQL
            if hasattr(e, 'args') and e.args and e.args[0] == 1062:
                return render_template('Registro.html', error='El correo ya está registrado.')
            return render_template('Registro.html', error=f'Error al crear la cuenta: {e}')

        token = create_access_token(identity=str(usuario_id))
        response = make_response(redirect(url_for('main.index')))
        set_access_cookies(response, token)
        return response

    return render_template('Registro.html')


@main.route('/logout', methods=['POST'])
def logout():
    response = make_response(redirect(url_for('main.login')))
    unset_jwt_cookies(response)
    return response


# ── Catálogo (público) ────────────────────────────────────

@main.route('/catalogo')
def catalogo():
    productos = []
    error = None
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, clave, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso "
            "FROM productos WHERE activo = 1 ORDER BY nombre"
        )
        productos = cur.fetchall()
        cur.close()
    except Exception:
        error = 'El catálogo todavía no está disponible. Intenta de nuevo más tarde.'
    return render_template('Usuario-Catalogo.html', productos=productos, usuario=usuario_actual(), error=error)


# ── Rutas protegidas (requieren login) ───────────────────

@main.route('/favoritos')
@jwt_required()
def favoritos():
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.precio_referencia, p.acabado "
        "FROM favoritos f "
        "JOIN productos p ON f.producto_id = p.id "
        "WHERE f.usuario_id = %s ORDER BY f.created_at DESC",
        (user_id,)
    )
    productos = cur.fetchall()
    cur.close()
    return render_template('usuarioregistrado-favoritos.html', productos=productos, usuario=usuario_actual())


@main.route('/historial')
@jwt_required()
def historial():
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
    return render_template('usuarioregistrado-historial.html', asesorias=asesorias, usuario=usuario_actual())


@main.route('/favoritos/agregar/<int:producto_id>', methods=['POST'])
@jwt_required()
def agregar_favorito(producto_id):
    user_id = get_jwt_identity()
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT IGNORE INTO favoritos (usuario_id, producto_id) VALUES (%s, %s)",
            (user_id, producto_id)
        )
        mysql.connection.commit()
        cur.close()
    except Exception:
        pass
    return redirect(request.referrer or url_for('main.catalogo'))


@main.route('/favoritos/eliminar/<int:producto_id>', methods=['POST'])
@jwt_required()
def eliminar_favorito(producto_id):
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
        (user_id, producto_id)
    )
    mysql.connection.commit()
    cur.close()
    return redirect(request.referrer or url_for('main.favoritos'))
