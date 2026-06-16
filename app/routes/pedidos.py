# ─────────────────────────────────────────────────────────────
# routes/pedidos.py
#
# Blueprint de compra directa y seguimiento de pedidos.
#
# Rutas:
#   GET/POST  /checkout
#   GET/POST  /checkout/<producto_id>
#   GET       /pedido/confirmacion/<pedido_id>
#   GET       /mis-pedidos
# ─────────────────────────────────────────────────────────────

import json
import re
from collections import OrderedDict

from flask import Blueprint, render_template, request, redirect, url_for
from app import mysql
from app.helpers.auth_utils import usuario_actual

pedidos_bp = Blueprint('pedidos', __name__)

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


def _leer_carrito_items(producto_id=None):
    """Lee los items del carrito desde el request (POST o GET).

    Soporta:
    - JSON en el campo 'carrito_items' (múltiples productos desde el carrito)
    - producto_id individual (botón "Comprar" en detalle de producto)

    Devuelve una lista de dicts con al menos {id, cantidad}.
    """
    carrito_items = []
    raw = (request.form if request.method == 'POST' else request.args).get('carrito_items', '').strip()

    if raw:
        try:
            carrito_items = json.loads(raw)
        except Exception:
            carrito_items = []

    if not carrito_items and producto_id:
        cantidad = request.form.get('cantidad', 1, type=int) if request.method == 'POST' else 1
        carrito_items = [{'id': producto_id, 'cantidad': max(1, cantidad)}]

    return carrito_items


def _validar_stock(carrito_items):
    """Verifica disponibilidad de stock para todos los items.

    Devuelve (productos_validos, productos_sin_stock).
    productos_validos: lista de {producto, item} con cantidades ajustadas.
    productos_sin_stock: lista de nombres de productos sin stock.
    """
    cur = mysql.connection.cursor()
    productos_validos    = []
    productos_sin_stock  = []

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
    return productos_validos, productos_sin_stock


def _validar_formulario(form_data):
    """Valida los campos del formulario de checkout.

    Devuelve (True, None) si todo está bien, o (False, mensaje_error).
    """
    nombre_comprador = form_data.get('nombre_comprador', '')
    telefono         = form_data.get('telefono', '')
    direccion        = form_data.get('direccion', '')
    ciudad           = form_data.get('ciudad', '')
    estado_mx        = form_data.get('estado_mx', '')

    if not all([nombre_comprador, telefono, direccion, ciudad, estado_mx]):
        return False, 'Por favor completa todos los campos obligatorios.'

    if len(nombre_comprador) < 3 or not re.search(r'[a-záéíóúñA-ZÁÉÍÓÚÑ]', nombre_comprador):
        return False, 'El nombre debe tener al menos 3 caracteres y contener letras.'

    if not re.match(r'^[\d\s\+\-\(\)]{7,20}$', telefono):
        return False, 'El teléfono debe contener entre 7 y 20 dígitos.'

    if len(direccion) < 8:
        return False, 'La dirección parece demasiado corta. Incluye calle, número y colonia.'

    if len(ciudad) < 3:
        return False, 'Ingresa el nombre completo de tu ciudad.'

    return True, None


# ── Checkout ──────────────────────────────────────────────────

@pedidos_bp.route('/checkout', methods=['GET', 'POST'])
@pedidos_bp.route('/checkout/<int:producto_id>', methods=['GET', 'POST'])
def checkout(producto_id=None):
    """Formulario de compra directa.

    Acepta un producto individual o múltiples items del carrito via JSON.
    Valida stock en dos momentos: al mostrar el formulario y al confirmar
    el pedido (SELECT ... FOR UPDATE para evitar sobreventa).
    """
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for('auth.login'))

    carrito_items = _leer_carrito_items(producto_id)
    if not carrito_items:
        return redirect(url_for('public.carrito'))

    productos_validos, productos_sin_stock = _validar_stock(carrito_items)
    if not productos_validos:
        return redirect(url_for('public.carrito'))

    producto_principal = productos_validos[0]['producto']

    if request.method == 'POST':
        form_data = {
            'nombre_comprador': request.form.get('nombre_comprador', '').strip(),
            'telefono':         request.form.get('telefono', '').strip(),
            'direccion':        request.form.get('direccion', '').strip(),
            'ciudad':           request.form.get('ciudad', '').strip(),
            'estado_mx':        request.form.get('estado_mx', '').strip(),
            'carrito_items':    json.dumps(carrito_items),
        }

        valido, error_msg = _validar_formulario(form_data)
        if not valido:
            return render_template(
                'checkout.html',
                producto=producto_principal,
                productos_validos=productos_validos,
                productos_sin_stock=productos_sin_stock,
                usuario=usuario,
                estados_mx=ESTADOS_MX,
                form=form_data,
                error=error_msg
            )

        # ── Insertar pedidos y descontar stock ────────────────────
        pedidos_ids = []
        try:
            cur = mysql.connection.cursor()
            for entry in productos_validos:
                p           = entry['producto']
                qty         = entry['item']['cantidad']
                precio_unit = float(p['precio_referencia']) if p.get('precio_referencia') else None
                total       = round(precio_unit * qty, 2) if precio_unit else None

                # Verificar stock en el momento exacto de la compra (FOR UPDATE evita race conditions)
                cur.execute(
                    "SELECT COALESCE(stock,0) AS stock FROM productos WHERE id = %s FOR UPDATE",
                    (p['id'],)
                )
                stock_actual = cur.fetchone()['stock']
                if stock_actual < qty:
                    qty = stock_actual
                if qty <= 0:
                    continue   # otro usuario compró al mismo tiempo, omitir

                cur.execute("""
                    INSERT INTO pedidos
                      (usuario_id, producto_id, canal,
                       nombre_comprador, telefono, direccion, ciudad, estado_mx,
                       cantidad, precio_unitario, total, estado_pedido)
                    VALUES (%s, %s, 'directo', %s, %s, %s, %s, %s, %s, %s, %s, 'pendiente')
                """, (
                    usuario['id'],
                    p['id'],
                    form_data['nombre_comprador'],
                    form_data['telefono'],
                    form_data['direccion'],
                    form_data['ciudad'],
                    form_data['estado_mx'],
                    qty, precio_unit, total,
                ))
                pedidos_ids.append(cur.lastrowid)

                # Descontar stock inmediatamente — GREATEST evita negativos
                cur.execute(
                    "UPDATE productos SET stock = GREATEST(0, stock - %s) WHERE id = %s",
                    (qty, p['id'])
                )

            mysql.connection.commit()
            cur.close()
        except Exception as e:
            mysql.connection.rollback()
            print(f"[ERROR CHECKOUT] {type(e).__name__}: {e}")
            return render_template(
                'checkout.html',
                producto=producto_principal,
                productos_validos=productos_validos,
                productos_sin_stock=productos_sin_stock,
                usuario=usuario,
                estados_mx=ESTADOS_MX,
                form=form_data,
                error='Ocurrió un error al registrar tu pedido. Intenta de nuevo.'
            )

        if not pedidos_ids:
            return redirect(url_for('public.carrito'))

        return redirect(url_for('pedidos.confirmacion_pedido', pedido_id=pedidos_ids[0]))

    # GET: mostrar formulario vacío
    return render_template(
        'checkout.html',
        producto=producto_principal,
        productos_validos=productos_validos,
        productos_sin_stock=productos_sin_stock,
        usuario=usuario,
        estados_mx=ESTADOS_MX,
        form={'carrito_items': json.dumps(carrito_items)}
    )


# ── Confirmación de pedido ────────────────────────────────────

@pedidos_bp.route('/pedido/confirmacion/<int:pedido_id>')
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

    if not pedido:
        return redirect(url_for('public.catalogo'))

    return render_template('confirmacion_pedido.html', pedido=pedido, usuario=usuario_actual())


# ── Mis pedidos ───────────────────────────────────────────────

@pedidos_bp.route('/mis-pedidos')
def mis_pedidos():
    """Historial de pedidos del usuario agrupados por sesión de compra."""
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pd.nombre_comprador, pd.telefono, pd.direccion, pd.ciudad, pd.estado_mx,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.usuario_id = %s
        ORDER BY pd.created_at DESC
    """, (usuario['id'],))
    rows = cur.fetchall()
    cur.close()

    # Agrupar items comprados en la misma sesión (mismo día, mismos 10 minutos)
    ventas = OrderedDict()
    for p in rows:
        minuto_base = (p['created_at'].hour * 60 + p['created_at'].minute) // 10 if p['created_at'] else 0
        fecha_dia   = str(p['created_at'].date()) if p['created_at'] else 'nd'
        vkey        = f"{fecha_dia}|{minuto_base}"

        if vkey not in ventas:
            ventas[vkey] = {
                'id_principal':    p['id'],
                'estado_pedido':   p['estado_pedido'],
                'created_at':      p['created_at'],
                'nombre_comprador': p['nombre_comprador'],
                'telefono':        p['telefono'],
                'direccion':       p['direccion'],
                'ciudad':          p['ciudad'],
                'estado_mx':       p['estado_mx'],
                'productos':       [],
                'total':           0.0,
            }
        ventas[vkey]['productos'].append({
            'nombre_producto': p['nombre_producto'],
            'imagen_url':      p['imagen_url'],
            'cantidad':        p['cantidad'],
            'total':           float(p['total']) if p['total'] else 0.0,
        })
        ventas[vkey]['total'] += float(p['total']) if p['total'] else 0.0

    return render_template(
        'usuario/pedidos.html',
        ventas=list(ventas.values()),
        usuario=usuario
    )