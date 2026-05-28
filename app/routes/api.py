from decimal import Decimal

from flask import Blueprint, jsonify, request, abort, current_app
from app import mysql

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/chat', methods=['POST'])
def chat():
    from openai import OpenAI

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Solicitud inválida'}), 400

    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'error': 'Mensaje vacío'}), 400

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
        "- Siempre necesitas saber al menos: superficie, uso (interior/exterior) y área aproximada.\n"
        "- Si el cliente menciona una superficie que no está en el catálogo, responde con sin_resultado de inmediato.\n"
        "- Solo recomienda productos del catálogo. Si ninguno encaja, usa sin_resultado.\n\n"

        "REGLAS PARA LAS OPCIONES DE RESPUESTA:\n"
        "- Cada opción debe tener máximo 4 palabras. Cortas y claras.\n"
        "- Usa entre 2 y 4 opciones por pregunta. Nunca más de 4.\n"
        "- Las opciones deben cubrir los casos reales más comunes del catálogo.\n"
        "- Para área siempre usa: ['Menos de 5 m²', '5 a 15 m²', '15 a 30 m²', 'Más de 30 m²']\n"
        "- Para uso siempre usa: ['Interior', 'Exterior', 'Ambos']\n"
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
        '"litros": 2.5, "complemento": "nombre o null", '
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


@api_bp.route('/api/productos/<int:producto_id>/detalle', methods=['GET'])
def detalle_producto_completo(producto_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT id, clave, nombre, descripcion_ia, imagen_url, precio_referencia, "
        "acabado, uso, rendimiento_min, link_compra_ml, activo, created_at, updated_at, "
        "sup_madera, sup_metal, sup_concreto, sup_otro "
        "FROM productos WHERE id = %s",
        (producto_id,)
    )
    producto = cur.fetchone()

    if not producto:
        cur.close()
        abort(404, description='Producto no encontrado')

    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, c.tipo, c.proporcion "
        "FROM complementos c "
        "JOIN productos p ON c.complemento_id = p.id "
        "WHERE c.producto_id = %s",
        (producto_id,)
    )
    complementos = cur.fetchall()
    cur.close()

    return jsonify({
        'id': producto['id'],
        'clave': producto['clave'],
        'nombre': producto['nombre'],
        'descripcion': producto.get('descripcion_ia'),
        'imagen_url': producto.get('imagen_url'),
        'precio_referencia': float(producto['precio_referencia']) if isinstance(producto.get('precio_referencia'), Decimal) else producto.get('precio_referencia'),
        'acabado': producto.get('acabado'),
        'uso': producto.get('uso'),
        'rendimiento_min': float(producto['rendimiento_min']) if isinstance(producto.get('rendimiento_min'), Decimal) else producto.get('rendimiento_min'),
        'link_compra_ml': producto.get('link_compra_ml'),
        'activo': bool(producto.get('activo')),
        'superficies': {
            'madera': bool(producto.get('sup_madera')),
            'metal': bool(producto.get('sup_metal')),
            'concreto': bool(producto.get('sup_concreto')),
            'otro': bool(producto.get('sup_otro')),
        },
        'complementos': [
            {
                'id': c['id'],
                'nombre': c['nombre'],
                'imagen_url': c.get('imagen_url'),
                'tipo': c.get('tipo'),
                'proporcion': c.get('proporcion'),
            }
            for c in complementos
        ],
        'created_at': producto['created_at'].isoformat() if producto.get('created_at') else None,
        'updated_at': producto['updated_at'].isoformat() if producto.get('updated_at') else None,
    }), 200


@api_bp.route('/api/productos', methods=['POST'])
def crear_producto():
    data = request.get_json() or {}
    nombre = data.get('nombre')
    clave = data.get('clave')
    descripcion = data.get('descripcion')
    imagen_url = data.get('imagen_url')
    precio_referencia = data.get('precio_referencia')
    acabado = data.get('acabado')
    uso = data.get('uso')
    activo = 1 if data.get('activo', True) else 0

    if not nombre or not clave:
        return jsonify({'error': 'Los campos nombre y clave son obligatorios.'}), 400

    cur = mysql.connection.cursor()
    cur.execute(
        "INSERT INTO productos (clave, nombre, descripcion_ia, imagen_url, precio_referencia, acabado, uso, activo) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (clave, nombre, descripcion, imagen_url, precio_referencia, acabado, uso, activo)
    )
    mysql.connection.commit()
    producto_id = cur.lastrowid
    cur.close()

    response, status = detalle_producto(producto_id)
    return response, 201


@api_bp.route('/api/productos/<int:producto_id>', methods=['PUT'])
def editar_producto(producto_id):
    data = request.get_json() or {}
    campo_update = []
    valores = []
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

    for campo, columna in campo_map.items():
        if campo in data:
            valor = data[campo]
            if campo == 'activo':
                valor = 1 if valor else 0
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

    return detalle_producto(producto_id)


@api_bp.route('/api/productos/<int:producto_id>', methods=['DELETE'])
def eliminar_producto(producto_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM complementos WHERE producto_id = %s OR complemento_id = %s", (producto_id, producto_id))
    cur.execute("DELETE FROM productos WHERE id = %s", (producto_id,))
    deleted = cur.rowcount
    mysql.connection.commit()
    cur.close()

    if deleted == 0:
        abort(404, description='Producto no encontrado')

    return jsonify({'message': 'Producto eliminado.'}), 200