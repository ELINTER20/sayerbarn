from flask import Blueprint, render_template, request, redirect, url_for, make_response
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity,
    set_access_cookies, unset_jwt_cookies, verify_jwt_in_request
)
from app import mysql, bcrypt

# Blueprint principal: agrupa todas las rutas públicas y de usuario
main = Blueprint('main', __name__)


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
            response = make_response(redirect(url_for('main.index')))
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
    response = make_response(redirect(url_for('main.login')))
    unset_jwt_cookies(response)
    return response


# ── Catálogo (público) ────────────────────────────────────

@main.route('/catalogo')
def catalogo():
    # Obtiene todos los productos activos junto con su categoría
    productos = []
    error = None
    favoritos_ids = set()
    usuario = usuario_actual()
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
    return render_template('catalogo.html', productos=productos, usuario=usuario, error=error, favoritos_ids=favoritos_ids)


# ── Rutas protegidas (requieren login) ───────────────────

@main.route('/favoritos')
@jwt_required()  # Redirige al login si el usuario no tiene sesión activa
def favoritos():
    # Muestra todos los productos que el usuario ha marcado como favoritos
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
        abort(404)  # Producto no encontrado o inactivo
    # Obtiene todos los complementos (diluyentes, catalizadores, etc.) del producto
    cur.execute(
        "SELECT p.nombre, p.imagen_url, c.tipo, c.proporcion "
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


@main.route('/checkout/<int:producto_id>', methods=['GET', 'POST'])
def checkout(producto_id):
    """Formulario de compra directa para un producto.
    GET:  muestra el formulario con los datos del producto.
    POST: valida, guarda el pedido en BD y redirige a la confirmación."""

    # Obtener el producto; si no existe o está inactivo devuelve 404
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, nombre, descripcion_ia, imagen_url, precio_referencia, uso "
        "FROM productos WHERE id = %s AND activo = 1",
        (producto_id,)
    )
    producto = cur.fetchone()
    cur.close()

    if not producto:
        from flask import abort
        abort(404)

    usuario = usuario_actual()

    if request.method == 'POST':
        # Recoger y limpiar los datos del formulario
        nombre_comprador = request.form.get('nombre_comprador', '').strip()
        telefono         = request.form.get('telefono', '').strip()
        direccion        = request.form.get('direccion', '').strip()
        ciudad           = request.form.get('ciudad', '').strip()
        estado_mx        = request.form.get('estado_mx', '').strip()
        cantidad         = request.form.get('cantidad', 1, type=int)

        # Guardar los valores para repoblar el formulario si hay error
        form_data = {
            'nombre_comprador': nombre_comprador,
            'telefono': telefono,
            'direccion': direccion,
            'ciudad': ciudad,
            'estado_mx': estado_mx,
            'cantidad': cantidad,
        }

        # Validaciones básicas de campos obligatorios
        if not nombre_comprador or not telefono or not direccion or not ciudad or not estado_mx:
            return render_template('checkout.html',
                                   producto=producto,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='Por favor completa todos los campos obligatorios.')

        if cantidad < 1 or cantidad > 99:
            cantidad = 1

        # Calcular totales a partir del precio de referencia del producto
        precio_unitario = float(producto['precio_referencia']) if producto.get('precio_referencia') else None
        total = round(precio_unitario * cantidad, 2) if precio_unitario else None

        # Insertar el pedido en la BD; usuario_id puede ser NULL si no hay sesión
        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO pedidos
                  (usuario_id, producto_id, canal,
                   nombre_comprador, telefono, direccion, ciudad, estado_mx,
                   cantidad, precio_unitario, total, estado_pedido)
                VALUES (%s, %s, 'directo', %s, %s, %s, %s, %s, %s, %s, %s, 'pendiente')
            """, (
                usuario['id'] if usuario else None,
                producto_id,
                nombre_comprador, telefono, direccion, ciudad, estado_mx,
                cantidad, precio_unitario, total,
            ))
            mysql.connection.commit()
            pedido_id = cur.lastrowid  # ID del pedido recién creado
            cur.close()
        except Exception as e:
            print(f"[ERROR CHECKOUT] {type(e).__name__}: {e}")
            return render_template('checkout.html',
                                   producto=producto,
                                   usuario=usuario,
                                   estados_mx=ESTADOS_MX,
                                   form=form_data,
                                   error='Ocurrió un error al registrar tu pedido. Intenta de nuevo.')

        # Redirigir a la página de confirmación con el ID del pedido recién creado
        return redirect(url_for('main.confirmacion_pedido', pedido_id=pedido_id))

    # GET: mostrar el formulario vacío
    return render_template('checkout.html',
                           producto=producto,
                           usuario=usuario,
                           estados_mx=ESTADOS_MX,
                           form={})


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


@main.route('/mis-pedidos')
@jwt_required()
def mis_pedidos():
    """Historial de pedidos del usuario autenticado, ordenado del más reciente al más antiguo."""
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.usuario_id = %s
        ORDER BY pd.created_at DESC
    """, (user_id,))
    pedidos = cur.fetchall()
    cur.close()
    return render_template('usuarioregistrado-pedidos.html',
                           pedidos=pedidos,
                           usuario=usuario_actual())