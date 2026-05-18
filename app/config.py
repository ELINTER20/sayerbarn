import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')

    JWT_TOKEN_LOCATION = ['cookies']
    # En Railway (HTTPS) las cookies deben ser Secure
    JWT_COOKIE_SECURE = os.getenv('RAILWAY_ENVIRONMENT') is not None
    JWT_ACCESS_COOKIE_PATH = '/'
    JWT_COOKIE_CSRF_PROTECT = False

    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    # Railway expone MYSQL_DATABASE; localmente se usa MYSQL_DB
    MYSQL_DB = os.getenv('MYSQL_DATABASE') or os.getenv('MYSQL_DB', 'sayerbarn')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_CURSORCLASS = 'DictCursor'

    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')