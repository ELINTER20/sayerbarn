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
