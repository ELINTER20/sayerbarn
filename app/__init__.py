from flask import Flask
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_mysqldb import MySQL
from .config import Config

bcrypt = Bcrypt()
jwt = JWTManager()
mysql = MySQL()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    bcrypt.init_app(app)
    jwt.init_app(app)
    mysql.init_app(app)

    from .routes import main
    app.register_blueprint(main)

    return app