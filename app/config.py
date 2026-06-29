import os
from datetime import timedelta
from dotenv import load_dotenv

# Calcula la ruta raíz del proyecto y carga el archivo .env desde ahí
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ENV_PATH = os.path.join(ROOT_DIR, '.env')
load_dotenv(ENV_PATH, override=True)  # override=True hace que .env sobreescriba variables del sistema

class Config:
    # Clave secreta de Flask para firmar sesiones y cookies
    SECRET_KEY = os.getenv('SECRET_KEY')
    # Clave secreta exclusiva para firmar los tokens JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')

    # Guarda el token JWT en cookies del navegador (no en localStorage)
    JWT_TOKEN_LOCATION = ['cookies']
    # En Railway (HTTPS) las cookies deben ser Secure
    JWT_COOKIE_SECURE = os.getenv('RAILWAY_ENVIRONMENT') is not None
    # La cookie del token aplica para todas las rutas del sitio
    JWT_ACCESS_COOKIE_PATH = '/'
    # Desactiva la protección CSRF (se confía en el dominio propio)
    JWT_COOKIE_CSRF_PROTECT = False
    # La sesión dura 1 día. Al cerrar el navegador y volver,
    # si pasó más de 1 día tendrá que iniciar sesión de nuevo.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)

    # Datos de conexión a MySQL leídos desde variables de entorno
    MYSQL_HOST = os.getenv('MYSQL_HOST')
    MYSQL_USER = os.getenv('MYSQL_USER')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
    # Railway expone MYSQL_DATABASE; localmente se usa MYSQL_DB
    MYSQL_DB = os.getenv('MYSQL_DATABASE') or os.getenv('MYSQL_DB')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    # DictCursor devuelve filas como diccionarios en vez de tuplas
    MYSQL_CURSORCLASS = 'DictCursor'

    # API key de OpenAI para el asistente de asesoría con IA
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

    # Mercado Pago — Checkout Pro
    MP_PUBLIC_KEY   = os.getenv('MP_PUBLIC_KEY')   # Para el frontend (no se usa en Checkout Pro)
    MP_ACCESS_TOKEN = os.getenv('MP_ACCESS_TOKEN') # Para crear preferencias desde el backend

    # URL base pública — se usa para construir los links de retorno de MP
    # En producción (Render) se lee del entorno; en local apunta a localhost
    BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')

    # URL del webhook de n8n para notificaciones de pedidos confirmados
    N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

    # Configuración opcional de correo para recuperación de contraseña
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() in ('true', '1', 'yes')
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'false').lower() in ('true', '1', 'yes')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', f"no-reply@{os.getenv('MAIL_DEFAULT_DOMAIN', 'example.com')}")

    # Mercado Libre — publicación de productos al marketplace
    ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN')