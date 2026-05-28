from decimal import Decimal

from flask import Blueprint, jsonify, request, abort, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
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
        "Eres un asesor experto en barnices y productos para madera de Sayer Dabet, "
        "una marca líder en México especializada en barnices, pinturas y recubrimientos "
        "para madera, metal y concreto.\n\n"

        "Tu misión es ayudar al cliente a elegir el producto correcto. "
        "Sigue estas reglas:\n"
        "- Responde siempre en español, de forma amigable, clara y concisa.\n"
        "- Haz UNA sola pregunta a la vez. Nunca hagas varias preguntas en el mismo mensaje.\n"
        "- Si el cliente no ha mencionado la superficie (madera, metal, concreto), pregunta eso primero.\n"
        "- Luego pregunta si es para interior o exterior.\n"
        "- Luego pregunta el área aproximada en metros cuadrados.\n"
        "- Con esos tres datos, recomienda un producto del catálogo.\n"
        "- Cuando recomiendes un producto, calcula los litros necesados: "
        "divide el área entre el rendimiento promedio y redondea hacia arriba. "
        "Sugiere siempre comprar un 10-15% extra por repasos.\n"
        "- Si el producto requiere un complemento (diluyente o catalizador), menciónalo.\n"
        "- Mantén respuestas cortas: máximo 3 párrafos.\n"
        "- IMPORTANTE: Si el cliente menciona una superficie que no está en el catálogo, "
        "informa de inmediato que no tienes productos para esa superficie y sugiere "
        "acercarse a una sucursal. No sigas haciendo preguntas innecesarias.\n"
        "- Solo recomienda productos del catálogo actual. "
        "Si ningún producto encaja, dile al cliente que se acerque a una sucursal.\n"
        "- Si el cliente pregunta algo fuera del tema de barnices, redirige amablemente.\n\n"

        f"CATÁLOGO ACTUAL DE PRODUCTOS:\n\n{catalogo_texto}"
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
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        return jsonify({'response': reply})
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


@api_bp.route('/api/asesorias', methods=['GET'])
@jwt_required()
def listar_asesorias():
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
        'area_m2': float(a['area_m2']) if isinstance(a.get('area_m2'), Decimal) else a.get('area_m2'),
        'litros_estimados': float(a['litros_estimados']) if isinstance(a.get('litros_estimados'), Decimal) else a.get('litros_estimados'),
        'created_at': a['created_at'].isoformat() if a.get('created_at') else None,
        'producto_nombre': a.get('producto_nombre'),
        'imagen_url': a.get('imagen_url'),
    } for a in asesorias]), 200


@api_bp.route('/api/favoritos', methods=['GET'])
@jwt_required()
def listar_favoritos_api():
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


@api_bp.route('/api/favoritos/<int:producto_id>', methods=['DELETE'])
@jwt_required()
def eliminar_favorito_api(producto_id):
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
        (user_id, producto_id)
    )
    mysql.connection.commit()
    cur.close()
    return jsonify({'ok': True}), 200


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
