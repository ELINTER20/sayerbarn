import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app, mysql

app = create_app()
print('MYSQL_HOST', app.config['MYSQL_HOST'])
print('MYSQL_DB', app.config['MYSQL_DB'])
print('MYSQL_PORT', app.config['MYSQL_PORT'])
print('MYSQL_USER', app.config['MYSQL_USER'])
print('MYSQL_PASSWORD', app.config['MYSQL_PASSWORD'])
print('mysql_class', type(mysql))

with app.app_context():
    try:
        cur = mysql.connection.cursor()
        cur.execute('SELECT 1')
        print('DB OK', cur.fetchone())
        cur.close()
    except Exception as e:
        print('DB ERROR', type(e).__name__, e)
