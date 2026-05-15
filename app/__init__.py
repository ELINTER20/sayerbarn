from flask import Flask
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from .config import Config

bcrypt = Bcrypt()
jwt = JWTManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    bcrypt.init_app(app)
    jwt.init_app(app)

    from .routes import main
    app.register_blueprint(main)

    return app