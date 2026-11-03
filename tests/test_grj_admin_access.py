import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_db
from app.middleware.security_headers import security_headers_middleware
from app.models import Attendant
from app.routers import grj_admin
from app.auth import get_current_attendant_id
from app.services.grj_admin import GRJ_COOKIE


class GRJAdminAccessTests(unittest.TestCase):
    def setUp(self):
        reset_database()
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-only-secret-with-32-characters")
        app.middleware("http")(security_headers_middleware)
        app.include_router(grj_admin.router)
        def db_session():
            with get_session() as db:
                yield db
        app.dependency_overrides[get_db] = db_session
        @app.get("/admin")
        def protected_page(request: Request):
            return {"attendant_id": get_current_attendant_id(request)}
        self.client = TestClient(app, base_url="https://app.centralaguas.com.br")

    @patch.object(grj_admin, "redeem_grj_code")
    def test_untrusted_parent_is_rejected_before_redemption(self, redeem):
        response = self.client.post("/integracoes/grj/acesso", data={"code": "x" * 43}, headers={"origin": "https://example.test"})
        self.assertEqual(response.status_code, 403)
        redeem.assert_not_called()

    @patch.object(grj_admin, "redeem_grj_code", return_value={"user": {"id": 42, "name": "João", "email": "admin@example.test"}, "section": "painel"})
    def test_grj_admin_gets_partitioned_session_and_existing_panel(self, redeem):
        response = self.client.post("/integracoes/grj/acesso", data={"code": "x" * 43}, headers={"origin": "https://www.grupogrj.com.br"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")
        cookie = response.headers["set-cookie"]
        for value in (GRJ_COOKIE, "HttpOnly", "Secure", "SameSite=None", "Partitioned"):
            self.assertIn(value, cookie)
        protected = self.client.get("/admin")
        self.assertIsInstance(protected.json()["attendant_id"], int)
        self.assertIn("frame-ancestors", protected.headers["content-security-policy"])
        self.assertNotIn("x-frame-options", protected.headers)
        self.assertEqual(protected.headers["cache-control"], "no-store")

    @patch.object(grj_admin, "redeem_grj_code", side_effect=ValueError("expired"))
    def test_expired_grant_cannot_create_admin(self, redeem):
        response = self.client.post("/integracoes/grj/acesso", data={"code": "x" * 43}, headers={"origin": "https://www.grupogrj.com.br"})
        self.assertEqual(response.status_code, 403)
        with get_session() as db:
            self.assertEqual(db.query(Attendant).count(), 0)

    def test_tampered_cookie_does_not_authenticate(self):
        self.client.cookies.set(GRJ_COOKIE, "tampered")
        response = self.client.get("/admin")
        self.assertIsNone(response.json()["attendant_id"])
        self.assertEqual(response.headers["x-frame-options"], "SAMEORIGIN")

    def test_logout_clears_partitioned_cookie(self):
        response = self.client.get("/integracoes/grj/sair")
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertIn("Partitioned", response.headers["set-cookie"])
