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
                            "imagem_url": "/uploads/produtos/hidroleve-20l.png",
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
        self.assertEqual(products[0].image_url, "https://example.test/uploads/produtos/hidroleve-20l.png")
        self.assertEqual(
            grj_catalog.product_to_public_dict(products[0])["image_url"],
            "https://example.test/uploads/produtos/hidroleve-20l.png",
        )

    def test_fetch_products_keeps_negative_stock_as_indisponivel_for_testing(self):
        def fake_urlopen(request, timeout):
            return FakeResponse(
                {
                    "status": "ok",
                    "data": [
                        {
                            "id": 13,
                            "codigo": "13",
                            "nome": "Acquatuba 10L",
                            "unidade": "UN",
                            "preco_venda": 13.0,
                            "estoque_disponivel": -17.0,
                            "apelido": "",
                        }
                    ],
                }
            )

        with patch.object(settings, "CENTRAL_AGUAS_APP_TOKEN", "token-test"):
            with patch.object(settings, "CENTRAL_AGUAS_PRODUCTS_API_URL", "https://example.test/products"):
                with patch("app.services.grj_catalog.urllib.request.urlopen", fake_urlopen):
                    products = grj_catalog.fetch_grj_products()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].nome, "Acquatuba 10L")
        self.assertEqual(products[0].stock_status, "indisponivel")


if __name__ == "__main__":
    unittest.main()
