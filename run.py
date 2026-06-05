import os
from app import create_app

# Crea la aplicación Flask usando la fábrica definida en app/__init__.py
app = create_app()

if __name__ == '__main__':
    # Lee el puerto desde variables de entorno; si no existe usa 5000 por defecto
    port = int(os.getenv('PORT', 5000))
    # Activa el modo debug solo si FLASK_DEBUG=true en las variables de entorno
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    # Inicia el servidor escuchando en todas las IPs del equipo
    app.run(host='0.0.0.0', port=port, debug=debug)