from decimal import Decimal

from flask import Blueprint, jsonify, request, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import mysql

api_bp = Blueprint('api', __name__)


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


@api_bp.route('/api/asesorias', methods=['GET'])
@jwt_required()
def listar_asesorias():
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT a.id, a.created_at, p.nombre AS producto_nombre, p.imagen_url AS producto_imagen_url,
               a.resultado, a.superficie, a.uso, a.area_m2, a.litros_estimados
        FROM asesorias a
        LEFT JOIN productos p ON a.producto_recomendado_id = p.id
        WHERE a.usuario_id = %s
        ORDER BY a.created_at DESC
        """,
        (user_id,)
    )
    asesorias = cur.fetchall()
    cur.close()

    return jsonify([
        {
            'id': a['id'],
            'fecha': a['created_at'].isoformat() if a.get('created_at') else None,
            'producto_recomendado': a.get('producto_nombre'),
            'imagen_url': a.get('producto_imagen_url'),
            'resultado': a.get('resultado'),
            'superficie': a.get('superficie'),
            'uso': a.get('uso'),
            'area_m2': a.get('area_m2'),
            'litros_estimados': a.get('litros_estimados'),
        }
        for a in asesorias
    ]), 200


@api_bp.route('/api/favoritos', methods=['GET'])
@jwt_required()
def listar_favoritos():
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.nombre, p.imagen_url, p.precio_referencia, p.acabado, p.uso "
        "FROM favoritos f "
        "JOIN productos p ON f.producto_id = p.id "
        "WHERE f.usuario_id = %s "
        "ORDER BY f.created_at DESC",
        (user_id,)
    )
    favoritos = cur.fetchall()
    cur.close()

    return jsonify([
        {
            'id': f['id'],
            'nombre': f['nombre'],
            'imagen_url': f.get('imagen_url'),
            'precio_referencia': float(f['precio_referencia']) if isinstance(f.get('precio_referencia'), Decimal) else f.get('precio_referencia'),
            'acabado': f.get('acabado'),
            'uso': f.get('uso'),
        }
        for f in favoritos
    ]), 200


@api_bp.route('/api/favoritos/<int:producto_id>', methods=['DELETE'])
@jwt_required()
def eliminar_favorito(producto_id):
    user_id = get_jwt_identity()
    cur = mysql.connection.cursor()
    cur.execute(
        "DELETE FROM favoritos WHERE usuario_id = %s AND producto_id = %s",
        (user_id, producto_id)
    )
    deleted = cur.rowcount
    mysql.connection.commit()
    cur.close()

    if deleted == 0:
        abort(404, description='Favorito no encontrado')

    return jsonify({'message': 'Favorito eliminado.'}), 200


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
