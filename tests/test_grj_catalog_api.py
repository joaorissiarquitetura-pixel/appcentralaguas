import json
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import grj_catalog


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class GRJCatalogApiTests(unittest.TestCase):
    def test_fetch_products_uses_bearer_token_and_maps_fields(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["authorization"] = request.get_header("Authorization")
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "status": "ok",
                    "data": [
                        {
                            "id": 123,
                            "codigo": "123",
                            "nome": "Hidroleve 20L",
                            "unidade": "UN",
                            "preco_venda": 17.0,
                            "estoque_disponivel": 10.0,
                            "apelido": "Galão retornável",
                        }
                    ],
                }
            )

        with patch.object(settings, "CENTRAL_AGUAS_APP_TOKEN", "token-test"):
            with patch.object(settings, "CENTRAL_AGUAS_PRODUCTS_API_URL", "https://example.test/products"):
                with patch("app.services.grj_catalog.urllib.request.urlopen", fake_urlopen):
                    products = grj_catalog.fetch_grj_products()

        self.assertEqual(captured["authorization"], "Bearer token-test")
        self.assertEqual(captured["url"], "https://example.test/products")
        self.assertEqual(captured["timeout"], 8)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].id, 123)
        self.assertEqual(products[0].codigo, "123")
        self.assertEqual(products[0].nome, "Hidroleve 20L")
        self.assertEqual(products[0].unidade, "UN")
        self.assertEqual(products[0].preco_venda, 17.0)
        self.assertEqual(products[0].estoque_disponivel, 10.0)
        self.assertEqual(products[0].apelido, "Galão retornável")


if __name__ == "__main__":
    unittest.main()
