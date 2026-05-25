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

    system_prompt = (
        "Eres un asesor experto en barnices y productos para madera de Sayer Dabet, "
        "una marca líder en México especializada en barnices, pinturas y recubrimientos "
        "para madera, metal y concreto (líneas Sayerlack, Sayer Dabet y complementarias).\n\n"
        "Tu misión es ayudar al cliente a elegir el producto correcto para su proyecto. "
        "Sigue estas reglas:\n"
        "- Responde siempre en español, de forma amigable, clara y concisa.\n"
        "- Si el cliente no ha mencionado la superficie (madera, metal, concreto), "
        "el ambiente (interior/exterior) o el área aproximada, pregunta por esos datos "
        "antes de recomendar.\n"
        "- Cuando tengas suficiente información, recomienda un producto específico de "
        "Sayer Dabet y explica brevemente por qué es el adecuado.\n"
        "- Mantén respuestas cortas: máximo 3-4 párrafos.\n"
        "- Si el cliente hace preguntas fuera del tema de barnices y recubrimientos, "
        "redirige amablemente la conversación."
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
