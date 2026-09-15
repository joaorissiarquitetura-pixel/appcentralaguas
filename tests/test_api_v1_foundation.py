import json
import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from app.api.v1.auth import login
from app.api.v1.products import list_products
from app.schemas.auth import CustomerLoginRequest
from app.services.auth_service import authenticate_customer, create_customer_account


class RequestStub:
    def __init__(self):
        self.session = {}


class ApiV1FoundationTests(unittest.TestCase):
    def setUp(self):
        reset_database()
        self.db = get_session()

    def tearDown(self):
        self.db.close()

    def test_customer_auth_service_creates_and_authenticates_customer(self):
        customer = create_customer_account(
            self.db,
            name="Cliente Teste",
            phone="(17) 99999-0000",
            password="1234",
            zip_code="15500000",
            street="Rua Teste",
            number="10",
            neighborhood="Centro",
        )

        authenticated = authenticate_customer(self.db, phone="17999990000", password="1234")

        self.assertEqual(authenticated.id, customer.id)

    def test_api_login_sets_existing_session_cookie_state(self):
        create_customer_account(
            self.db,
            name="Cliente App",
            phone="17988880000",
            password="1234",
            zip_code="15500000",
        )
        request = RequestStub()

        response = login(CustomerLoginRequest(phone="17988880000", password="1234"), request, self.db)
        payload = json.loads(response.body)

        self.assertTrue(payload["success"])
        self.assertIn("customer_id", request.session)

    def test_products_endpoint_returns_local_catalog(self):
        with patch(
            "app.api.v1.products.list_products_for_api",
            return_value=([{"id": 1, "name": "Galao 20L", "source": "local"}], "local"),
        ):
            response = list_products(include_inactive=False, limit=100, db=self.db)
        payload = json.loads(response.body)

        self.assertTrue(payload["success"])
        self.assertEqual(payload["meta"]["source"], "local")
        self.assertEqual(payload["data"][0]["name"], "Galao 20L")


if __name__ == "__main__":
    unittest.main()
