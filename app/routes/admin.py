from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app import mysql

# Blueprint de administración: todas sus rutas empiezan con /admin
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Decorador que protege rutas: solo permite acceso a usuarios con rol 'admin'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()  # Verifica que haya un JWT válido en la cookie
            user_id = get_jwt_identity()
            cur = mysql.connection.cursor()
            cur.execute("SELECT rol FROM usuarios WHERE id = %s AND activo = 1", (user_id,))
            usuario = cur.fetchone()
            cur.close()
            # Si el usuario no existe o no es admin, devuelve error 403
            if not usuario or usuario['rol'] != 'admin':
                abort(403)
        except Exception:
            # Si no hay sesión válida, redirige al login
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def dashboard():
    cur = mysql.connection.cursor()

    # Cuenta total de productos activos en el catálogo
    cur.execute("SELECT COUNT(*) as total FROM productos WHERE activo = 1")
    productos_activos = cur.fetchone()['total']

    # Cuenta el total de asesorías realizadas en todo el historial
    cur.execute("SELECT COUNT(*) as total FROM asesorias")
    total_asesorias = cur.fetchone()['total']

    # Cuenta publicaciones actualmente en estado 'publicado' en marketplace
    cur.execute("SELECT COUNT(*) as total FROM publicaciones_marketplace WHERE estado = 'publicado'")
    publicaciones_ml = cur.fetchone()['total']

    # Cuenta pedidos pendientes de gestión (pendiente + pagado)
    cur.execute("SELECT COUNT(*) as total FROM pedidos WHERE estado_pedido IN ('pendiente','pagado')")
    pedidos_pendientes = cur.fetchone()['total']

    # Los 5 productos más recomendados por la IA en los últimos 7 días
    cur.execute("""
        SELECT p.nombre, COUNT(a.id) as recomendaciones
        FROM productos p
        JOIN asesorias a ON a.producto_recomendado_id = p.id
        WHERE a.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY p.id, p.nombre
        ORDER BY recomendaciones DESC
        LIMIT 5
    """)
    top_productos = cur.fetchall()
    cur.close()

    return render_template(
        'admin/dashboard.html',
        productos_activos=productos_activos,
        total_asesorias=total_asesorias,
        publicaciones_ml=publicaciones_ml,
        pedidos_pendientes=pedidos_pendientes,
        top_productos=top_productos
    )


# ── Gestión de productos ──────────────────────────────────

@admin_bp.route('/productos')
@admin_required
def productos():
    # Lista productos con paginación (20 por página)
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 20
    offset = (pagina - 1) * por_pagina  # Calcula desde qué registro empezar

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.clave, p.nombre, p.imagen_url, p.uso, p.acabado, p.activo, "
        "c.nombre as categoria "
        "FROM productos p "
        "LEFT JOIN categorias c ON p.categoria_id = c.id "
        "ORDER BY p.created_at DESC LIMIT %s OFFSET %s",
        (por_pagina, offset)
    )
    productos_lista = cur.fetchall()

    # Cuenta el total para calcular cuántas páginas hay
    cur.execute("SELECT COUNT(*) as total FROM productos")
    total = cur.fetchone()['total']
    cur.close()

    return render_template(
        'admin/productos.html',
        productos=productos_lista,
        pagina=pagina,
        total=total,
        por_pagina=por_pagina
    )


@admin_bp.route('/productos/nuevo', methods=['GET', 'POST'])
@admin_required
def agregar_producto():
    """Formulario para crear un nuevo producto en el catálogo.
    GET:  muestra el formulario vacío con la lista de categorías.
    POST: valida los campos obligatorios e inserta el producto en la BD."""

    # Cargar categorías para el selector del formulario
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
    categorias = cur.fetchall()
    cur.close()

    if request.method == 'POST':
        # Recoger todos los campos del formulario
        clave       = request.form.get('clave', '').strip().upper()
        nombre      = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip() or None
        categoria_id= request.form.get('categoria_id', type=int)
        uso         = request.form.get('uso') or None
        acabado     = request.form.get('acabado') or None
        imagen_url  = request.form.get('imagen_url', '').strip() or None
        rendimiento = request.form.get('rendimiento', type=float) or None
        precio      = request.form.get('precio', type=float) or None
        enlace      = request.form.get('enlace', '').strip() or None
        # Checkboxes de superficie: 1 si marcados, 0 si no
        sup_madera  = 1 if request.form.get('sup_madera') else 0
        sup_metal   = 1 if request.form.get('sup_metal') else 0
        sup_concreto= 1 if request.form.get('sup_concreto') else 0
        sup_otro    = 1 if request.form.get('sup_otro') else 0

        # Guardar valores para repoblar el formulario si hay error
        form_data = {
            'clave': clave, 'nombre': nombre, 'descripcion': descripcion,
            'categoria_id': str(categoria_id) if categoria_id else '',
            'uso': uso, 'acabado': acabado, 'imagen_url': imagen_url,
            'rendimiento': rendimiento, 'precio': precio, 'enlace': enlace,
            'sup_madera': sup_madera, 'sup_metal': sup_metal,
            'sup_concreto': sup_concreto, 'sup_otro': sup_otro,
        }

        # Validar campos obligatorios
        if not clave or not nombre or not categoria_id:
            return render_template('admin/agregar_producto.html',
                                   categorias=categorias,
                                   form=form_data,
                                   error='Los campos Clave, Nombre y Categoría son obligatorios.')

        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO productos
                  (clave, nombre, descripcion_ia, categoria_id,
                   uso, acabado,
                   sup_madera, sup_metal, sup_concreto, sup_otro,
                   rendimiento_min, precio_referencia,
                   imagen_url, link_compra_ml, activo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            """, (clave, nombre, descripcion, categoria_id,
                  uso, acabado,
                  sup_madera, sup_metal, sup_concreto, sup_otro,
                  rendimiento, precio,
                  imagen_url, enlace))
            mysql.connection.commit()
            cur.close()
        except Exception as e:
            print(f"[ERROR AGREGAR PRODUCTO] {type(e).__name__}: {e}")
            # Error 1062 = clave duplicada en MySQL
            msg = 'Ya existe un producto con esa clave.' if (hasattr(e, 'args') and e.args and e.args[0] == 1062) \
                  else f'Error al guardar el producto: {e}'
            return render_template('admin/agregar_producto.html',
                                   categorias=categorias,
                                   form=form_data,
                                   error=msg)

        return redirect(url_for('admin.productos'))

    # GET: formulario vacío
    return render_template('admin/agregar_producto.html',
                           categorias=categorias,
                           form={})


@admin_bp.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def editar_producto(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        # Recoge los campos del formulario; campos vacíos se guardan como NULL
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        acabado = request.form.get('acabado') or None
        rendimiento = request.form.get('rendimiento') or None
        enlace = request.form.get('enlace', '').strip() or None
        uso = request.form.get('uso') or None
        imagen_url = request.form.get('imagen_url', '').strip() or None
        # Los checkboxes de superficie: 1 si están marcados, 0 si no
        sup_madera = 1 if request.form.get('sup_madera') else 0
        sup_metal = 1 if request.form.get('sup_metal') else 0
        sup_concreto = 1 if request.form.get('sup_concreto') else 0
        sup_otro = 1 if request.form.get('sup_otro') else 0

        cur.execute("""
            UPDATE productos SET
                nombre = %s, descripcion_ia = %s, acabado = %s,
                rendimiento_min = %s, link_compra_ml = %s, uso = %s,
                imagen_url = %s,
                sup_madera = %s, sup_metal = %s, sup_concreto = %s, sup_otro = %s
            WHERE id = %s
        """, (nombre, descripcion, acabado, rendimiento, enlace, uso,
              imagen_url, sup_madera, sup_metal, sup_concreto, sup_otro, id))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('admin.productos'))

    # GET: carga los datos actuales del producto para prellenar el formulario
    cur.execute("SELECT * FROM productos WHERE id = %s", (id,))
    producto = cur.fetchone()
    cur.close()

    if not producto:
        abort(404)

    return render_template('admin/editar_producto.html', producto=producto)


@admin_bp.route('/productos/<int:id>/toggle', methods=['POST'])
@admin_required
def toggle_producto(id):
    # Alterna el estado activo/inactivo del producto sin borrarlo
    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET activo = NOT activo WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.productos'))


@admin_bp.route('/productos/<int:id>/eliminar', methods=['POST'])
@admin_required
def eliminar_producto(id):
    # Baja lógica: marca el producto como inactivo en vez de borrarlo físicamente
    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET activo = 0 WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.productos'))


# ── Complementos ──────────────────────────────────────────

@admin_bp.route('/complementos')
@admin_required
def complementos():
    # Lista todas las relaciones producto-complemento (ej: barniz + diluyente)
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id, c.tipo, c.proporcion,
               p1.nombre as producto_nombre,
               p2.nombre as complemento_nombre
        FROM complementos c
        JOIN productos p1 ON c.producto_id = p1.id
        JOIN productos p2 ON c.complemento_id = p2.id
        ORDER BY c.id DESC
    """)
    complementos_lista = cur.fetchall()

    # Carga la lista de productos activos para el selector del formulario de agregar
    cur.execute("SELECT id, nombre FROM productos WHERE activo = 1 ORDER BY nombre")
    productos_lista = cur.fetchall()
    cur.close()

    return render_template(
        'admin/complementos.html',
        complementos=complementos_lista,
        productos=productos_lista
    )


@admin_bp.route('/complementos/agregar', methods=['POST'])
@admin_required
def agregar_complemento():
    # Crea una nueva relación entre un producto y su complemento
    producto_id = request.form.get('producto_id', type=int)
    complemento_id = request.form.get('complemento_id', type=int)
    tipo = request.form.get('tipo')
    proporcion = request.form.get('proporcion', '').strip() or None

    # Valida que los campos obligatorios estén presentes
    if not producto_id or not complemento_id or not tipo:
        return redirect(url_for('admin.complementos'))

    cur = mysql.connection.cursor()
    cur.execute(
        "INSERT INTO complementos (producto_id, complemento_id, tipo, proporcion) VALUES (%s, %s, %s, %s)",
        (producto_id, complemento_id, tipo, proporcion)
    )
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.complementos'))


@admin_bp.route('/complementos/<int:id>/eliminar', methods=['POST'])
@admin_required
def eliminar_complemento(id):
    # Elimina permanentemente la relación complemento de la BD
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM complementos WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.complementos'))


# ── Publicaciones Marketplace ─────────────────────────────

@admin_bp.route('/pedidos')
@admin_required
def pedidos():
    """Lista todos los pedidos con filtro opcional por estado.
    Muestra canal, comprador, ubicación (alerta si no es Acapulco) y selector de estado."""
    filtro_estado = request.args.get('estado', '').strip() or None

    cur = mysql.connection.cursor()
    if filtro_estado:
        # Filtra por estado si se pasó el parámetro ?estado=
        cur.execute("""
            SELECT pd.id, pd.nombre_comprador, pd.telefono,
                   pd.ciudad, pd.estado_mx, pd.canal,
                   pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
                   pr.nombre AS nombre_producto, pr.imagen_url
            FROM pedidos pd
            JOIN productos pr ON pd.producto_id = pr.id
            WHERE pd.estado_pedido = %s
            ORDER BY pd.created_at DESC
        """, (filtro_estado,))
    else:
        # Sin filtro: todos los pedidos del más reciente al más antiguo
        cur.execute("""
            SELECT pd.id, pd.nombre_comprador, pd.telefono,
                   pd.ciudad, pd.estado_mx, pd.canal,
                   pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
                   pr.nombre AS nombre_producto, pr.imagen_url
            FROM pedidos pd
            JOIN productos pr ON pd.producto_id = pr.id
            ORDER BY pd.created_at DESC
        """)
    pedidos_lista = cur.fetchall()
    cur.close()

    return render_template('admin/pedidos.html',
                           pedidos=pedidos_lista,
                           filtro_estado=filtro_estado)


@admin_bp.route('/pedidos/<int:pedido_id>/estado', methods=['POST'])
@admin_required
def cambiar_estado_pedido(pedido_id):
    """Actualiza el estado de un pedido desde el panel admin.
    Acepta solo los valores válidos del ENUM para evitar inserciones incorrectas."""
    estados_validos = {'pendiente', 'pagado', 'en_proceso', 'entregado', 'cancelado'}
    nuevo_estado = request.form.get('estado', '').strip()

    if nuevo_estado in estados_validos:
        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE pedidos SET estado_pedido = %s WHERE id = %s",
            (nuevo_estado, pedido_id)
        )
        mysql.connection.commit()
        cur.close()

    # Conserva el filtro activo al volver a la lista
    filtro = request.args.get('estado', '')
    if filtro:
        return redirect(url_for('admin.pedidos', estado=filtro))
    return redirect(url_for('admin.pedidos'))


@admin_bp.route('/publicar')
@admin_required
def publicar():
    # Muestra las últimas 50 publicaciones en marketplace con su estado
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pm.id, pm.canal, pm.estado, pm.created_at,
               p.nombre as producto_nombre, p.imagen_url
        FROM publicaciones_marketplace pm
        JOIN productos p ON pm.producto_id = p.id
        ORDER BY pm.created_at DESC
        LIMIT 50
    """)
    publicaciones = cur.fetchall()
    cur.close()
    return render_template('admin/publicar.html', publicaciones=publicaciones)
