import unittest

from app.helpers.categorias import DEFAULT_CATEGORIAS, ensure_default_categories


class DefaultCategoriesTest(unittest.TestCase):
    def test_default_categories_include_all_requested_segments(self):
        required = {
            'Barnices para madera',
            'Diluyentes',
            'Complementos',
            'Catalizadores',
            'Selladores',
            'Fondos',
            'Separado',
            'Tinta al aceite',
            'Tinta al alcohol',
        }

        for category in required:
            with self.subTest(category=category):
                self.assertIn(category, DEFAULT_CATEGORIAS)

    def test_ensure_default_categories_inserts_missing_entries(self):
        class FakeCursor:
            def __init__(self):
                self.rows = [{'id': 1, 'nombre': 'Barnices para madera'}]
                self.executed = []

            def execute(self, query, params=()):
                self.executed.append((query, params))
                if 'SELECT id, nombre FROM categorias' in query:
                    self._result = self.rows
                elif 'INSERT IGNORE' in query:
                    self.rows.append({'id': len(self.rows) + 1, 'nombre': params[0]})
                    self._result = None

            def fetchall(self):
                return self.rows

            def close(self):
                return None

        class FakeConnection:
            def __init__(self):
                self.cursor_obj = FakeCursor()

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                return None

        connection = FakeConnection()
        result = ensure_default_categories(connection)

        self.assertIn('Diluyentes', [item['nombre'] for item in result])
        self.assertTrue(any('INSERT IGNORE' in query for query, _ in connection.cursor_obj.executed))


if __name__ == '__main__':
    unittest.main()
