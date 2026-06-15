from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app import mysql

# Blueprint de administración: todas sus rutas empiezan con /admin
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Decorador que protege rutas: solo permite acceso a usuarios con rol 'admin'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            verify_jwt_in_request()  # Verifica que haya un JWT válido en la cookie
            user_id = get_jwt_identity()
            cur = mysql.connection.cursor()
            cur.execute("SELECT rol FROM usuarios WHERE id = %s AND activo = 1", (user_id,))
            usuario = cur.fetchone()
            cur.close()
            # Si el usuario no existe o no es admin, devuelve error 403
            if not usuario or usuario['rol'] != 'admin':
                abort(403)
        except Exception:
            # Si no hay sesión válida, redirige al login
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def dashboard():
    cur = mysql.connection.cursor()

    # Cuenta total de productos activos en el catálogo
    cur.execute("SELECT COUNT(*) as total FROM productos WHERE activo = 1")
    productos_activos = cur.fetchone()['total']

    # Cuenta el total de asesorías realizadas en todo el historial
    cur.execute("SELECT COUNT(*) as total FROM asesorias")
    total_asesorias = cur.fetchone()['total']

    # Cuenta publicaciones actualmente en estado 'publicado' en marketplace
    cur.execute("SELECT COUNT(*) as total FROM publicaciones_marketplace WHERE estado = 'publicado'")
    publicaciones_ml = cur.fetchone()['total']

    # Cuenta pedidos pendientes de gestión (pendiente + pagado)
    cur.execute("SELECT COUNT(*) as total FROM pedidos WHERE estado_pedido IN ('pendiente','pagado')")
    pedidos_pendientes = cur.fetchone()['total']

    # Los 5 productos más recomendados por la IA en los últimos 7 días
    cur.execute("""
        SELECT p.nombre, COUNT(a.id) as recomendaciones
        FROM productos p
        JOIN asesorias a ON a.producto_recomendado_id = p.id
        WHERE a.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY p.id, p.nombre
        ORDER BY recomendaciones DESC
        LIMIT 5
    """)
    top_productos = cur.fetchall()
    cur.close()

    return render_template(
        'admin/dashboard.html',
        productos_activos=productos_activos,
        total_asesorias=total_asesorias,
        publicaciones_ml=publicaciones_ml,
        pedidos_pendientes=pedidos_pendientes,
        top_productos=top_productos
    )


# ── Gestión de productos ──────────────────────────────────

@admin_bp.route('/productos')
@admin_required
def productos():
    # Lista productos con paginación (20 por página)
    pagina = request.args.get('pagina', 1, type=int)
    por_pagina = 20
    offset = (pagina - 1) * por_pagina  # Calcula desde qué registro empezar

    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT p.id, p.clave, p.nombre, p.imagen_url, p.uso, p.acabado, p.activo, "
        "COALESCE(p.stock, 0) AS stock, "
        "c.nombre as categoria "
        "FROM productos p "
        "LEFT JOIN categorias c ON p.categoria_id = c.id "
        "ORDER BY p.created_at DESC LIMIT %s OFFSET %s",
        (por_pagina, offset)
    )
    productos_lista = cur.fetchall()

    # Cuenta el total para calcular cuántas páginas hay
    cur.execute("SELECT COUNT(*) as total FROM productos")
    total = cur.fetchone()['total']
    cur.close()

    return render_template(
        'admin/productos.html',
        productos=productos_lista,
        pagina=pagina,
        total=total,
        por_pagina=por_pagina
    )


@admin_bp.route('/productos/nuevo', methods=['GET', 'POST'])
@admin_required
def agregar_producto():
    """Formulario para crear un nuevo producto en el catálogo.
    GET:  muestra el formulario vacío con la lista de categorías.
    POST: valida los campos obligatorios e inserta el producto en la BD."""

    # Cargar categorías para el selector del formulario
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
    categorias = cur.fetchall()
    cur.close()

    if request.method == 'POST':
        # Recoger todos los campos del formulario
        clave       = request.form.get('clave', '').strip().upper()
        nombre      = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip() or None
        categoria_id= request.form.get('categoria_id', type=int)
        uso         = request.form.get('uso') or None
        acabado     = request.form.get('acabado') or None
        imagen_url  = request.form.get('imagen_url', '').strip() or None
        rendimiento = request.form.get('rendimiento', type=float) or None
        precio      = request.form.get('precio', type=float) or None
        enlace      = request.form.get('enlace', '').strip() or None
        # Checkboxes de superficie: 1 si marcados, 0 si no
        sup_madera  = 1 if request.form.get('sup_madera') else 0
        sup_metal   = 1 if request.form.get('sup_metal') else 0
        sup_concreto= 1 if request.form.get('sup_concreto') else 0
        sup_otro    = 1 if request.form.get('sup_otro') else 0

        # Guardar valores para repoblar el formulario si hay error
        form_data = {
            'clave': clave, 'nombre': nombre, 'descripcion': descripcion,
            'categoria_id': str(categoria_id) if categoria_id else '',
            'uso': uso, 'acabado': acabado, 'imagen_url': imagen_url,
            'rendimiento': rendimiento, 'precio': precio, 'enlace': enlace,
            'sup_madera': sup_madera, 'sup_metal': sup_metal,
            'sup_concreto': sup_concreto, 'sup_otro': sup_otro,
        }

        # Validar campos obligatorios
        if not clave or not nombre or not categoria_id:
            return render_template('admin/agregar_producto.html',
                                   categorias=categorias,
                                   form=form_data,
                                   error='Los campos Clave, Nombre y Categoría son obligatorios.')

        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO productos
                  (clave, nombre, descripcion_ia, categoria_id,
                   uso, acabado,
                   sup_madera, sup_metal, sup_concreto, sup_otro,
                   rendimiento_min, precio_referencia,
                   imagen_url, link_compra_ml, activo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
            """, (clave, nombre, descripcion, categoria_id,
                  uso, acabado,
                  sup_madera, sup_metal, sup_concreto, sup_otro,
                  rendimiento, precio,
                  imagen_url, enlace))
            mysql.connection.commit()
            cur.close()
        except Exception as e:
            print(f"[ERROR AGREGAR PRODUCTO] {type(e).__name__}: {e}")
            # Error 1062 = clave duplicada en MySQL
            msg = 'Ya existe un producto con esa clave.' if (hasattr(e, 'args') and e.args and e.args[0] == 1062) \
                  else f'Error al guardar el producto: {e}'
            return render_template('admin/agregar_producto.html',
                                   categorias=categorias,
                                   form=form_data,
                                   error=msg)

        return redirect(url_for('admin.productos'))

    # GET: formulario vacío
    return render_template('admin/agregar_producto.html',
                           categorias=categorias,
                           form={})


@admin_bp.route('/productos/<int:id>/editar', methods=['GET', 'POST'])
@admin_required
def editar_producto(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        acabado = request.form.get('acabado') or None
        rendimiento = request.form.get('rendimiento') or None
        enlace = request.form.get('enlace', '').strip() or None
        uso = request.form.get('uso') or None
        imagen_url = request.form.get('imagen_url', '').strip() or None
        sup_madera = 1 if request.form.get('sup_madera') else 0
        sup_metal = 1 if request.form.get('sup_metal') else 0
        sup_concreto = 1 if request.form.get('sup_concreto') else 0
        sup_otro = 1 if request.form.get('sup_otro') else 0

        cur.execute("""
            UPDATE productos SET
                nombre = %s, descripcion_ia = %s, acabado = %s,
                rendimiento_min = %s, link_compra_ml = %s, uso = %s,
                imagen_url = %s,
                sup_madera = %s, sup_metal = %s, sup_concreto = %s, sup_otro = %s
            WHERE id = %s
        """, (nombre, descripcion, acabado, rendimiento, enlace, uso,
              imagen_url, sup_madera, sup_metal, sup_concreto, sup_otro, id))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('admin.productos'))

    # GET: carga los datos actuales del producto para prellenar el formulario
    cur.execute("SELECT * FROM productos WHERE id = %s", (id,))
    producto = cur.fetchone()
    cur.close()

    if not producto:
        abort(404)

    return render_template('admin/editar_producto.html', producto=producto)


@admin_bp.route('/productos/<int:id>/toggle', methods=['POST'])
@admin_required
def toggle_producto(id):
    # Alterna el estado activo/inactivo del producto sin borrarlo
    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET activo = NOT activo WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.productos'))


@admin_bp.route('/productos/<int:id>/stock', methods=['POST'])
@admin_required
def actualizar_stock(id):
    """Actualiza el stock de un producto. Acepta JSON o form-data.
    Devuelve JSON para poder usarlo con fetch desde el template."""
    from flask import jsonify as _jsonify
    data = request.get_json(silent=True) or {}
    nuevo_stock = data.get('stock') if data else request.form.get('stock', type=int)
    try:
        nuevo_stock = max(0, int(nuevo_stock))
    except (TypeError, ValueError):
        return _jsonify({'error': 'Valor inválido'}), 400

    cur = mysql.connection.cursor()
    cur.execute("UPDATE productos SET stock = %s WHERE id = %s", (nuevo_stock, id))
    mysql.connection.commit()
    cur.close()
    return _jsonify({'ok': True, 'stock': nuevo_stock})


@admin_bp.route('/productos/<int:id>/eliminar', methods=['POST'])
@admin_required
def eliminar_producto(id):
    """Elimina físicamente el producto de la BD.
    Si falla por FKs con pedidos existentes hace baja lógica (activo=0)
    para no perder el historial de pedidos."""
    cur = mysql.connection.cursor()
    try:
        # Elimina relaciones directas sin historial crítico
        cur.execute("DELETE FROM complementos WHERE producto_id = %s OR complemento_id = %s", (id, id))
        cur.execute("DELETE FROM favoritos WHERE producto_id = %s", (id,))
        cur.execute("DELETE FROM estadisticas_productos WHERE producto_id = %s", (id,))
        cur.execute("DELETE FROM productos WHERE id = %s", (id,))
        mysql.connection.commit()
    except Exception:
        # Producto referenciado en pedidos: solo desactiva para no perder historial
        mysql.connection.rollback()
        cur.execute("UPDATE productos SET activo = 0 WHERE id = %s", (id,))
        mysql.connection.commit()
    finally:
        cur.close()
    return redirect(url_for('admin.productos'))


# ── Complementos ──────────────────────────────────────────

@admin_bp.route('/complementos')
@admin_required
def complementos():
    # Lista todas las relaciones producto-complemento (ej: barniz + diluyente)
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id, c.tipo, c.proporcion,
               p1.nombre as producto_nombre,
               p2.nombre as complemento_nombre
        FROM complementos c
        JOIN productos p1 ON c.producto_id = p1.id
        JOIN productos p2 ON c.complemento_id = p2.id
        ORDER BY c.id DESC
    """)
    complementos_lista = cur.fetchall()

    # Carga la lista de productos activos para el selector del formulario de agregar
    cur.execute("SELECT id, nombre FROM productos WHERE activo = 1 ORDER BY nombre")
    productos_lista = cur.fetchall()
    cur.close()

    return render_template(
        'admin/complementos.html',
        complementos=complementos_lista,
        productos=productos_lista
    )


@admin_bp.route('/complementos/agregar', methods=['POST'])
@admin_required
def agregar_complemento():
    # Crea una nueva relación entre un producto y su complemento
    producto_id = request.form.get('producto_id', type=int)
    complemento_id = request.form.get('complemento_id', type=int)
    tipo = request.form.get('tipo')
    proporcion = request.form.get('proporcion', '').strip() or None

    # Valida que los campos obligatorios estén presentes
    if not producto_id or not complemento_id or not tipo:
        return redirect(url_for('admin.complementos'))

    cur = mysql.connection.cursor()
    cur.execute(
        "INSERT INTO complementos (producto_id, complemento_id, tipo, proporcion) VALUES (%s, %s, %s, %s)",
        (producto_id, complemento_id, tipo, proporcion)
    )
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.complementos'))


@admin_bp.route('/complementos/<int:id>/eliminar', methods=['POST'])
@admin_required
def eliminar_complemento(id):
    # Elimina permanentemente la relación complemento de la BD
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM complementos WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin.complementos'))


# ── Publicaciones Marketplace ─────────────────────────────

@admin_bp.route('/pedidos')
@admin_required
def pedidos():
    """Lista pedidos agrupados por período y agrupa items del mismo comprador/fecha en una venta."""
    filtro_estado  = request.args.get('estado', '').strip() or None
    periodo        = request.args.get('periodo', 'hoy').strip()

    fmt_map = {
        'hoy':    "DATE(pd.created_at)",
        'dia':    "DATE(pd.created_at)",
        'semana': "DATE(pd.created_at - INTERVAL WEEKDAY(pd.created_at) DAY)",
        'mes':    "DATE_FORMAT(pd.created_at, '%%Y-%%m-01')",
    }
    fecha_expr = fmt_map.get(periodo, fmt_map['dia'])

    condiciones = ["1=1"]
    params = []
    if periodo == 'hoy':
        condiciones.append("DATE(pd.created_at) = CURDATE()")
    if filtro_estado:
        condiciones.append("pd.estado_pedido = %s")
        params.append(filtro_estado)
    where = " AND ".join(condiciones)

    cur = mysql.connection.cursor()
    cur.execute(f"""
        SELECT pd.id, pd.usuario_id, pd.nombre_comprador, pd.telefono,
               pd.ciudad, pd.estado_mx, pd.canal,
               pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pr.nombre AS nombre_producto, pr.imagen_url,
               {fecha_expr} AS periodo_fecha
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE {where}
        ORDER BY pd.created_at DESC
    """, params if params else ())
    pedidos_lista = cur.fetchall()

    # Agrupar por período y dentro de cada período agrupar ventas del mismo comprador
    # Una "venta" = mismo nombre_comprador + misma fecha (DATE) + misma sesión
    from collections import OrderedDict
    grupos = OrderedDict()   # {periodo_fecha: [venta, ...]}
    # Una venta = {key, comprador, items: [], total, estado, canal, created_at, id}

    for p in pedidos_lista:
        pkey = str(p['periodo_fecha']) if p['periodo_fecha'] else 'Sin fecha'
        if pkey not in grupos:
            grupos[pkey] = OrderedDict()

        # Clave de venta: comprador + día exacto (para agrupar la misma sesión de compra)
        fecha_dia = str(p['created_at'].date()) if p['created_at'] else 'nd'
        # Agrupar items creados dentro de los mismos 10 minutos (misma sesión)
        minuto_base = (p['created_at'].hour * 60 + p['created_at'].minute) // 10 if p['created_at'] else 0
        venta_key = f"{p['nombre_comprador']}|{fecha_dia}|{minuto_base}|{p['usuario_id'] or 'anon'}"

        if venta_key not in grupos[pkey]:
            grupos[pkey][venta_key] = {
                'id_principal': p['id'],
                'nombre_comprador': p['nombre_comprador'],
                'telefono': p['telefono'],
                'ciudad': p['ciudad'],
                'estado_mx': p['estado_mx'],
                'canal': p['canal'],
                'estado_pedido': p['estado_pedido'],
                'created_at': p['created_at'],
                'productos': [],
                'total': 0.0,
            }
        venta = grupos[pkey][venta_key]
        venta['productos'].append({
            'id': p['id'],
            'nombre_producto': p['nombre_producto'],
            'imagen_url': p['imagen_url'],
            'cantidad': p['cantidad'],
            'total': float(p['total']) if p['total'] else 0.0,
        })
        venta['total'] += float(p['total']) if p['total'] else 0.0

    # Convertir OrderedDict interno a listas para el template
    grupos_lista = OrderedDict()
    for pkey, ventas_dict in grupos.items():
        grupos_lista[pkey] = list(ventas_dict.values())

    # Stock bajo (≤5) para alerta en dashboard
    cur.execute("""
        SELECT id, nombre, COALESCE(stock,0) AS stock
        FROM productos
        WHERE activo = 1 AND COALESCE(stock,0) <= 5
        ORDER BY stock ASC
    """)
    stock_bajo = cur.fetchall()
    cur.close()

    return render_template('admin/pedidos.html',
                           grupos=grupos_lista,
                           filtro_estado=filtro_estado,
                           periodo=periodo,
                           stock_bajo=stock_bajo)


@admin_bp.route('/pedidos/exportar-pdf')
@admin_required
def exportar_pedidos_pdf():
    """Genera un PDF real con reportlab.
    Si reportlab no está instalado, devuelve un aviso claro en lugar de un HTML."""
    from flask import make_response

    # Verificar que reportlab esté disponible antes de hacer cualquier query
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError:
        # Instrucción clara para el desarrollador
        msg = (
            "reportlab no está instalado en este entorno.\n"
            "Ejecuta: pip install reportlab\n"
            "Luego reinicia Flask y vuelve a intentarlo."
        )
        response = make_response(msg, 500)
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        return response

    from io import BytesIO
    import datetime

    filtro_estado = request.args.get('estado', '').strip() or None
    periodo       = request.args.get('periodo', 'hoy').strip()

    fmt_map = {
        'hoy':    "DATE(pd.created_at)",
        'dia':    "DATE(pd.created_at)",
        'semana': "DATE(pd.created_at - INTERVAL WEEKDAY(pd.created_at) DAY)",
        'mes':    "DATE_FORMAT(pd.created_at, '%%Y-%%m-01')",
    }
    fecha_expr = fmt_map.get(periodo, fmt_map['dia'])

    condiciones = ["1=1"]
    params = []
    if periodo == 'hoy':
        condiciones.append("DATE(pd.created_at) = CURDATE()")
    if filtro_estado:
        condiciones.append("pd.estado_pedido = %s")
        params.append(filtro_estado)
    where = " AND ".join(condiciones)

    cur = mysql.connection.cursor()
    cur.execute(f"""
        SELECT pd.id, pd.nombre_comprador, pd.ciudad, pd.estado_mx,
               pd.canal, pd.cantidad, pd.total, pd.estado_pedido, pd.created_at,
               pr.nombre AS nombre_producto,
               {fecha_expr} AS periodo_fecha
        FROM pedidos pd
        JOIN productos pr ON pd.producto_id = pr.id
        WHERE {where}
        ORDER BY pd.created_at DESC
    """, params if params else ())
    pedidos_lista = cur.fetchall()
    cur.close()

    # Agrupar por período
    from collections import OrderedDict
    grupos = OrderedDict()
    for p in pedidos_lista:
        key = str(p['periodo_fecha']) if p['periodo_fecha'] else 'Sin fecha'
        if key not in grupos:
            grupos[key] = []
        grupos[key].append(p)

    total_general = sum(float(p['total']) for p in pedidos_lista if p['total'])

    # ── Construir el PDF con ReportLab ──────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    azul   = colors.HexColor('#0033A0')
    gris   = colors.HexColor('#E8EDF7')
    blanco = colors.white

    titulo_style = ParagraphStyle('titulo', fontSize=18, textColor=azul,
                                  fontName='Helvetica-Bold', spaceAfter=4)
    meta_style   = ParagraphStyle('meta', fontSize=9, textColor=colors.grey,
                                  spaceAfter=16)
    grupo_style  = ParagraphStyle('grupo', fontSize=11, textColor=azul,
                                  fontName='Helvetica-Bold', spaceBefore=12, spaceAfter=4)

    periodo_labels = {'hoy': 'Hoy', 'dia': 'Día', 'semana': 'Semana', 'mes': 'Mes'}
    ahora = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')

    elementos = [
        Paragraph('Reporte de Pedidos — SayerBarn', titulo_style),
        Paragraph(
            f'Período: {periodo_labels.get(periodo, periodo)}'
            + (f' | Estado: {filtro_estado.capitalize()}' if filtro_estado else '')
            + f' | Generado: {ahora}',
            meta_style
        ),
    ]

    col_w = [1.2*cm, 4.5*cm, 3.5*cm, 2.5*cm, 1.5*cm, 2.2*cm, 2.2*cm]
    header = ['#', 'Producto', 'Comprador', 'Ciudad', 'Cant.', 'Total', 'Estado']

    for fecha_key, pedidos in grupos.items():
        subtotal = sum(float(p['total']) for p in pedidos if p['total'])

        elementos.append(Paragraph(
            f'{fecha_key}  —  {len(pedidos)} pedido{"s" if len(pedidos)!=1 else ""}  |  Subtotal: ${subtotal:,.2f} MXN',
            grupo_style
        ))

        data = [header]
        for p in pedidos:
            data.append([
                f'#{p["id"]}',
                p['nombre_producto'][:30],
                p['nombre_comprador'][:22],
                f'{p["ciudad"] or "—"}',
                str(p['cantidad']),
                f'${float(p["total"]):,.2f}' if p['total'] else '—',
                p['estado_pedido'].capitalize(),
            ])

        t = Table(data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,0), azul),
            ('TEXTCOLOR',    (0,0), (-1,0), blanco),
            ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [blanco, gris]),
            ('GRID',         (0,0), (-1,-1), 0.25, colors.HexColor('#D0D7EE')),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ]))
        elementos.append(t)
        elementos.append(Spacer(1, 0.3*cm))

    # Fila de total general — usar SPAN para evitar que el texto se encime
    n_pedidos = len(pedidos_lista)
    total_data = [['TOTAL GENERAL', '', '', '', '', f'${total_general:,.2f} MXN', f'{n_pedidos} pedido{"s" if n_pedidos != 1 else ""}']]
    total_t = Table(total_data, colWidths=col_w)
    total_t.setStyle(TableStyle([
        ('BACKGROUND',   (0,0), (-1,-1), azul),
        ('TEXTCOLOR',    (0,0), (-1,-1), blanco),
        ('FONTNAME',     (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,-1), 9),
        ('TOPPADDING',   (0,0), (-1,-1), 7),
        ('BOTTOMPADDING',(0,0), (-1,-1), 7),
        # Fusionar columnas 0-4 para que "TOTAL GENERAL" tenga espacio
        ('SPAN',         (0,0), (4,0)),
        ('ALIGN',        (0,0), (4,0), 'RIGHT'),
        ('ALIGN',        (5,0), (5,0), 'RIGHT'),
        ('ALIGN',        (6,0), (6,0), 'CENTER'),
    ]))
    elementos.append(total_t)

    doc.build(elementos)

    pdf_bytes = buf.getvalue()
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=pedidos_{periodo}.pdf'
    return response

@admin_bp.route('/pedidos/<int:pedido_id>/estado', methods=['POST'])
@admin_required
def cambiar_estado_pedido(pedido_id):
    """Actualiza el estado de un pedido desde el panel admin.
    Acepta solo los valores válidos del ENUM para evitar inserciones incorrectas."""
    estados_validos = {'pendiente', 'pagado', 'en_proceso', 'entregado', 'cancelado'}
    nuevo_estado = request.form.get('estado', '').strip()

    if nuevo_estado in estados_validos:
        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE pedidos SET estado_pedido = %s WHERE id = %s",
            (nuevo_estado, pedido_id)
        )
        mysql.connection.commit()
        cur.close()

    # Conserva el filtro activo al volver a la lista
    filtro = request.args.get('estado', '')
    if filtro:
        return redirect(url_for('admin.pedidos', estado=filtro))
    return redirect(url_for('admin.pedidos'))


@admin_bp.route('/publicar')
@admin_required
def publicar():
    """Vista principal de publicaciones con formulario de nueva publicación."""
    exito = request.args.get('exito')
    error = request.args.get('error')
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT pm.id, pm.canal, pm.estado, pm.created_at,
               p.nombre as producto_nombre, p.imagen_url
        FROM publicaciones_marketplace pm
        JOIN productos p ON pm.producto_id = p.id
        ORDER BY pm.created_at DESC
        LIMIT 50
    """)
    publicaciones = cur.fetchall()
    cur.execute("SELECT id, nombre, clave FROM productos WHERE activo = 1 ORDER BY nombre")
    productos_activos = cur.fetchall()
    cur.close()
    return render_template('admin/publicar.html',
                           publicaciones=publicaciones,
                           productos_activos=productos_activos,
                           exito=exito,
                           error=error)


@admin_bp.route('/publicar/nueva', methods=['POST'])
@admin_required
def crear_publicacion():
    """Registra una nueva publicación en estado pendiente hasta integrar la API de ML."""
    producto_id = request.form.get('producto_id', type=int)
    canal = request.form.get('canal', 'mercadolibre').strip()

    if not producto_id:
        return redirect(url_for('admin.publicar', error='Debes seleccionar un producto.'))

    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO publicaciones_marketplace (producto_id, canal, estado)
            VALUES (%s, %s, 'pendiente')
        """, (producto_id, canal))
        mysql.connection.commit()
        cur.close()
    except Exception as e:
        print(f"[ERROR PUBLICAR] {e}")
        return redirect(url_for('admin.publicar', error='Error al registrar la publicación.'))

    return redirect(url_for('admin.publicar', exito='1'))