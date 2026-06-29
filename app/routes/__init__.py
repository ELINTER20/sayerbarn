from flask import Blueprint, render_template, request, redirect, url_for, make_response, current_app
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity,
    set_access_cookies, unset_jwt_cookies, verify_jwt_in_request
)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from email.message import EmailMessage
import smtplib

from app import mysql, bcrypt

# Blueprint principal: agrupa todas las rutas públicas y de usuario
main = Blueprint('main', __name__)


def _get_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset-salt')


def generate_password_reset_token(email):
    return _get_serializer().dumps(email)


def verify_password_reset_token(token, max_age=3600):
    try:
        return _get_serializer().loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def send_password_reset_email(to_email, reset_link):
    if not current_app.config['MAIL_SERVER'] or not current_app.config['MAIL_USERNAME'] or not current_app.config['MAIL_PASSWORD']:
        return False

    message = EmailMessage()
    message['Subject'] = 'Recuperar contraseña - SayerBarn'
    message['From'] = current_app.config['MAIL_DEFAULT_SENDER']
    message['To'] = to_email
    message.set_content(
        f"Hola,\n\nHaz clic en el siguiente enlace para restablecer tu contraseña:\n\n{reset_link}\n\nEste enlace expirará en 1 hora. Si no solicitaste este cambio, ignora este mensaje.\n"
    )

    try:
        if current_app.config['MAIL_USE_SSL']:
            with smtplib.SMTP_SSL(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
                server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
                server.send_message(message)
        else:
            with smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
                if current_app.config['MAIL_USE_TLS']:
                    server.starttls()
                server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
                server.send_message(message)
        return True
    except Exception as e:
        print(f"[ERROR EMAIL] No se pudo enviar correo: {e}")
        return False


def usuario_actual():
    """Devuelve el usuario logueado como dict, o None si no hay sesión activa."""
    try:
        # Lee el JWT de la cookie sin lanzar error si no existe
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
    # Obtiene los 3 primeros productos activos para mostrarlos como destacados en la landing
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

        # Busca al usuario activo por email en la BD
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, nombre, password_hash, rol FROM usuarios "
            "WHERE email = %s AND activo = 1",
            (email,)
        )
        usuario = cur.fetchone()
        cur.close()

        # Verifica que el usuario exista y que la contraseña coincida con el hash guardado
        if usuario and bcrypt.check_password_hash(usuario['password_hash'], password):
            token = create_access_token(identity=str(usuario['id']))
            # Los admins van al panel de administración; los demás a la landing
            destino = url_for('admin.dashboard') if usuario['rol'] == 'admin' else url_for('main.index')
            response = make_response(redirect(destino))
            # Guarda el token JWT en una cookie segura del navegador
            set_access_cookies(response, token)
            return response

        # Si las credenciales son incorrectas, vuelve al formulario con el error
        return render_template('auth/login.html', error='Correo o contraseña incorrectos.', email=email, usuario=usuario_actual())

    # GET: muestra el formulario vacío
    return render_template('auth/login.html', usuario=usuario_actual())


@main.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirmPassword', '')

        # Valida que todos los campos estén llenos
        if not nombre or not email or not password or not confirm_password:
            return render_template('auth/registro.html', error='Todos los campos son requeridos.', nombre=nombre, email=email, usuario=usuario_actual())

        # Valida que las dos contraseñas coincidan
        if password != confirm_password:
            return render_template('auth/registro.html', error='Las contraseñas no coinciden.', nombre=nombre, email=email, usuario=usuario_actual())

        # Genera el hash de la contraseña antes de guardarla (nunca se guarda en texto plano)
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO usuarios (nombre, email, password_hash) VALUES (%s, %s, %s)",
                (nombre, email, password_hash)
            )
            mysql.connection.commit()
            usuario_id = cur.lastrowid  # ID del nuevo usuario recién creado
            cur.close()
        except Exception as e:
            print(f"[ERROR REGISTRO] {type(e).__name__}: {e}")
            # Error 1062 = Duplicate entry en MySQL (email repetido)
            if hasattr(e, 'args') and e.args and e.args[0] == 1062:
                return render_template('auth/registro.html', error='El correo ya está registrado.', nombre=nombre, email=email, usuario=usuario_actual())
            return render_template('auth/registro.html', error=f'Error al crear la cuenta: {e}', nombre=nombre, email=email, usuario=usuario_actual())

        # Inicia sesión automáticamente después del registro exitoso
        token = create_access_token(identity=str(usuario_id))
        response = make_response(redirect(url_for('main.index')))
        set_access_cookies(response, token)
        return response

    # GET: muestra el formulario vacío
    return render_template('auth/registro.html', usuario=usuario_actual())


@main.route('/logout', methods=['POST'])
def logout():
    # Elimina las cookies JWT del navegador para cerrar la sesión
    response = make_response(redirect(url_for('main.index')))
    unset_jwt_cookies(response)
    return response

@main.route('/recuperar-password', methods=['GET', 'POST'])
def recuperar_password():
    error = None
    success = None
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
                reset_link = url_for('main.reset_password', token=generate_password_reset_token(email), _external=True)
                email_sent = send_password_reset_email(email, reset_link)
                if email_sent:
                    success = 'Si ese correo existe, hemos enviado un enlace de recuperación.'
                else:
                    success = 'No se pudo enviar el correo. Usa el enlace directo de prueba a continuación.'
            else:
                success = 'Si ese correo existe, hemos enviado un enlace de recuperación.'

    show_reset_link = bool(reset_link and (current_app.debug or not current_app.config['MAIL_SERVER'] or not email_sent))
    return render_template(
        'recuperar_password.html',
        error=error,
        success=success,
        reset_link=reset_link if show_reset_link else None,
        usuario=usuario_actual()
    )


@main.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    error = None
    email = verify_password_reset_token(token)
    if not email:
        return render_template('recuperar_password.html', error='El enlace no es válido o expiró. Solicita uno nuevo.', usuario=usuario_actual())

    if request.method == 'POST':
        password = request.form.get('password', '')
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
            return render_template('auth/login.html', success='Tu contraseña ha sido actualizada. Ya puedes iniciar sesión.', email=email, usuario=usuario_actual())

    return render_template('reset_password.html', token=token, error=error, usuario=usuario_actual())


# ── Catálogo (público) ────────────────────────────────────

@main.route('/catalogo')
def catalogo():
    productos = []
    error = None
    favoritos_ids = set()
    usuario = usuario_actual()
    # Filtro de categoría desde URL (?categoria=X)
    categoria_filtro = request.args.get('categoria', type=int)

    try:
        cur = mysql.connection.cursor()
        # Traer categorías para el selector del sidebar
        cur.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
        categorias = cur.fetchall()

        # Query de productos: todos (activos e inactivos), disponibles primero,
        # luego agotados, luego desactivados. Dentro de cada grupo, ordenado por nombre.
        campos = (
            "p.id, p.clave, p.nombre, p.descripcion_ia, p.imagen_url, "
            "p.precio_referencia, p.acabado, p.uso, p.rendimiento_min, "
            "p.sup_madera, p.sup_metal, p.sup_concreto, p.sup_otro, "
            "p.activo, COALESCE(p.stock, 0) AS stock, "
            "p.categoria_id, c.nombre AS categoria "
        )
        orden = (
            "ORDER BY "
            "  p.activo DESC, "               # activos primero
            "  (COALESCE(p.stock,0) > 0) DESC, "  # con stock antes que agotados
            "  p.nombre ASC"
        )

        if categoria_filtro:
            cur.execute(
                f"SELECT {campos}"
                "FROM productos p "
                "LEFT JOIN categorias c ON p.categoria_id = c.id "
                f"WHERE p.categoria_id = %s {orden}",
                (categoria_filtro,)
            )
        else:
            cur.execute(
                f"SELECT {campos}"
                "FROM productos p "
                "LEFT JOIN categorias c ON p.categoria_id = c.id "
                + orden
            )
        productos = cur.fetchall()
        cur.close()
    except Exception:
        categorias = []
        error = 'El catálogo todavía no está disponible. Intenta de nuevo más tarde.'

    if usuario:
        try:
            cur2 = mysql.connection.cursor()
            cur2.execute(
                "SELECT producto_id FROM favoritos WHERE usuario_id = %s",
                (usuario['id'],)
            )
            favoritos_ids = {row['producto_id'] for row in cur2.fetchall()}
            cur2.close()
        except Exception:
            pass

    return render_template('catalogo.html',
                           productos=productos,
                           categorias=categorias,
                           categoria_filtro=categoria_filtro,
                           usuario=usuario,
                           error=error,
                           favoritos_ids=favoritos_ids)


# ── Rutas protegidas (requieren login) ───────────────────

@main.route('/favoritos')
@jwt_required()  # Redirige al login si el usuario no tiene sesión activa
def favoritos():
    # Muestra todos los productos que el usuario ha marcado como favoritos
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
    return render_template('usuarioregistrado-favoritos.html', productos=productos, usuario=usuario_actual())


@main.route('/historial')
@jwt_required()
def historial():
    # Muestra el historial de asesorías realizadas por el usuario
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
    # Agrega un producto a favoritos; INSERT IGNORE evita duplicados silenciosamente
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
    # Regresa a la página anterior; si no hay referrer, va al catálogo
    return redirect(request.referrer or url_for('main.catalogo'))


@main.route('/asesoria')
def asesoria():
    # Muestra la página del asistente de asesoría con IA
    return render_template('Usuario-Asesoria.html', usuario=usuario_actual())


@main.route('/asesoria/resultado/<int:asesoria_id>')
def resultado_asesoria(asesoria_id):
    # Muestra el resultado de una asesoría específica con el producto recomendado
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT a.superficie, a.uso, a.area_m2, a.litros_estimados, "
        "p.id AS producto_id, p.nombre, p.descripcion_ia, p.imagen_url, "
        "p.rendimiento_min, p.link_compra_ml, p.acabado, p.ficha_tecnica_url "
        "FROM asesorias a "
        "JOIN productos p ON a.producto_recomendado_id = p.id "
        "WHERE a.id = %s",
        (asesoria_id,)
    )
    resultado = cur.fetchone()

    # Si no existe la asesoría, regresa al formulario
    if not resultado:
        cur.close()
        return redirect(url_for('main.asesoria'))

    # Busca el complemento recomendado para el producto (ej: diluyente o catalizador)
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


@main.route('/producto/<int:producto_id>')
def detalle_producto(producto_id):
    # Muestra la página de detalle de un producto con sus datos y complementos
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.clave, p.nombre, p.descripcion_ia, p.imagen_url, "
        "p.precio_referencia, p.acabado, p.uso, p.rendimiento_min, p.link_compra_ml, "
        "p.ficha_tecnica_url, p.activo, p.sup_madera, p.sup_metal, p.sup_concreto, p.sup_otro, "
        "COALESCE(p.stock, 0) AS stock, "
        "c.nombre AS categoria "
        "FROM productos p "
        "LEFT JOIN categorias c ON p.categoria_id = c.id "
        "WHERE p.id = %s",
        (producto_id,)
    )
    producto = cur.fetchone()
    if not producto:
        cur.close()
        from flask import abort
        abort(404)  # Producto no encontrado
    # Obtiene todos los complementos (diluyentes, catalizadores, etc.) del producto
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.link_compra_ml, "
        "p.activo, COALESCE(p.stock, 0) AS stock, "
        "c.tipo, c.proporcion "
        "FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s",
        (producto_id,)
    )
    complementos = cur.fetchall()
    cur.close()
    return render_template('Usuario-ProductoDetalle.html',
                           producto=producto,
                           complementos=complementos,
                           usuario=usuario_actual())


@main.route('/producto/<int:producto_id>/info')
def info_producto(producto_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.clave, p.nombre, p.descripcion_ia, p.imagen_url, "
        "p.precio_referencia, p.acabado, p.uso, p.rendimiento_min, p.link_compra_ml, "
        "p.ficha_tecnica_url, p.sup_madera, p.sup_metal, p.sup_concreto, p.sup_otro, "
        "c.nombre AS categoria "
        "FROM productos p "
        "LEFT JOIN categorias c ON p.categoria_id = c.id "
        "WHERE p.id = %s AND p.activo = 1",
        (producto_id,)
    )
    producto = cur.fetchone()
    if not producto:
        cur.close()
        from flask import abort
        abort(404)
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.link_compra_ml, c.tipo, c.proporcion "
        "FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s",
        (producto_id,)
    )
    complementos = cur.fetchall()
    cur.close()
    return render_template('producto-info.html',
                           producto=producto,
                           complementos=complementos,
                           usuario=usuario_actual())


@main.route('/carrito')
def carrito():
    return render_template('carrito.html', usuario=usuario_actual())


@main.route('/mi-cuenta')
@jwt_required()
def mi_cuenta():
    """Hub de la cuenta del usuario: links a pedidos, historial y favoritos."""
    usuario = usuario_actual()
    return render_template('mi-cuenta.html', usuario=usuario)


@main.route('/mi-cuenta/configuracion', methods=['GET', 'POST'])
@jwt_required()
def configuracion():
    """Permite al usuario cambiar su nombre, correo o contraseña."""
    user_id = get_jwt_identity()
    usuario = usuario_actual()
    error = None
    exito = None

    if request.method == 'POST':
        accion = request.form.get('accion', '')

        if accion == 'datos':
            nuevo_nombre = request.form.get('nombre', '').strip()
            nuevo_email = request.form.get('email', '').strip().lower()
            confirm_datos = request.form.get('confirm_datos', '')
            if not nuevo_nombre or not nuevo_email or not confirm_datos:
                error = 'El nombre, el correo y la contraseña de confirmación son obligatorios.'
            else:
                # Verificar contraseña antes de permitir cambios de datos personales
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
                        exito = 'Datos actualizados correctamente.'
                        usuario = usuario_actual()
                    except Exception as e:
                        if hasattr(e, 'args') and e.args and e.args[0] == 1062:
                            error = 'Ese correo ya está registrado por otra cuenta.'
                        else:
                            error = 'Error al actualizar los datos. Intenta de nuevo.'

        elif accion == 'password':
            actual = request.form.get('password_actual', '')
            nueva = request.form.get('password_nueva', '')
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

    return render_template('configuracion.html', usuario=usuario, error=error, exito=exito)


@main.route('/favoritos/eliminar/<int:producto_id>', methods=['POST'])
@jwt_required()
def eliminar_favorito(producto_id):
    # Elimina un producto de la lista de favoritos del usuario
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
        (user_id, producto_id)
    )
    mysql.connection.commit()
    cur.close()
    return redirect(request.referrer or url_for('main.favoritos'))


# ── Checkout y pedidos ────────────────────────────────────

# Lista de estados de la república mexicana para el formulario de checkout
ESTADOS_MX = [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche',
    'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima',
    'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo',
    'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca',
    'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa',
    'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán',
    'Zacatecas',
]


@main.route('/checkout', methods=['GET', 'POST'])
@main.route('/checkout/<int:producto_id>', methods=['GET', 'POST'])
def checkout(producto_id=None):
    """Formulario de compra. Soporta:
    - Un solo producto (desde botón "Comprar aquí")
    - Múltiples productos del carrito (campo JSON 'carrito_items')"""
    import json as _json
    import re as _re

    usuario = usuario_actual()

    # Usuarios no registrados no pueden hacer pedidos
    if not usuario:
        return redirect(url_for('main.login'))

    # ── Leer items: carrito JSON o producto individual ────────────────
    carrito_items = []   # [{id, nombre, precio, imagen, cantidad}, ...]

    if request.method == 'POST':
        raw = request.form.get('carrito_items', '').strip()
        if raw:
            try:
                carrito_items = _json.loads(raw)
            except Exception:
                carrito_items = []

        # Si viene de producto individual sin JSON del carrito
        if not carrito_items and producto_id:
            cantidad = request.form.get('cantidad', 1, type=int)
            carrito_items = [{'id': producto_id, 'cantidad': max(1, cantidad)}]

    else:  # GET
        raw = request.args.get('carrito_items', '').strip()
        if raw:
            try:
                carrito_items = _json.loads(raw)
            except Exception:
                carrito_items = []
        if not carrito_items and producto_id:
            carrito_items = [{'id': producto_id, 'cantidad': 1}]

    if not carrito_items:
        return redirect(url_for('main.carrito'))

    # ── Validar stock de todos los items antes de mostrar el formulario ──
    cur = mysql.connection.cursor()
    productos_validos = []
    productos_sin_stock = []

    for item in carrito_items:
        pid = int(item.get('id', 0))
        qty = int(item.get('cantidad', 1))
        cur.execute(
            "SELECT id, nombre, imagen_url, precio_referencia, uso, activo, "
            "COALESCE(stock,0) AS stock "
            "FROM productos WHERE id = %s",
            (pid,)
        )
        p = cur.fetchone()
        if not p or not p['activo']:
            continue
        if p['stock'] < qty:
            # Si hay algo pero menos de lo pedido, ajustar o marcar sin stock
            if p['stock'] > 0:
                qty = p['stock']   # da lo que hay
            else:
                productos_sin_stock.append(p['nombre'])
                continue
        item['cantidad'] = qty
        item['nombre']   = item.get('nombre') or p['nombre']
        item['precio']   = float(p['precio_referencia']) if p.get('precio_referencia') else 0
        item['imagen']   = item.get('imagen') or p.get('imagen_url') or ''
        productos_validos.append({'producto': p, 'item': item})

    cur.close()

    if not productos_validos:
        return redirect(url_for('main.carrito'))

    # Producto "principal" para mostrar en el resumen (primer item)
    producto_principal = productos_validos[0]['producto']

    if request.method == 'POST':
        nombre_comprador = request.form.get('nombre_comprador', '').strip()
        telefono         = request.form.get('telefono', '').strip()
        direccion        = request.form.get('direccion', '').strip()
        ciudad           = request.form.get('ciudad', '').strip()
        estado_mx        = request.form.get('estado_mx', '').strip()

        form_data = {
            'nombre_comprador': nombre_comprador,
            'telefono': telefono,
            'direccion': direccion,
            'ciudad': ciudad,
            'estado_mx': estado_mx,
            'carrito_items': _json.dumps(carrito_items),
        }

        if not nombre_comprador or not telefono or not direccion or not ciudad or not estado_mx:
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='Por favor completa todos los campos obligatorios.')

        # Validaciones de datos reales
        import re as _re
        if len(nombre_comprador) < 3 or not _re.search(r'[a-záéíóúñA-ZÁÉÍÓÚÑ]', nombre_comprador):
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='El nombre debe tener al menos 3 caracteres y contener letras.')
        if not _re.match(r'^[\d\s\+\-\(\)]{7,20}$', telefono):
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='El teléfono debe contener entre 7 y 20 dígitos.')
        if len(direccion) < 8:
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='La dirección parece demasiado corta. Incluye calle, número y colonia.')
        if len(ciudad) < 3:
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='Ingresa el nombre completo de tu ciudad.')

        # ── Insertar pedidos y descontar stock atómicamente ───────────
        pedidos_ids = []
        try:
            cur = mysql.connection.cursor()
            for entry in productos_validos:
                p   = entry['producto']
                qty = entry['item']['cantidad']
                precio_unit = float(p['precio_referencia']) if p.get('precio_referencia') else None
                total       = round(precio_unit * qty, 2) if precio_unit else None

                # Verificar stock en el momento exacto de la compra (concurrencia)
                cur.execute(
                    "SELECT COALESCE(stock,0) AS stock FROM productos WHERE id = %s FOR UPDATE",
                    (p['id'],)
                )
                stock_actual = cur.fetchone()['stock']
                if stock_actual < qty:
                    qty = stock_actual  # ajusta a lo disponible
                if qty <= 0:
                    continue  # otro usuario se adelantó, se omite este item

                # Insertar el pedido
                cur.execute("""
                    INSERT INTO pedidos
                      (usuario_id, producto_id, canal,
                       nombre_comprador, telefono, direccion, ciudad, estado_mx,
                       cantidad, precio_unitario, total, estado_pedido)
                    VALUES (%s, %s, 'directo', %s, %s, %s, %s, %s, %s, %s, %s, 'pendiente')
                """, (
                    usuario['id'] if usuario else None,
                    p['id'],
                    nombre_comprador, telefono, direccion, ciudad, estado_mx,
                    qty, precio_unit, total,
                ))
                pedido_id = cur.lastrowid
                pedidos_ids.append(pedido_id)

                # Descontar stock inmediatamente
                cur.execute(
                    "UPDATE productos SET stock = GREATEST(0, stock - %s) WHERE id = %s",
                    (qty, p['id'])
                )

            mysql.connection.commit()
            cur.close()
        except Exception as e:
            mysql.connection.rollback()
            print(f"[ERROR CHECKOUT] {type(e).__name__}: {e}")
            return render_template('checkout.html',
                                   producto=producto_principal,
                                   productos_validos=productos_validos,
                                   productos_sin_stock=productos_sin_stock,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='Ocurrió un error al registrar tu pedido. Intenta de nuevo.')

        if not pedidos_ids:
            return redirect(url_for('main.carrito'))

        return redirect(url_for('main.confirmacion_pedido', pedido_id=pedidos_ids[0]))

    # GET
    return render_template('checkout.html',
                           producto=producto_principal,
                           productos_validos=productos_validos,
                           productos_sin_stock=productos_sin_stock,
                           usuario=usuario,
                           estados_mx=ESTADOS_MX,
                           form={'carrito_items': _json.dumps(carrito_items)})


@main.route('/pedido/confirmacion/<int:pedido_id>')
def confirmacion_pedido(pedido_id):
    """Página de confirmación que se muestra tras guardar el pedido."""
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.nombre_comprador, pd.telefono, pd.direccion,
               pd.ciudad, pd.estado_mx, pd.cantidad, pd.total, pd.estado_pedido,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.id = %s
    """, (pedido_id,))
    pedido = cur.fetchone()
    cur.close()

    # Si el pedido no existe (alguien navegó a una URL inventada) redirige al catálogo
    if not pedido:
        return redirect(url_for('main.catalogo'))

    return render_template('confirmacion_pedido.html',
                           pedido=pedido,
                           usuario=usuario_actual())


@main.route('/contacto')
def contacto():
    import json as _json
    from app.tiendas import TIENDAS
    return render_template('contacto.html',
                           tiendas=TIENDAS,
                           tiendas_json=_json.dumps(TIENDAS, ensure_ascii=False),
                           usuario=usuario_actual())


@main.route('/mis-pedidos')
def mis_pedidos():
    """Historial de pedidos del usuario, agrupando items de la misma compra."""
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for('main.login'))
    user_id = usuario['id']
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pd.nombre_comprador, pd.telefono, pd.direccion, pd.ciudad, pd.estado_mx,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.usuario_id = %s
        ORDER BY pd.created_at DESC
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()

    # Agrupar items comprados en la misma sesión (mismo comprador, mismos 10 minutos)
    from collections import OrderedDict
    ventas = OrderedDict()
    for p in rows:
        minuto_base = (p['created_at'].hour * 60 + p['created_at'].minute) // 10 if p['created_at'] else 0
        fecha_dia = str(p['created_at'].date()) if p['created_at'] else 'nd'
        vkey = f"{fecha_dia}|{minuto_base}"
        if vkey not in ventas:
            ventas[vkey] = {
                'id_principal': p['id'],
                'estado_pedido': p['estado_pedido'],
                'created_at': p['created_at'],
                'nombre_comprador': p['nombre_comprador'],
                'telefono': p['telefono'],
                'direccion': p['direccion'],
                'ciudad': p['ciudad'],
                'estado_mx': p['estado_mx'],
                'items': [],  # kept for compatibility
                'productos': [],
                'total': 0.0,
            }
        ventas[vkey]['productos'].append({
            'nombre_producto': p['nombre_producto'],
            'imagen_url': p['imagen_url'],
            'cantidad': p['cantidad'],
            'total': float(p['total']) if p['total'] else 0.0,
        })
        ventas[vkey]['total'] += float(p['total']) if p['total'] else 0.0

    return render_template('usuarioregistrado-pedidos.html',
                           ventas=list(ventas.values()),
                           usuario=usuario)