#!/usr/bin/env python
"""Insert default categories into the database using app.config.Config.

Run with the project's virtualenv active:
  .\venv\Scripts\Activate.ps1
  python scripts\insert_categorias.py
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config
from app.helpers.categorias import DEFAULT_CATEGORIAS
try:
    import MySQLdb
except ImportError:
    print('MySQLdb not installed. Run: pip install mysqlclient')
    sys.exit(1)

def insert_categories():
    host = Config.MYSQL_HOST
    user = Config.MYSQL_USER
    password = Config.MYSQL_PASSWORD
    port = Config.MYSQL_PORT
    db_name = Config.MYSQL_DB

    cats = DEFAULT_CATEGORIAS

    print(f'Connecting to MySQL host={host} port={port} user={user} db={db_name}')
    conn = MySQLdb.connect(host=host, user=user, passwd=password, port=port, db=db_name)
    conn.autocommit(True)
    cur = conn.cursor()
    inserted = 0
    for cat in cats:
        cur.execute("INSERT IGNORE INTO categorias (nombre) VALUES (%s)", (cat,))
        if cur.rowcount:
            inserted += 1

    cur.close()
    conn.close()
    print(f'Done. Inserted {inserted} new categories (others ignored).')

if __name__ == '__main__':
    insert_categories()
