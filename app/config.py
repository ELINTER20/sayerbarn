import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')

    # JWT almacenado en cookie (compatible con templates Jinja2)
    JWT_TOKEN_LOCATION = ['cookies']
    JWT_COOKIE_SECURE = False        # True en producción (HTTPS)
    JWT_ACCESS_COOKIE_PATH = '/'
    JWT_COOKIE_CSRF_PROTECT = False  # Activar en producción

    MYSQL_HOST = os.getenv('MYSQL_HOST')
    MYSQL_USER = os.getenv('MYSQL_USER')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
    MYSQL_DB = os.getenv('MYSQL_DB')
    MYSQL_CURSORCLASS = 'DictCursor'

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')