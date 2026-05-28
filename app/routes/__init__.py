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
    productos_destacados = []
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso "
            "FROM productos WHERE activo = 1 ORDER BY id LIMIT 3"
        )
        productos_destacados = cur.fetchall()
        cur.close()
    except Exception:
        pass
    return render_template('LandingPage.html', usuario=usuario_actual(), productos=productos_destacados)


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

        return render_template('Iniciosesion.html', error='Correo o contraseña incorrectos.', email=email, usuario=usuario_actual())

    return render_template('Iniciosesion.html', usuario=usuario_actual())


@main.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirmPassword', '')

        if not nombre or not email or not password or not confirm_password:
            return render_template('Registro.html', error='Todos los campos son requeridos.', nombre=nombre, email=email, usuario=usuario_actual())

        if password != confirm_password:
            return render_template('Registro.html', error='Las contraseñas no coinciden.', nombre=nombre, email=email, usuario=usuario_actual())

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
                return render_template('Registro.html', error='El correo ya está registrado.', nombre=nombre, email=email, usuario=usuario_actual())
            return render_template('Registro.html', error=f'Error al crear la cuenta: {e}', nombre=nombre, email=email, usuario=usuario_actual())

        token = create_access_token(identity=str(usuario_id))
        response = make_response(redirect(url_for('main.index')))
        set_access_cookies(response, token)
        return response

    return render_template('Registro.html', usuario=usuario_actual())


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
            "SELECT p.id, p.clave, p.nombre, p.descripcion_ia, p.imagen_url, "
            "p.precio_referencia, p.acabado, p.uso, p.rendimiento_min, "
            "p.sup_madera, p.sup_metal, p.sup_concreto, p.sup_otro, "
            "c.nombre AS categoria "
            "FROM productos p "
            "LEFT JOIN categorias c ON p.categoria_id = c.id "
            "WHERE p.activo = 1 ORDER BY p.nombre"
        )
        productos = cur.fetchall()
        cur.close()
    except Exception:
        error = 'El catálogo todavía no está disponible. Intenta de nuevo más tarde.'
    return render_template('catalogo.html', productos=productos, usuario=usuario_actual(), error=error)


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
    return redirect(request.referrer or url_for('main.catalogo'))


@main.route('/chat')
def chat_asesoria():
    return render_template('Usuario-ChatAsesoria.html', usuario=usuario_actual())


@main.route('/asesoria', methods=['GET', 'POST'])
def asesoria():
    if request.method == 'GET':
        return render_template('Usuario-Asesoria.html', usuario=usuario_actual())

    superficie = (request.form.get('superficie_custom') or request.form.get('superficie', '')).strip()
    uso = request.form.get('uso', '').strip()
    area_m2_str = request.form.get('area_m2', '').strip()

    if not superficie or not uso or not area_m2_str:
        return render_template('Usuario-Asesoria.html',
                               error='Todos los campos son requeridos.',
                               usuario=usuario_actual())

    try:
        area_m2 = float(area_m2_str)
        if area_m2 <= 0:
            raise ValueError
    except ValueError:
        return render_template('Usuario-Asesoria.html',
                               error='El área debe ser un número mayor a 0.',
                               usuario=usuario_actual())

    col_map = {
        'madera': 'sup_madera',
        'metal': 'sup_metal',
        'concreto': 'sup_concreto',
        'otro': 'sup_otro',
    }
    sup_col = col_map.get(superficie.lower(), 'sup_otro')

    cur = mysql.connection.cursor()
    cur.execute(
        f"SELECT id, nombre, descripcion_ia, imagen_url, rendimiento_min, link_compra_ml, acabado "
        f"FROM productos WHERE {sup_col} = 1 AND (uso = %s OR uso = 'ambos') AND activo = 1 "
        f"ORDER BY rendimiento_min DESC LIMIT 1",
        (uso,)
    )
    producto = cur.fetchone()

    if not producto:
        cur.close()
        return render_template('Usuario-AsesoriaError.html', usuario=usuario_actual())

    litros = round(area_m2 / float(producto['rendimiento_min']), 2) if producto['rendimiento_min'] else None

    cur.execute(
        "SELECT p.nombre, p.imagen_url FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s LIMIT 1",
        (producto['id'],)
    )
    complemento = cur.fetchone()

    usuario = usuario_actual()
    user_id = usuario['id'] if usuario else None

    cur.execute(
        "INSERT INTO asesorias (usuario_id, superficie, uso, area_m2, litros_estimados, producto_recomendado_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, superficie, uso, area_m2, litros, producto['id'])
    )
    mysql.connection.commit()
    asesoria_id = cur.lastrowid
    cur.close()

    return redirect(url_for('main.resultado_asesoria', asesoria_id=asesoria_id))


@main.route('/asesoria/resultado/<int:asesoria_id>')
def resultado_asesoria(asesoria_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT a.superficie, a.uso, a.area_m2, a.litros_estimados, "
        "p.id AS producto_id, p.nombre, p.descripcion_ia, p.imagen_url, "
        "p.rendimiento_min, p.link_compra_ml, p.acabado "
        "FROM asesorias a "
        "JOIN productos p ON a.producto_recomendado_id = p.id "
        "WHERE a.id = %s",
        (asesoria_id,)
    )
    resultado = cur.fetchone()

    if not resultado:
        cur.close()
        return render_template('Usuario-AsesoriaError.html', usuario=usuario_actual())

    cur.execute(
        "SELECT p.nombre, p.imagen_url FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s LIMIT 1",
        (resultado['producto_id'],)
    )
    complemento = cur.fetchone()
    cur.close()

    return render_template('Usuario-ProductoRecomendado.html',
                           resultado=resultado,
                           complemento=complemento,
                           usuario=usuario_actual())


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
