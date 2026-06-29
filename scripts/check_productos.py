"""Diagnóstico: muestra todos los productos y su imagen_url actual."""
from app import create_app, mysql

app = create_app()

with app.app_context():
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, nombre, imagen_url, activo FROM productos ORDER BY id")
    productos = cur.fetchall()
    cur.close()

    print(f"{'ID':<5} {'Activo':<7} {'imagen_url':<60} {'Nombre'}")
    print("-" * 120)
    for p in productos:
        img = p['imagen_url'] or '(vacío)'
        print(f"{p['id']:<5} {str(p['activo']):<7} {img[:58]:<60} {p['nombre']}")
