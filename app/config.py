import os
from dotenv import load_dotenv

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(ENV_PATH, override=True)

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')

    JWT_TOKEN_LOCATION = ['cookies']
    # En Railway (HTTPS) las cookies deben ser Secure
    JWT_COOKIE_SECURE = os.getenv('RAILWAY_ENVIRONMENT') is not None
    JWT_ACCESS_COOKIE_PATH = '/'
    JWT_COOKIE_CSRF_PROTECT = False

    MYSQL_HOST = os.getenv('MYSQL_HOST')
    MYSQL_USER = os.getenv('MYSQL_USER')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
    # Railway expone MYSQL_DATABASE; localmente se usa MYSQL_DB
    MYSQL_DB = os.getenv('MYSQL_DATABASE') or os.getenv('MYSQL_DB')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT'))
    MYSQL_CURSORCLASS = 'DictCursor'

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')