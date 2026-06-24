# helpers/ml.py
# Utilidades de Mercado Libre para SayerBarn.
# Gestiona la publicación de productos al marketplace desde el panel admin.

import requests
from flask import current_app

# URL base de la API de ML para México
ML_API_BASE = 'https://api.mercadolibre.com'

# Mapeo de categoría_id interna → category_id de Mercado Libre México
# MLM: México. Estas son las categorías más cercanas para pinturas/recubrimientos.
# Si un producto no tiene mapeo exacto, cae en PINTURAS_Y_RECUBRIMIENTOS (general).
ML_CATEGORIAS = {
    # categoria_id de SayerBarn : category_id de ML México
    1:  'MLM1500',   # Pinturas y recubrimientos (general)
    2:  'MLM1500',   # Barnices → misma rama
    3:  'MLM1500',   # Selladores → misma rama
    4:  'MLM1500',   # Fondos/Primers → misma rama
    5:  'MLM1500',   # Diluyentes → misma rama
    6:  'MLM1500',   # Catalizadores → misma rama
}
ML_CATEGORIA_DEFAULT = 'MLM1500'  # Pinturas, Barnices y Selladores


def _headers():
    """Encabezados de autenticación para la API de ML."""
    token = current_app.config.get('ML_ACCESS_TOKEN')
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }


def publicar_producto(producto):
    """Publica un producto en Mercado Libre México.

    Args:
        producto: dict con los campos del producto desde la BD.
                  Debe tener al menos: nombre, precio_referencia, imagen_url.

    Returns:
        (ml_item_id, ml_url, error_msg)
        - Si éxito:  (str, str, None)    → ej. ('MLM123456789', 'https://...', None)
        - Si falla:  (None, None, str)   → el str describe el error
    """
    precio = producto.get('precio_referencia')
    if not precio or float(precio) <= 0:
        return None, None, 'El producto no tiene precio definido.'

    imagen_url = producto.get('imagen_url', '').strip()
    if not imagen_url:
        return None, None, 'El producto no tiene imagen. ML requiere al menos una imagen.'

    # Descripción: usar descripcion_ia si existe, si no armar una básica
    descripcion = (producto.get('descripcion_ia') or '').strip()
    if not descripcion:
        partes = [producto['nombre']]
        if producto.get('uso'):
            partes.append(f"Uso: {producto['uso']}")
        if producto.get('acabado') and producto['acabado'] != 'ninguno':
            partes.append(f"Acabado: {producto['acabado']}")
        descripcion = '. '.join(partes) + '. Producto Sayer Dabet.'

    # Condición: nuevo si condicion_nueva=1, usado si no
    condicion = 'new' if producto.get('condicion_nueva', 1) else 'used'

    # Categoría ML según categoria_id interno
    categoria_ml = ML_CATEGORIAS.get(
        producto.get('categoria_id'), ML_CATEGORIA_DEFAULT
    )

    # Construir el payload para la API de ML
    payload = {
        'title':        producto['nombre'],
        'category_id':  categoria_ml,
        'price':        float(precio),
        'currency_id':  'MXN',
        'available_quantity': max(1, int(producto.get('stock') or 1)),
        'buying_mode':  'buy_it_now',
        'condition':    condicion,
        'listing_type_id': 'gold_special',  # Publicación gratuita estándar
        'description':  {'plain_text': descripcion},
        'pictures':     [{'source': imagen_url}],
        'attributes': _construir_atributos(producto),
    }

    try:
        resp = requests.post(
            f'{ML_API_BASE}/items',
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()

        if resp.status_code == 201:
            ml_item_id = data.get('id')
            ml_url     = data.get('permalink')
            print(f'[ML] Producto publicado: {ml_item_id} → {ml_url}')
            return ml_item_id, ml_url, None

        # Error de ML — extraer mensaje legible
        error_msg = _parsear_error(data)
        print(f'[ML ERROR] publicar_producto: status={resp.status_code} → {error_msg}')
        return None, None, error_msg

    except requests.Timeout:
        return None, None, 'La API de Mercado Libre tardó demasiado. Intenta de nuevo.'
    except Exception as e:
        return None, None, f'Error inesperado al contactar Mercado Libre: {e}'


def pausar_publicacion(ml_item_id):
    """Pausa una publicación activa en ML (la oculta del marketplace)."""
    try:
        resp = requests.put(
            f'{ML_API_BASE}/items/{ml_item_id}',
            json={'status': 'paused'},
            headers=_headers(),
            timeout=10,
        )
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, {'error': str(e)}


def reactivar_publicacion(ml_item_id):
    """Reactiva una publicación pausada en ML."""
    try:
        resp = requests.put(
            f'{ML_API_BASE}/items/{ml_item_id}',
            json={'status': 'active'},
            headers=_headers(),
            timeout=10,
        )
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, {'error': str(e)}


def _construir_atributos(producto):
    """Genera la lista de atributos ML a partir de los campos del producto.

    ML México acepta atributos estándar para la categoría MLM1500.
    Solo mandamos los que tenemos datos reales.
    """
    atributos = [
        {'id': 'BRAND', 'value_name': 'Sayer'},
    ]

    if producto.get('rendimiento_min'):
        atributos.append({
            'id': 'COVERAGE',
            'value_name': f"{producto['rendimiento_min']} m²/L",
        })

    # Superficies compatibles como texto
    sups = []
    if producto.get('sup_madera'): sups.append('Madera')
    if producto.get('sup_metal'):  sups.append('Metal')
    if producto.get('sup_concreto'): sups.append('Concreto')
    if producto.get('sup_otro'):   sups.append('Otras superficies')
    if sups:
        atributos.append({
            'id': 'COMPATIBLE_SURFACES',
            'value_name': ', '.join(sups),
        })

    return atributos


def _parsear_error(data):
    """Extrae un mensaje de error legible de la respuesta de ML."""
    if 'cause' in data and data['cause']:
        causas = [c.get('description', '') for c in data['cause'] if c.get('description')]
        if causas:
            return ' | '.join(causas)
    return data.get('message') or data.get('error') or 'Error desconocido de Mercado Libre.'