#!/usr/bin/env python
"""Initialize MySQL database and tables using settings from app.config.Config.

Run from the project root with the virtual environment active:
  .\\venv\\Scripts\\python.exe scripts\\init_mysql.py
"""
import os
import sys
import traceback

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config

try:
    import MySQLdb
except ImportError:
    print('MySQLdb is not installed. Install with: pip install mysqlclient')
    sys.exit(1)


def create_database_and_tables():
    host = Config.MYSQL_HOST
    user = Config.MYSQL_USER
    password = Config.MYSQL_PASSWORD
    port = Config.MYSQL_PORT
    db_name = Config.MYSQL_DB

    print(f'Connecting to MySQL host={host} port={port} user={user}')
    conn = MySQLdb.connect(host=host, user=user, passwd=password, port=port)
    conn.autocommit(True)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    print(f"Database '{db_name}' ensured.")
    cur.close()
    conn.close()

    conn = MySQLdb.connect(host=host, user=user, passwd=password, port=port, db=db_name)
    cur = conn.cursor()

    print('Creating table usuarios if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            rol VARCHAR(50) NOT NULL DEFAULT 'user',
            activo TINYINT(1) NOT NULL DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    print('Creating table categorias if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS categorias (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL UNIQUE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')
    # Insert default categories if they don't exist yet
    from app.helpers.categorias import DEFAULT_CATEGORIAS

    default_cats = DEFAULT_CATEGORIAS
    for cat in default_cats:
        try:
            cur.execute("INSERT IGNORE INTO categorias (nombre) VALUES (%s)", (cat,))
        except Exception:
            pass

    print('Creating table productos if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            clave VARCHAR(100) NOT NULL UNIQUE,
            nombre VARCHAR(255) NOT NULL,
            descripcion_ia TEXT,
            imagen_url VARCHAR(512),
            precio_referencia DECIMAL(12,2),
            acabado VARCHAR(255),
            uso VARCHAR(255),
            activo TINYINT(1) NOT NULL DEFAULT 1,
            categoria_id INT,
            rendimiento_min VARCHAR(255),
            link_compra_ml VARCHAR(512),
            sup_madera TINYINT(1) NOT NULL DEFAULT 0,
            sup_metal TINYINT(1) NOT NULL DEFAULT 0,
            sup_concreto TINYINT(1) NOT NULL DEFAULT 0,
            sup_otro TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    print('Creating table asesorias if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS asesorias (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id INT NOT NULL,
            superficie VARCHAR(255),
            uso VARCHAR(255),
            area_m2 DECIMAL(10,2),
            litros_estimados DECIMAL(10,2),
            resultado TEXT,
            producto_recomendado_id INT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (producto_recomendado_id) REFERENCES productos(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    print('Creating table publicaciones_marketplace if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS publicaciones_marketplace (
            id INT AUTO_INCREMENT PRIMARY KEY,
            producto_id INT NOT NULL,
            canal VARCHAR(255),
            estado VARCHAR(50),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    print('Creating table complementos if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS complementos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            producto_id INT NOT NULL,
            complemento_id INT NOT NULL,
            tipo VARCHAR(255),
            proporcion VARCHAR(255),
            FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE,
            FOREIGN KEY (complemento_id) REFERENCES productos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    print('Creating table favoritos if needed...')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS favoritos (
            usuario_id INT NOT NULL,
            producto_id INT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (usuario_id, producto_id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (producto_id) REFERENCES productos(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')

    conn.commit()
    cur.close()
    conn.close()
    print('MySQL initialization completed successfully.')


if __name__ == '__main__':
    try:
        create_database_and_tables()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
