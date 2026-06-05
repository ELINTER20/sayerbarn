from flask import Flask
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_mysqldb import MySQL
from .config import Config

# Instancias globales de extensiones; se vinculan a la app en create_app()
bcrypt = Bcrypt()   # Encriptación de contraseñas
jwt = JWTManager()  # Manejo de tokens JWT
mysql = MySQL()     # Conexión a la base de datos MySQL

def create_app():
    # Crea y configura la aplicación Flask
    app = Flask(__name__)
    app.config.from_object(Config)  # Carga la configuración desde config.py

    # Vincula cada extensión con la instancia de la app
    bcrypt.init_app(app)
    jwt.init_app(app)
    mysql.init_app(app)

    # Importa y registra los blueprints (grupos de rutas)
    from .routes import main           # Rutas públicas (inicio, login, catálogo, etc.)
    from .routes.admin import admin_bp # Rutas del panel de administración (/admin/...)
    from .routes.api import api_bp     # Rutas de la API REST (/api/...)

    app.register_blueprint(main)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    return app