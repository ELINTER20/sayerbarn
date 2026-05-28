from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app import mysql

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            cur = mysql.connection.cursor()
            cur.execute("SELECT rol FROM usuarios WHERE id = %s AND activo = 1", (user_id,))
            usuario = cur.fetchone()
            cur.close()
            if not usuario or usuario['rol'] != 'admin':
                abort(403)
        except Exception:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def dashboard():
    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) as total FROM productos WHERE activo = 1")
    productos_activos = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) as total FROM asesorias")
    total_asesorias = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) as total FROM publicaciones_marketplace WHERE estado = 'publicado'")
    publicaciones_ml = cur.fetchone()['total']

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
        'Admin-Dashboard.html',
        productos_activos=productos_activos,
        total_asesorias=total_asesorias,
        publicaciones_ml=publicaciones_ml,
        top_productos=top_productos
    )


# ── Gestión de productos ──────────────────────────────────

@admin_bp.route('/productos')
@admin_required
def productos():
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 20
    offset = (pagina - 1) * por_pagina

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

    cur.execute("SELECT COUNT(*) as total FROM productos")
    total = cur.fetchone()['total']
    cur.close()

    return render_template(
        'Admin-GestionProduc.html',
        productos=productos_lista,
        pagina=pagina,
        total=total,
        por_pagina=por_pagina
    )


@admin_bp.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def editar_producto(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        acabado = request.form.get('acabado') or None
        rendimiento = request.form.get('rendimiento') or None
        enlace = request.form.get('enlace', '').strip() or None
        uso = request.form.get('uso') or None
        imagen_url = request.form.get('imagen_url', '').strip() or None
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

    cur.execute("SELECT * FROM productos WHERE id = %s", (id,))
    producto = cur.fetchone()
    cur.close()

    if not producto:
        abort(404)

    return render_template('Admin-Editar-Eliminar.html', producto=producto)


@admin_bp.route('/productos/<int:id>/toggle', methods=['POST'])
@admin_required
def toggle_producto(id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET activo = NOT activo WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.productos'))


@admin_bp.route('/productos/<int:id>/eliminar', methods=['POST'])
@admin_required
def eliminar_producto(id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET activo = 0 WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.productos'))


# ── Complementos ──────────────────────────────────────────

@admin_bp.route('/complementos')
@admin_required
def complementos():
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

    cur.execute("SELECT id, nombre FROM productos WHERE activo = 1 ORDER BY nombre")
    productos_lista = cur.fetchall()
    cur.close()

    return render_template(
        'admin-complementos.html',
        complementos=complementos_lista,
        productos=productos_lista
    )


@admin_bp.route('/complementos/agregar', methods=['POST'])
@admin_required
def agregar_complemento():
    producto_id = request.form.get('producto_id', type=int)
    complemento_id = request.form.get('complemento_id', type=int)
    tipo = request.form.get('tipo')
    proporcion = request.form.get('proporcion', '').strip() or None

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
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM complementos WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.complementos'))


# ── Publicaciones Marketplace ─────────────────────────────

@admin_bp.route('/publicar')
@admin_required
def publicar():
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
    return render_template('admin-publicarMC.html', publicaciones=publicaciones)
