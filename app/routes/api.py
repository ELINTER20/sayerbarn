from decimal import Decimal
from functools import wraps

from flask import Blueprint, jsonify, request, abort, current_app
from flask_jwt_extended import jwt_required, verify_jwt_in_request, get_jwt_identity
from app import mysql

# Blueprint de la API REST: todas sus rutas empiezan con /api/
api_bp = Blueprint('api', __name__)


def api_admin_required(f):
    """Decorador para endpoints de API que solo permiten acceso a admins. Devuelve JSON."""
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
                return jsonify({'error': 'Acceso no autorizado'}), 403
        except Exception:
            return jsonify({'error': 'Autenticación requerida'}), 401
        return f(*args, **kwargs)
    return decorated


@api_bp.route('/api/chat', methods=['POST'])
def chat():
    """Endpoint del asistente de asesoría con IA (GPT-4o-mini).
    Recibe el mensaje del usuario y el historial de la conversación,
    consulta el catálogo en la BD y devuelve una respuesta en JSON."""
    from openai import OpenAI

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Solicitud inválida'}), 400

    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'error': 'Mensaje vacío'}), 400

    # Filtra el historial para aceptar solo mensajes válidos de user/assistant
    raw_history = data.get('history') or []
    safe_history = [
        {'role': msg['role'], 'content': msg['content']}
        for msg in raw_history
        if isinstance(msg, dict)
        and msg.get('role') in ('user', 'assistant')
        and isinstance(msg.get('content'), str)
    ]

    # ── Leer productos activos de la BD ──────────────────────────────
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT p.nombre, p.clave, p.descripcion_ia,
                   p.uso, p.acabado,
                   p.sup_madera, p.sup_metal, p.sup_concreto,
                   p.rendimiento_min, p.rendimiento_max,
                   p.precio_referencia,
                   GROUP_CONCAT(
                       CONCAT(c2.nombre, ' (', co.tipo, ', ', COALESCE(co.proporcion,''), ')')
                       SEPARATOR ' | '
                   ) AS complementos
            FROM productos p
            LEFT JOIN complementos co ON co.producto_id = p.id
            LEFT JOIN productos c2   ON c2.id = co.complemento_id
            WHERE p.activo = 1
              AND p.categoria_id != (
                  SELECT id FROM categorias WHERE nombre = 'Diluyentes y complementos' LIMIT 1
              )
            GROUP BY p.id
            ORDER BY p.id
        """)
        productos_bd = cur.fetchall()
        cur.close()
    except Exception as e:
        print(f"[ERROR CHAT - BD] {e}")
        productos_bd = []

    # ── Construir bloque de catálogo para el prompt ───────────────────
    if productos_bd:
        lineas_catalogo = []
        for i, p in enumerate(productos_bd, 1):
            superficies = []
            if p.get('sup_madera'): superficies.append('madera')
            if p.get('sup_metal'):  superficies.append('metal')
            if p.get('sup_concreto'): superficies.append('concreto')

            rend_min = p.get('rendimiento_min')
            rend_max = p.get('rendimiento_max')
            rendimiento = (
                f"{float(rend_min):.0f} a {float(rend_max):.0f} m² por litro"
                if rend_min and rend_max else "consultar ficha técnica"
            )

            precio = p.get('precio_referencia')
            precio_str = f"${float(precio):.0f} MXN" if precio else "consultar precio"

            complementos_str = p.get('complementos') or 'ninguno'

            bloque = (
                f"{i}. {p['nombre']} (clave: {p['clave']})\n"
                f"   - Superficie: {', '.join(superficies) if superficies else 'ver descripción'}\n"
                f"   - Uso: {p.get('uso') or 'ambos'}\n"
                f"   - Acabado: {p.get('acabado') or 'sin acabado definido'}\n"
                f"   - Rendimiento: {rendimiento}\n"
                f"   - Complementos requeridos: {complementos_str}\n"
                f"   - Precio referencia: {precio_str}\n"
                f"   - Descripción: {p.get('descripcion_ia') or 'sin descripción'}"
            )
            lineas_catalogo.append(bloque)

        catalogo_texto = "\n\n".join(lineas_catalogo)
    else:
        catalogo_texto = "No hay productos disponibles en este momento."

    # ── Superficies disponibles en el catálogo ────────────────────────
    todas_superficies = set()
    for p in productos_bd:
        if p.get('sup_madera'):   todas_superficies.add('madera')
        if p.get('sup_metal'):    todas_superficies.add('metal')
        if p.get('sup_concreto'): todas_superficies.add('concreto')

    superficies_disponibles = ', '.join(todas_superficies) if todas_superficies else 'madera'

    catalogo_texto += (
        f"\n\nSUPERFICIES QUE CUBRE EL CATÁLOGO ACTUAL: {superficies_disponibles}. "
        "Si el cliente menciona una superficie que no está en esta lista, "
        "informa de inmediato que no tienes productos para esa superficie "
        "y sugiere acercarse a una sucursal sin hacer más preguntas."
    )

    # ── System prompt dinámico ────────────────────────────────────────
    system_prompt = (
        "Eres un asesor experto de Sayer Dabet, empresa mexicana de barnices y recubrimientos. "
        "Tu trabajo es guiar al cliente para encontrar el producto correcto, "
        "igual que lo haría un vendedor experto en tienda.\n\n"

        "CÓMO DEBES COMPORTARTE:\n"
        "- Conduce la conversación tú mismo desde el inicio. No esperes que el cliente sepa qué decir.\n"
        "- Haz UNA sola pregunta a la vez y espera la respuesta antes de continuar.\n"
        "- Decide qué preguntar según lo que el cliente ya respondió. No sigas un orden fijo.\n"
        "- Con 3 o 4 respuestas normalmente ya tienes suficiente para recomendar. No hagas más preguntas de las necesarias.\n"
        "- Si la primera respuesta ya te da suficiente contexto, recomienda directamente.\n"
        "- Siempre necesitas saber al menos: superficie, uso (interior/exterior), clima de la zona y área aproximada.\n"
        "- Pregunta SIEMPRE por el clima/ambiente, sin importar si el uso es interior o exterior. "
        "No la omitas ni la saltes para ir directo a área: en interiores también aplica "
        "(ej. humedad de baño, calor de cocina), aunque las opciones sean distintas a las de exterior.\n"
        "- Si el cliente menciona una superficie que no está en el catálogo, responde con sin_resultado de inmediato.\n"
        "- Solo recomienda productos del catálogo. Si ninguno encaja, usa sin_resultado.\n\n"

        "REGLAS PARA LAS OPCIONES DE RESPUESTA:\n"
        "- Cada opción debe tener máximo 4 palabras. Cortas y claras.\n"
        "- Usa entre 2 y 4 opciones por pregunta. Nunca más de 4, excepto en la pregunta de clima.\n"
        "- Las opciones deben cubrir los casos reales más comunes del catálogo.\n"
        "- Para área siempre usa: ['Menos de 5 m²', '5 a 15 m²', '15 a 30 m²', 'Más de 30 m²']\n"
        "- Para uso siempre usa: ['Interior', 'Exterior', 'Ambos']\n"
        "- Para clima usa (hasta 6 opciones permitidas aquí, elige solo las que apliquen según el uso): "
        "['Alta humedad', 'Exposición al sol', 'Exposición a lluvia', 'Clima templado', "
        "'Fachada exterior', 'Zona costera (salitre)']. "
        "Si el uso es interior, usa solo las que tengan sentido en interior "
        "(ej. 'Alta humedad', 'Exposición al sol', 'Clima templado') y omite las exclusivas "
        "de exterior ('Fachada exterior', 'Zona costera (salitre)', 'Exposición a lluvia').\n"
        "- Para zona de exposición usa (elige solo las que apliquen según el uso): "
        "si el uso es interior: ['Humedad', 'Directo al agua', 'Indirectamente al agua']; "
        "si el uso es exterior: ['Sol', 'Salinidad húmeda']\n"
        "- Para acabado usa: ['Brillante', 'Semi mate', 'Mate', 'Sin preferencia']\n"
        "- Para superficie usa: ['Madera', 'Metal', 'Concreto', 'Otro']\n"
        "- Para preguntas de sí/no usa siempre: ['Sí', 'No', 'No estoy seguro']\n\n"

        "CÁLCULO DE LITROS:\n"
        "- Divide el área entre el rendimiento promedio del producto y redondea hacia arriba.\n"
        "- Si el área fue una opción de rango, usa el valor medio del rango (ej: '5 a 15 m²' = 10 m²).\n"
        "- Suma siempre un 15% extra por repasos.\n"
        "- Si el producto requiere diluyente o catalizador, indícalo en el campo complemento.\n\n"

        "FORMATO DE RESPUESTA — CRÍTICO:\n"
        "Responde SIEMPRE con un JSON válido. Sin texto antes ni después. Sin markdown.\n\n"

        "Pregunta al usuario:\n"
        '{"tipo": "pregunta", "texto": "¿pregunta aquí?", "opciones": ["Op 1", "Op 2", "Op 3"]}\n\n'

        "Cuando tengas suficiente información para recomendar:\n"
        '{"tipo": "recomendacion", "producto": "nombre", "clave": "clave", '
        '"litros": 2.5, "complemento": "nombre o null", "precio": 999.00, '
        '"mensaje": "por qué este producto en máximo 2 oraciones"}\n\n'

        "Cuando no hay producto disponible o la superficie no está en catálogo:\n"
        '{"tipo": "sin_resultado", "mensaje": "explicación breve y qué debe hacer el cliente"}\n\n'

        f"CATÁLOGO ACTUAL:\n\n{catalogo_texto}"
    )

    messages = (
        [{'role': 'system', 'content': system_prompt}]
        + safe_history
        + [{'role': 'user', 'content': user_message}]
    )

    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'error': 'La API key de OpenAI no está configurada.'}), 500

    try:
        import json as json_lib
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=messages,
            max_tokens=500,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content

        # Intentar parsear el JSON que regresa la IA
        try:
            parsed = json_lib.loads(raw)
        except Exception:
            # Si falla el parse, regresar como pregunta genérica para no romper el flujo
            print(f"[WARN CHAT] La IA no regresó JSON válido: {raw[:200]}")
            parsed = {
                "tipo": "pregunta",
                "texto": raw,
                "opciones": []
            }

        return jsonify(parsed)
    except Exception as e:
        print(f"[ERROR CHAT] {type(e).__name__}: {e}")
        return jsonify({'error': 'Error al contactar al asistente. Intenta de nuevo.'}), 500

def _serialize_product(product):
    """Convierte una fila de producto de la BD a un dict serializable como JSON.
    Convierte Decimal a float para que JSON no falle al serializar."""
    return {
        'id': product['id'],
        'clave': product['clave'],
        'nombre': product['nombre'],
        'descripcion': product.get('descripcion_ia'),
        'imagen_url': product.get('imagen_url'),
        'precio_referencia': float(product['precio_referencia']) if isinstance(product.get('precio_referencia'), Decimal) else product.get('precio_referencia'),
        'acabado': product.get('acabado'),
        'uso': product.get('uso'),
        'activo': bool(product.get('activo')),
        'created_at': product.get('created_at').isoformat() if product.get('created_at') else None,
        'updated_at': product.get('updated_at').isoformat() if product.get('updated_at') else None,
    }


@api_bp.route('/api/productos', methods=['GET'])
def listar_productos():
    # Devuelve todos los productos activos en formato JSON
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, clave, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso, activo, created_at, updated_at "
        "FROM productos WHERE activo = 1 ORDER BY id"
    )
    productos = cur.fetchall()
    cur.close()

    return jsonify([_serialize_product(p) for p in productos]), 200


@api_bp.route('/api/productos/<int:producto_id>', methods=['GET'])
def detalle_producto(producto_id):
    # Devuelve los datos básicos de un producto específico por su ID
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, clave, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso, activo, created_at, updated_at "
        "FROM productos WHERE id = %s",
        (producto_id,)
    )
    producto = cur.fetchone()
    cur.close()

    if not producto:
        abort(404, description='Producto no encontrado')

    return jsonify(_serialize_product(producto)), 200


@api_bp.route('/api/productos', methods=['POST'])
@api_admin_required
def crear_producto():
    # Crea un nuevo producto en la BD con los datos enviados en JSON
    data = request.get_json() or {}
    nombre = data.get('nombre')
    clave = data.get('clave')
    descripcion = data.get('descripcion')
    imagen_url = data.get('imagen_url')
    precio_referencia = data.get('precio_referencia')
    acabado = data.get('acabado')
    uso = data.get('uso')
    activo = 1 if data.get('activo', True) else 0

    # nombre y clave son los únicos campos obligatorios
    if not nombre or not clave:
        return jsonify({'error': 'Los campos nombre y clave son obligatorios.'}), 400

    cur = mysql.connection.cursor()
    cur.execute(
        "INSERT INTO productos (clave, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso, activo) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (clave, nombre, descripcion, imagen_url, precio_referencia, acabado, uso, activo)
    )
    mysql.connection.commit()
    producto_id = cur.lastrowid  # ID del producto recién insertado
    cur.close()

    # Reutiliza detalle_producto para devolver el objeto completo con código 201
    response, status = detalle_producto(producto_id)
    return response, 201


@api_bp.route('/api/productos/<int:producto_id>', methods=['PUT'])
@api_admin_required
def editar_producto(producto_id):
    # Actualiza solo los campos enviados en el JSON (actualización parcial)
    data = request.get_json() or {}
    campo_update = []
    valores = []
    # Mapeo de nombre del campo en JSON → nombre de columna en la BD
    campo_map = {
        'clave': 'clave',
        'nombre': 'nombre',
        'descripcion': 'descripcion_ia',
        'imagen_url': 'imagen_url',
        'precio_referencia': 'precio_referencia',
        'acabado': 'acabado',
        'uso': 'uso',
        'activo': 'activo',
    }

    # Construye dinámicamente el SET de la query con solo los campos recibidos
    for campo, columna in campo_map.items():
        if campo in data:
            valor = data[campo]
            if campo == 'activo':
                valor = 1 if valor else 0  # Normaliza booleano a 1/0 para MySQL
            campo_update.append(f"{columna} = %s")
            valores.append(valor)

    if not campo_update:
        return jsonify({'error': 'No se envió ningún campo válido para actualizar.'}), 400

    valores.append(producto_id)
    cur = mysql.connection.cursor()
    cur.execute(
        f"UPDATE productos SET {', '.join(campo_update)} WHERE id = %s",
        tuple(valores)
    )
    mysql.connection.commit()
    cur.close()

    # Devuelve el producto actualizado
    return detalle_producto(producto_id)


@api_bp.route('/api/asesorias', methods=['GET'])
@jwt_required()
def listar_asesorias():
    # Devuelve el historial de asesorías del usuario autenticado
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT a.id, a.superficie, a.uso, a.area_m2, a.litros_estimados, "
        "a.created_at, p.nombre AS producto_nombre, p.imagen_url "
        "FROM asesorias a "
        "LEFT JOIN productos p ON a.producto_recomendado_id = p.id "
        "WHERE a.usuario_id = %s ORDER BY a.created_at DESC",
        (user_id,)
    )
    asesorias = cur.fetchall()
    cur.close()
    return jsonify([{
        'id': a['id'],
        'superficie': a.get('superficie'),
        'uso': a.get('uso'),
        # Convierte Decimal a float para JSON
        'area_m2': float(a['area_m2']) if isinstance(a.get('area_m2'), Decimal) else a.get('area_m2'),
        'litros_estimados': float(a['litros_estimados']) if isinstance(a.get('litros_estimados'), Decimal) else a.get('litros_estimados'),
        'created_at': a['created_at'].isoformat() if a.get('created_at') else None,
        'producto_nombre': a.get('producto_nombre'),
        'imagen_url': a.get('imagen_url'),
    } for a in asesorias]), 200


@api_bp.route('/api/favoritos', methods=['GET'])
@jwt_required()
def listar_favoritos_api():
    # Devuelve la lista de favoritos del usuario autenticado en formato JSON
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.descripcion_ia, p.acabado, p.uso, "
        "p.rendimiento_min, p.rendimiento_max, p.link_compra_ml "
        "FROM favoritos f "
        "JOIN productos p ON f.producto_id = p.id "
        "WHERE f.usuario_id = %s ORDER BY f.created_at DESC",
        (user_id,)
    )
    productos = cur.fetchall()
    cur.close()
    return jsonify([{
        'id': p['id'],
        'nombre': p['nombre'],
        'imagen_url': p.get('imagen_url'),
        'descripcion': p.get('descripcion_ia'),
        'acabado': p.get('acabado'),
        'uso': p.get('uso'),
        'rendimiento_min': float(p['rendimiento_min']) if isinstance(p.get('rendimiento_min'), Decimal) else p.get('rendimiento_min'),
        'rendimiento_max': float(p['rendimiento_max']) if isinstance(p.get('rendimiento_max'), Decimal) else p.get('rendimiento_max'),
        'link_compra_ml': p.get('link_compra_ml'),
    } for p in productos]), 200


@api_bp.route('/api/favoritos/<int:producto_id>', methods=['POST'])
@jwt_required()
def agregar_favorito_api(producto_id):
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "INSERT IGNORE INTO favoritos (usuario_id, producto_id) VALUES (%s, %s)",
        (user_id, producto_id)
    )
    mysql.connection.commit()
    cur.close()
    return jsonify({'ok': True}), 200


@api_bp.route('/api/favoritos/<int:producto_id>', methods=['DELETE'])
@jwt_required()
def eliminar_favorito_api(producto_id):
    user_id = get_jwt_identity()
    cur = None
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
            (user_id, producto_id)
        )
        mysql.connection.commit()
    except Exception as e:
        print(f"[ERROR eliminar_favorito] {type(e).__name__}: {e}")
        return jsonify({'error': 'Error al eliminar favorito'}), 500
    finally:
        if cur:
            cur.close()
    return jsonify({'ok': True}), 200


@api_bp.route('/api/productos/<int:producto_id>', methods=['DELETE'])
@api_admin_required
def eliminar_producto(producto_id):
    # Elimina físicamente el producto y todos sus complementos asociados de la BD
    cur = mysql.connection.cursor()
    # Primero borra los complementos para no violar la restricción de clave foránea
    cur.execute("DELETE FROM complementos WHERE producto_id = %s OR complemento_id = %s", (producto_id, producto_id))
    cur.execute("DELETE FROM productos WHERE id = %s", (producto_id,))
    deleted = cur.rowcount  # 0 si el producto no existía
    mysql.connection.commit()
    cur.close()

    if deleted == 0:
        abort(404, description='Producto no encontrado')

    return jsonify({'message': 'Producto eliminado.'}), 200


@api_bp.route('/api/tiendas')
def listar_tiendas():
    from app.tiendas import TIENDAS
    return jsonify(TIENDAS), 200


@api_bp.route('/api/guardar-asesoria', methods=['POST'])
def guardar_asesoria():
    """Guarda el resultado de una asesoría en la BD.
    Funciona tanto para usuarios logueados como para visitantes anónimos."""
    from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
    from app.helpers.auth_utils import usuario_actual

    data = request.get_json(silent=True) or {}
    clave       = (data.get('clave') or '').strip()
    superficie  = (data.get('superficie') or '').strip()
    uso         = (data.get('uso') or '').strip()
    area_m2     = data.get('area_m2')
    litros      = data.get('litros')

    if not clave:
        return jsonify({'error': 'Clave de producto requerida'}), 400

    # Buscar el producto real en la BD por clave
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, nombre, descripcion_ia, imagen_url, rendimiento_min, "
        "link_compra_ml, acabado, uso "
        "FROM productos WHERE clave = %s AND activo = 1 LIMIT 1",
        (clave,)
    )
    producto = cur.fetchone()

    # Si no encontró por clave, intentar por nombre (por si la IA devolvió el nombre)
    if not producto:
        nombre_ia = (data.get('producto') or '').strip()
        if nombre_ia:
            cur.execute(
                "SELECT id, nombre, descripcion_ia, imagen_url, rendimiento_min, "
                "link_compra_ml, acabado, uso "
                "FROM productos WHERE nombre LIKE %s AND activo = 1 LIMIT 1",
                (f"%{nombre_ia}%",)
            )
            producto = cur.fetchone()

    if not producto:
        cur.close()
        return jsonify({'error': 'Producto no encontrado en catálogo'}), 404

    # Si no vienen litros del frontend, los calcula: (área / rendimiento) + 15% de repaso
    if not litros and area_m2 and producto.get('rendimiento_min'):
        try:
            litros = round(float(area_m2) / float(producto['rendimiento_min']) * 1.15, 2)
        except Exception:
            litros = None

    # Obtener usuario actual (puede ser None si no está logueado)
    usuario = usuario_actual()
    user_id = usuario['id'] if usuario else None

    # Guarda la asesoría; user_id puede ser NULL para usuarios anónimos
    cur.execute(
        "INSERT INTO asesorias (usuario_id, superficie, uso, area_m2, litros_estimados, producto_recomendado_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, superficie or None, uso or None, area_m2 or None, litros, producto['id'])
    )
    mysql.connection.commit()
    asesoria_id = cur.lastrowid  # ID de la asesoría recién creada
    cur.close()

    return jsonify({'asesoria_id': asesoria_id}), 201