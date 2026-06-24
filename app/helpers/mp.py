# ─────────────────────────────────────────────────────────────
# helpers/mp.py
#
# Utilidades de Mercado Pago para SayerBarn.
# Centraliza la creación de preferencias y la verificación
# de pagos para que pedidos.py y el webhook no dupliquen lógica.
# ─────────────────────────────────────────────────────────────

import mercadopago
from flask import current_app


def get_sdk():
    """Devuelve una instancia del SDK con el Access Token configurado."""
    return mercadopago.SDK(current_app.config['MP_ACCESS_TOKEN'])


def crear_preferencia(pedido_id, items, datos_comprador, urls):
    """Crea una preferencia de pago en Mercado Pago (Checkout Pro).

    Args:
        pedido_id:       ID del pedido principal en nuestra BD (para rastreo).
        items:           Lista de dicts con {title, quantity, unit_price}.
        datos_comprador: Dict con {nombre, email} del comprador.
        urls:            Dict con {success, failure, pending} — URLs de retorno.

    Returns:
        (preference_id, init_point) si todo salió bien.
        (None, None) si hubo un error.
    """
    sdk = get_sdk()

    preference_data = {
        # Productos del pedido
        'items': [
            {
                'id':          str(item.get('producto_id', '')),
                'title':       item['title'],
                'quantity':    int(item['quantity']),
                'unit_price':  float(item['unit_price']),
                'currency_id': 'MXN',
            }
            for item in items
        ],

        # Datos del comprador (pre-rellena el formulario de MP)
        'payer': {
            'name':  datos_comprador.get('nombre', ''),
            'email':'TESTUSER8740454914502184808',  # ← email del usuario COMPRADOR de prueba
        },

        # URLs de retorno después del pago
        'back_urls': {
            'success': urls['success'],
            'failure': urls['failure'],
            'pending': urls['pending'],
        },
        'auto_return': 'approved',  # Redirige automático solo si fue aprobado

        # Referencia interna para cruzar con nuestra BD en el webhook
        'external_reference': str(pedido_id),

        # Webhook — MP notifica aquí cuando cambia el estado del pago
        'notification_url': urls.get('webhook'),

        # Vencimiento de la preferencia: 24 horas
        'expires':    True,
        'expiration_date_to': _fecha_expiracion_iso(horas=24),

        # Metadata útil para el panel de MP
        'statement_descriptor': 'SAYERBARN',
    }

    result = sdk.preference().create(preference_data)

    if result['status'] == 201:
        body = result['response']
        return body['id'], body['init_point']

    # Log del error para diagnóstico
    print(f"[MP ERROR] crear_preferencia: status={result['status']} body={result.get('response')}")
    return None, None


def obtener_pago(payment_id):
    """Consulta el estado de un pago directamente en la API de MP.

    Útil para verificar pagos cuando el webhook no llegó (app dormida en Render).

    Returns:
        Dict con los datos del pago, o None si no se encontró.
    """
    sdk = get_sdk()
    result = sdk.payment().get(payment_id)

    if result['status'] == 200:
        return result['response']

    print(f"[MP ERROR] obtener_pago {payment_id}: status={result['status']}")
    return None


def _fecha_expiracion_iso(horas=24):
    """Genera una fecha ISO 8601 con offset UTC para la expiración de preferencia."""
    from datetime import datetime, timezone, timedelta
    expira = datetime.now(timezone.utc) + timedelta(hours=horas)
    return expira.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')