import json
import unittest

from sqlalchemy import inspect

from tests.test_support import reset_database

from app.database import engine
from app.main import health_check
from app.schemas.common import api_error, api_success


class BackendFoundationTests(unittest.TestCase):
    def setUp(self):
        reset_database()

    def test_api_success_response_shape(self):
        response = api_success({"status": "ok"})
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"], {"status": "ok"})

    def test_api_error_response_shape(self):
        response = api_error("TEST_ERROR", "Mensagem de teste.", status_code=422)
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 422)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"]["code"], "TEST_ERROR")

    def test_root_health_check_is_safe(self):
        payload = health_check()

        self.assertEqual(payload["status"], "ok")
        self.assertIn("app", payload)
        self.assertIn("environment", payload)

    def test_admin_audit_log_table_exists(self):
        tables = set(inspect(engine).get_table_names())

        self.assertIn("admin_audit_logs", tables)


if __name__ == "__main__":
    unittest.main()
