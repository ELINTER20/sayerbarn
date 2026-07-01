# helpers/uploads.py
# Utilidades para guardar imágenes subidas desde el panel admin (drag & drop / selector de archivo).

import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename

# Extensiones de imagen aceptadas
EXTENSIONES_PERMITIDAS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

# Tamaño máximo por imagen: 5MB
TAMANO_MAX_BYTES = 5 * 1024 * 1024

# Carpeta donde se guardan las imágenes de producto (dentro de app/static)
SUBCARPETA_PRODUCTOS = os.path.join('images', 'productos')


def guardar_imagen_producto(file_storage, clave):
    """Guarda en disco una imagen de producto subida vía <input type="file">.

    - file_storage: objeto FileStorage de request.files.get('imagen_file')
    - clave: clave del producto, se usa como prefijo del nombre de archivo

    Devuelve la ruta relativa (ej. '/static/images/productos/hi-0900-a1b2c3d4.jpg')
    lista para guardarse en la columna imagen_url, o None si no se envió archivo.

    Lanza ValueError si el archivo no es válido (formato o tamaño), para que la
    ruta que llama pueda mostrar el mensaje de error y volver a renderizar el formulario.
    """
    if not file_storage or not file_storage.filename:
        return None

    nombre_original = file_storage.filename
    ext = nombre_original.rsplit('.', 1)[-1].lower() if '.' in nombre_original else ''
    if ext not in EXTENSIONES_PERMITIDAS:
        raise ValueError('Formato de imagen no soportado. Usa PNG, JPG, WEBP o GIF.')

    # Verifica el tamaño sin cargar el archivo completo en memoria dos veces
    file_storage.stream.seek(0, os.SEEK_END)
    tamano = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if tamano > TAMANO_MAX_BYTES:
        raise ValueError('La imagen supera el tamaño máximo de 5MB.')
    if tamano == 0:
        raise ValueError('El archivo de imagen está vacío.')

    # Nombre único: clave-en-minusculas + 8 caracteres aleatorios, para evitar
    # colisiones si se sube más de una imagen para el mismo producto
    base = secure_filename(clave or 'producto').lower() or 'producto'
    nombre_archivo = f"{base}-{uuid.uuid4().hex[:8]}.{ext}"

    carpeta = os.path.join(current_app.root_path, 'static', SUBCARPETA_PRODUCTOS)
    os.makedirs(carpeta, exist_ok=True)
    file_storage.save(os.path.join(carpeta, nombre_archivo))

    return f"/static/{SUBCARPETA_PRODUCTOS.replace(os.sep, '/')}/{nombre_archivo}"