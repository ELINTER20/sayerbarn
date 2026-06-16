# ─────────────────────────────────────────────────────────────
# routes/public.py
#
# Blueprint de rutas públicas — accesibles sin login.
#
# Rutas:
#   GET  /
#   GET  /catalogo
#   GET  /producto/<id>
#   GET  /producto/<id>/info
#   GET  /asesoria
#   GET  /asesoria/resultado/<id>
#   GET  /carrito
# ─────────────────────────────────────────────────────────────

from flask import Blueprint, render_template, request, redirect, url_for, abort
from app import mysql
from app.helpers.auth_utils import usuario_actual

public_bp = Blueprint('public', __name__)


# ── Landing page ──────────────────────────────────────────────

@public_bp.route('/')
def index():
    """Página principal con los 3 primeros productos destacados."""
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
    return render_template('index.html', usuario=usuario_actual(), productos=productos_destacados)


# ── Catálogo ──────────────────────────────────────────────────

@public_bp.route('/catalogo')
def catalogo():
    """Lista de productos con filtro opcional por categoría."""
    productos       = []
    categorias      = []
    error           = None
    favoritos_ids   = set()
    usuario         = usuario_actual()
    categoria_filtro = request.args.get('categoria', type=int)

    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
        categorias = cur.fetchall()

        campos = (
            "p.id, p.clave, p.nombre, p.descripcion_ia, p.imagen_url, "
            "p.precio_referencia, p.acabado, p.uso, p.rendimiento_min, "
            "p.sup_madera, p.sup_metal, p.sup_concreto, p.sup_otro, "
            "p.activo, COALESCE(p.stock, 0) AS stock, "
            "p.categoria_id, c.nombre AS categoria "
        )
        orden = (
            "ORDER BY "
            "  p.activo DESC, "
            "  (COALESCE(p.stock,0) > 0) DESC, "
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

    return render_template(
        'catalogo.html',
        productos=productos,
        categorias=categorias,
        categoria_filtro=categoria_filtro,
        usuario=usuario,
        error=error,
        favoritos_ids=favoritos_ids
    )


# ── Detalle de producto ───────────────────────────────────────

@public_bp.route('/producto/<int:producto_id>')
def detalle_producto(producto_id):
    """Página de detalle con complementos asociados."""
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
        abort(404)

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
    return render_template(
        'usuario/producto-detalle.html',
        producto=producto,
        complementos=complementos,
        usuario=usuario_actual()
    )


@public_bp.route('/producto/<int:producto_id>/info')
def info_producto(producto_id):
    """Vista de info rápida del producto (solo productos activos)."""
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
    return render_template(
        'producto-info.html',
        producto=producto,
        complementos=complementos,
        usuario=usuario_actual()
    )


# ── Asesoría ──────────────────────────────────────────────────

@public_bp.route('/asesoria')
def asesoria():
    """Página del asistente de asesoría con IA."""
    return render_template('usuario/asesoria.html', usuario=usuario_actual())


@public_bp.route('/asesoria/resultado/<int:asesoria_id>')
def resultado_asesoria(asesoria_id):
    """Muestra el resultado de una asesoría guardada con el producto recomendado."""
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

    if not resultado:
        cur.close()
        return redirect(url_for('public.asesoria'))

    cur.execute(
        "SELECT p.nombre, p.imagen_url FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s LIMIT 1",
        (resultado['producto_id'],)
    )
    complemento = cur.fetchone()
    cur.close()

    return render_template(
        'usuario/producto-recomendado.html',
        resultado=resultado,
        complemento=complemento,
        usuario=usuario_actual()
    )


# ── Carrito ───────────────────────────────────────────────────

@public_bp.route('/carrito')
def carrito():
    """Página del carrito (lógica del carrito vive en JS/API)."""
    return render_template('carrito.html', usuario=usuario_actual())