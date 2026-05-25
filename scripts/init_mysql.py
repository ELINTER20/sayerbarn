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
