# ─────────────────────────────────────────────────────────────
# routes/pedidos.py
#
# Blueprint de compra y seguimiento de pedidos con MP integrado.
#
# Flujo de pago:
#   1. GET/POST /checkout        → formulario de envío
#   2. POST     /checkout        → guarda pedido como 'pendiente',
#                                  crea preferencia MP y redirige
#   3. GET      /pago/exitoso    → MP regresa aquí si el pago fue aprobado
#   4. GET      /pago/pendiente  → MP regresa aquí si quedó en revisión
#   5. GET      /pago/fallido    → MP regresa aquí si falló o fue cancelado
#   6. POST     /webhook/mp      → MP notifica cambios de estado (background)
#   7. GET      /pedido/verificar/<id> → el usuario puede consultar su pago manualmente
#   8. GET      /pedido/confirmacion/<id> → vista final del pedido
#   9. GET      /mis-pedidos     → historial del usuario
# ─────────────────────────────────────────────────────────────

import json
import re
import hmac
import hashlib
from collections import OrderedDict

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app
from app import mysql
from app.helpers.auth_utils import usuario_actual
from app.helpers.mp import crear_preferencia, obtener_pago

pedidos_bp = Blueprint('pedidos', __name__)

ESTADOS_MX = [
    'Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche',
    'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima',
    'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo',
    'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca',
    'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa',
    'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán',
    'Zacatecas',
]

# Mapeo de estados de MP a estados internos de SayerBarn
MP_ESTADO = {
    'approved':     'pagado',
    'pending':      'pendiente',
    'in_process':   'pendiente',
    'rejected':     'cancelado',
    'cancelled':    'cancelado',
    'refunded':     'cancelado',
    'charged_back': 'cancelado',
}


# ── Helpers privados ──────────────────────────────────────────

def _leer_carrito_items(producto_id=None):
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
    cur = mysql.connection.cursor()
    productos_validos   = []
    productos_sin_stock = []

    for item in carrito_items:
        pid = int(item.get('id', 0))
        qty = int(item.get('cantidad', 1))
        cur.execute(
            "SELECT id, nombre, imagen_url, precio_referencia, uso, activo, "
            "COALESCE(stock,0) AS stock FROM productos WHERE id = %s",
            (pid,)
        )
        p = cur.fetchone()
        if not p or not p['activo']:
            continue
        if p['stock'] < qty:
            if p['stock'] > 0:
                qty = p['stock']
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


def _actualizar_estado_pedido(pedido_id, nuevo_estado, mp_payment_id=None):
    """Actualiza el estado de un pedido en la BD.

    Si el estado es 'pagado', también guarda el mp_payment_id.
    No descuenta stock aquí — el stock se descuenta en el checkout antes de ir a MP.
    """
    cur = mysql.connection.cursor()
    try:
        if mp_payment_id:
            cur.execute(
                "UPDATE pedidos SET estado_pedido = %s, mp_payment_id = %s WHERE id = %s",
                (nuevo_estado, str(mp_payment_id), pedido_id)
            )
        else:
            cur.execute(
                "UPDATE pedidos SET estado_pedido = %s WHERE id = %s",
                (nuevo_estado, pedido_id)
            )
        mysql.connection.commit()
    except Exception as e:
        mysql.connection.rollback()
        print(f"[ERROR] _actualizar_estado_pedido: {e}")
    finally:
        cur.close()


# ── Checkout ──────────────────────────────────────────────────

@pedidos_bp.route('/checkout', methods=['GET', 'POST'])
@pedidos_bp.route('/checkout/<int:producto_id>', methods=['GET', 'POST'])
def checkout(producto_id=None):
    """Formulario de datos de envío.

    Al confirmar:
    1. Guarda el pedido como 'pendiente' con mp_preference_id
    2. Redirige al usuario a Mercado Pago para pagar
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

        # ── Guardar pedidos en BD ──────────────────────────────
        pedidos_ids = []
        try:
            cur = mysql.connection.cursor()
            for entry in productos_validos:
                p           = entry['producto']
                qty         = entry['item']['cantidad']
                precio_unit = float(p['precio_referencia']) if p.get('precio_referencia') else None
                total       = round(precio_unit * qty, 2) if precio_unit else None

                cur.execute(
                    "SELECT COALESCE(stock,0) AS stock FROM productos WHERE id = %s FOR UPDATE",
                    (p['id'],)
                )
                stock_actual = cur.fetchone()['stock']
                if stock_actual < qty:
                    qty = stock_actual
                if qty <= 0:
                    continue

                cur.execute("""
                    INSERT INTO pedidos
                      (usuario_id, producto_id, canal,
                       nombre_comprador, telefono, direccion, ciudad, estado_mx,
                       cantidad, precio_unitario, total, estado_pedido)
                    VALUES (%s, %s, 'directo', %s, %s, %s, %s, %s, %s, %s, %s, 'pendiente')
                """, (
                    usuario['id'], p['id'],
                    form_data['nombre_comprador'], form_data['telefono'],
                    form_data['direccion'], form_data['ciudad'], form_data['estado_mx'],
                    qty, precio_unit, total,
                ))
                pedidos_ids.append(cur.lastrowid)

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

        pedido_principal_id = pedidos_ids[0]

        # ── Crear preferencia de Mercado Pago ─────────────────
        base_url = current_app.config.get('BASE_URL', 'https://sayerbarn.onrender.com')

        items_mp = [
            {
                'producto_id': entry['producto']['id'],
                'title':       entry['item']['nombre'],
                'quantity':    entry['item']['cantidad'],
                'unit_price':  entry['item']['precio'],
            }
            for entry in productos_validos
        ]

        urls_retorno = {
            'success': f"{base_url}/pago/exitoso",
            'failure': f"{base_url}/pago/fallido",
            'pending': f"{base_url}/pago/pendiente",
            'webhook': f"{base_url}/webhook/mp",
        }

        preference_id, init_point = crear_preferencia(
            pedido_id       = pedido_principal_id,
            items           = items_mp,
            datos_comprador = {'nombre': form_data['nombre_comprador'], 'email': usuario.get('email', '')},
            urls            = urls_retorno,
        )

        if preference_id and init_point:
            # Guardar el preference_id para poder rastrear el pago después
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE pedidos SET mp_preference_id = %s WHERE id IN %s",
                (preference_id, tuple(pedidos_ids))
            )
            mysql.connection.commit()
            cur.close()
            # Redirigir al usuario a Mercado Pago
            return redirect(init_point)
        else:
            # MP falló — el pedido quedó guardado como pendiente,
            # el usuario puede intentar pagar después desde "mis pedidos"
            return redirect(url_for('pedidos.confirmacion_pedido', pedido_id=pedido_principal_id))

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


# ── Retornos de Mercado Pago ──────────────────────────────────

@pedidos_bp.route('/pago/exitoso')
def pago_exitoso():
    """MP redirige aquí cuando el pago fue aprobado.

    Actualiza el pedido a 'pagado' usando los parámetros que MP
    manda en la URL (?payment_id=...&external_reference=...).
    """
    payment_id         = request.args.get('payment_id')
    external_reference = request.args.get('external_reference')  # nuestro pedido_id
    estado_mp          = request.args.get('status', 'approved')

    if payment_id and external_reference:
        nuevo_estado = MP_ESTADO.get(estado_mp, 'pendiente')
        _actualizar_estado_pedido(int(external_reference), nuevo_estado, payment_id)

    pedido_id = int(external_reference) if external_reference else None
    return redirect(url_for('pedidos.confirmacion_pedido', pedido_id=pedido_id) if pedido_id
                    else url_for('usuario.mis_pedidos'))


@pedidos_bp.route('/pago/pendiente')
def pago_pendiente():
    """MP redirige aquí cuando el pago quedó en revisión."""
    external_reference = request.args.get('external_reference')
    payment_id         = request.args.get('payment_id')

    if external_reference:
        _actualizar_estado_pedido(int(external_reference), 'pendiente', payment_id)

    pedido_id = int(external_reference) if external_reference else None
    return render_template(
        'confirmacion_pedido.html',
        pedido=_get_pedido(pedido_id),
        mensaje_mp='Tu pago está en revisión. Te notificaremos cuando sea confirmado.',
        usuario=usuario_actual()
    )


@pedidos_bp.route('/pago/fallido')
def pago_fallido():
    """MP redirige aquí cuando el pago fue rechazado o cancelado.
    Regresa al carrito con un aviso — el carrito sigue intacto en localStorage.
    """
    external_reference = request.args.get('external_reference')

    if external_reference:
        _actualizar_estado_pedido(int(external_reference), 'cancelado')

    return redirect(url_for('public.carrito', pago='fallido'))


# ── Webhook de Mercado Pago ───────────────────────────────────

@pedidos_bp.route('/webhook/mp', methods=['POST'])
def webhook_mp():
    """Recibe notificaciones de MP cuando cambia el estado de un pago.

    MP puede notificar múltiples veces — el endpoint debe ser idempotente.
    Siempre responde 200 para que MP no reintente indefinidamente.
    """
    data = request.get_json(silent=True) or {}
    topic = data.get('type') or request.args.get('topic', '')

    if topic == 'payment':
        payment_id = data.get('data', {}).get('id') or request.args.get('id')

        if payment_id:
            pago = obtener_pago(payment_id)
            if pago:
                estado_mp        = pago.get('status', '')
                external_ref     = pago.get('external_reference')
                nuevo_estado     = MP_ESTADO.get(estado_mp, 'pendiente')

                if external_ref:
                    _actualizar_estado_pedido(int(external_ref), nuevo_estado, payment_id)
                    print(f"[WEBHOOK MP] pedido={external_ref} payment={payment_id} estado={nuevo_estado}")

    # Siempre 200 — aunque no procesemos el evento, no queremos que MP reintente
    return jsonify({'status': 'ok'}), 200


# ── Verificación manual de pago ───────────────────────────────

@pedidos_bp.route('/pedido/verificar/<int:pedido_id>')
def verificar_pago(pedido_id):
    """El usuario puede entrar aquí si el webhook no actualizó su pedido.

    Consulta el estado directamente en la API de MP y actualiza la BD.
    Útil cuando Render estaba dormido y el webhook no llegó.
    """
    pedido = _get_pedido(pedido_id)
    if not pedido:
        return redirect(url_for('pedidos.mis_pedidos'))

    if pedido.get('mp_payment_id'):
        pago = obtener_pago(pedido['mp_payment_id'])
        if pago:
            estado_mp    = pago.get('status', '')
            nuevo_estado = MP_ESTADO.get(estado_mp, 'pendiente')
            _actualizar_estado_pedido(pedido_id, nuevo_estado, pedido['mp_payment_id'])

    return redirect(url_for('pedidos.confirmacion_pedido', pedido_id=pedido_id))


# ── Confirmación de pedido ────────────────────────────────────

@pedidos_bp.route('/pedido/confirmacion/<int:pedido_id>')
def confirmacion_pedido(pedido_id):
    """Página final que muestra el estado del pedido."""
    pedido = _get_pedido(pedido_id)
    if not pedido:
        return redirect(url_for('public.catalogo'))

    return render_template(
        'confirmacion_pedido.html',
        pedido=pedido,
        mensaje_mp=request.args.get('mensaje'),
        usuario=usuario_actual()
    )


# ── Mis pedidos ───────────────────────────────────────────────

@pedidos_bp.route('/mis-pedidos')
def mis_pedidos():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pd.nombre_comprador, pd.telefono, pd.direccion, pd.ciudad, pd.estado_mx,
               pd.mp_payment_id, pd.mp_preference_id,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.usuario_id = %s
        ORDER BY pd.created_at DESC
    """, (usuario['id'],))
    rows = cur.fetchall()
    cur.close()

    ventas = OrderedDict()
    for p in rows:
        minuto_base = (p['created_at'].hour * 60 + p['created_at'].minute) // 10 if p['created_at'] else 0
        fecha_dia   = str(p['created_at'].date()) if p['created_at'] else 'nd'
        vkey        = f"{fecha_dia}|{minuto_base}"

        if vkey not in ventas:
            ventas[vkey] = {
                'id_principal':     p['id'],
                'estado_pedido':    p['estado_pedido'],
                'created_at':       p['created_at'],
                'nombre_comprador': p['nombre_comprador'],
                'telefono':         p['telefono'],
                'direccion':        p['direccion'],
                'ciudad':           p['ciudad'],
                'estado_mx':        p['estado_mx'],
                'mp_payment_id':    p['mp_payment_id'],
                'productos':        [],
                'total':            0.0,
            }
        ventas[vkey]['productos'].append({
            'nombre_producto': p['nombre_producto'],
            'imagen_url':      p['imagen_url'],
            'cantidad':        p['cantidad'],
            'total':           float(p['total']) if p['total'] else 0.0,
        })
        ventas[vkey]['total'] += float(p['total']) if p['total'] else 0.0

    return render_template('usuario/pedidos.html', ventas=list(ventas.values()), usuario=usuario)


# ── Helper interno ────────────────────────────────────────────

def _get_pedido(pedido_id):
    """Obtiene un pedido de la BD. Devuelve None si no existe."""
    if not pedido_id:
        return None
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pd.id, pd.nombre_comprador, pd.telefono, pd.direccion,
               pd.ciudad, pd.estado_mx, pd.cantidad, pd.total,
               pd.estado_pedido, pd.mp_payment_id, pd.mp_preference_id,
               pr.nombre AS nombre_producto, pr.imagen_url
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE pd.id = %s
    """, (pedido_id,))
    pedido = cur.fetchone()
    cur.close()
    return pedido