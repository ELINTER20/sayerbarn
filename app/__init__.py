from flask import Flask
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_mysqldb import MySQL
from .config import Config

# Instancias globales de extensiones; se vinculan a la app en create_app()
bcrypt = Bcrypt()   # Encriptación de contraseñas
jwt    = JWTManager()  # Manejo de tokens JWT
mysql  = MySQL()       # Conexión a la base de datos MySQL


def create_app():
    """Application factory — crea y configura la instancia de Flask."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Vincula cada extensión con la instancia de la app
    bcrypt.init_app(app)
    jwt.init_app(app)
    mysql.init_app(app)

    # ── Registro de blueprints ────────────────────────────────
    # Cada blueprint agrupa las rutas de un dominio funcional.
    # El orden no importa para Flask, pero se lista de mayor a menor tráfico esperado.

    from .routes.public  import public_bp   # /, /catalogo, /producto, /asesoria, /carrito
    from .routes.auth    import auth_bp     # /login, /registro, /logout, /reset-password
    from .routes.usuario import usuario_bp  # /favoritos, /historial, /mi-cuenta
    from .routes.pedidos import pedidos_bp  # /checkout, /mis-pedidos, /pedido/confirmacion
    from .routes.admin   import admin_bp    # /admin/* — panel de administración
    from .routes.api     import api_bp      # /api/* — endpoints JSON para IA y carrito

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(usuario_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    return app