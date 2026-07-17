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

COMBINED_CATEGORY_NAMES = {
    'diluyentes y complementos',
    'fondos y selladores',
}


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


def normalize_categories(connection):
    """Devuelve las categorías normalizadas, evitando nombres combinados antiguos."""
    categorias = ensure_default_categories(connection)
    categorias_por_nombre = {
        (cat.get('nombre') or '').strip(): cat
        for cat in categorias
    }

    normalizadas = []
    for nombre in DEFAULT_CATEGORIAS:
        cat = categorias_por_nombre.get(nombre)
        if cat:
            normalizadas.append(cat)

    for cat in categorias:
        nombre = (cat.get('nombre') or '').strip()
        if not nombre or nombre in DEFAULT_CATEGORIAS or nombre.lower() in COMBINED_CATEGORY_NAMES:
            continue
        normalizadas.append(cat)

    return normalizadas


def visible_categories(connection, exclude_keywords=None):
    """Devuelve la lista de categorías visibles para la UI, excluyendo
    aquellas cuyo nombre contiene cualquiera de los `exclude_keywords`.

    Por defecto excluye: separado.
    """
    if exclude_keywords is None:
        exclude_keywords = ['separado']

    categorias = normalize_categories(connection)
    visible = []
    for cat in categorias:
        nombre = (cat.get('nombre') or '').lower()
        if any(k in nombre for k in exclude_keywords):
            continue
        visible.append(cat)
    return visible
