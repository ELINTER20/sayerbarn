from flask import Blueprint

main = Blueprint('main', __name__)

@main.route('/')
def index():
    return '<h1>SayerBarn funcionando ✓</h1>'