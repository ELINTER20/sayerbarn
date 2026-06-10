"""Script para actualizar la imagen del producto 'barniz de prueba'.
Ejecutar una sola vez: python update_imagen_barniz.py
"""
from app import create_app, mysql

app = create_app()

IMAGEN_URL = 'https://cdn.homedepot.com.mx/productos/725165/725165-m.jpg'

with app.app_context():
    cur = mysql.connection.cursor()

    # Busca todos los productos cuyo nombre contenga 'barniz' y 'prueba'
    cur.execute(
        "SELECT id, nombre, imagen_url FROM productos WHERE nombre LIKE %s",
        ('%prueba%',)
    )
    productos = cur.fetchall()

    if not productos:
        print("No se encontró ningún producto con 'prueba' en el nombre.")
    else:
        for p in productos:
            print(f"Encontrado: ID={p['id']} | Nombre={p['nombre']} | imagen_url actual={p['imagen_url']}")

        confirmar = input("\n¿Actualizar la imagen de TODOS los productos listados? (s/n): ").strip().lower()
        if confirmar == 's':
            for p in productos:
                cur.execute(
                    "UPDATE productos SET imagen_url = %s WHERE id = %s",
                    (IMAGEN_URL, p['id'])
                )
            mysql.connection.commit()
            print(f"✓ Imagen actualizada: {IMAGEN_URL}")
        else:
            print("Cancelado.")

    cur.close()
