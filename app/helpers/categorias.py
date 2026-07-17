"""Categorías base del catálogo de Sayer Barn."""

DEFAULT_CATEGORIAS = [
    'Barnices para madera',
    'Diluyentes',
    'Complementos',
    'Catalizadores',
    'Selladores',
    'Fondos',
    'Separado',
    'Tinta al aceite',
    'Tinta al alcohol',
]


def ensure_default_categories(connection):
    """Asegura que las categorías base existan en la base de datos y las devuelve."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
        categorias = cursor.fetchall()
        existing_names = {cat.get('nombre') for cat in categorias if cat.get('nombre')}

        missing = [name for name in DEFAULT_CATEGORIAS if name not in existing_names]
        if missing:
            for name in missing:
                cursor.execute("INSERT IGNORE INTO categorias (nombre) VALUES (%s)", (name,))
            connection.commit()
            cursor.execute("SELECT id, nombre FROM categorias ORDER BY nombre")
            categorias = cursor.fetchall()
    finally:
        cursor.close()

    return categorias


def visible_categories(connection, exclude_keywords=None):
    """Devuelve la lista de categorías visibles para la UI, excluyendo
    aquellas cuyo nombre contiene cualquiera de los `exclude_keywords`.

    Por defecto excluye: diluy, complement, fondo, sellador, separado.
    """
    if exclude_keywords is None:
        # Por defecto solo ocultamos 'separado'; mostrar diluyentes, complementos, fondos, selladores
        exclude_keywords = ['separado']

    categorias = ensure_default_categories(connection)
    visible = []
    for cat in categorias:
        nombre = (cat.get('nombre') or '').lower()
        if any(k in nombre for k in exclude_keywords):
            continue
        visible.append(cat)
    return visible
