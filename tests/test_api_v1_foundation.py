import json
import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from app.api.v1.auth import forgot_password, login, reset_password, verify_reset_code
from app.models import PasswordResetToken
from app.api.v1.products import list_products
from app.schemas.auth import (
    CustomerLoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyResetCodeRequest,
)
from app.services.auth_service import authenticate_customer, create_customer_account
from app.security import verify_password


class RequestStub:
    def __init__(self):
        self.session = {}
        self.headers = {}
        self.client = None


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
            complement="Apto 12 - Torre B",
            neighborhood="Centro",
        )

        authenticated = authenticate_customer(self.db, phone="17999990000", password="1234")

        self.assertEqual(authenticated.id, customer.id)
        self.assertEqual(customer.complement, "Apto 12 - Torre B")

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

    def test_password_recovery_sends_code_only_to_registered_phone(self):
        create_customer_account(
            self.db,
            name="Cliente Reset",
            phone="17999998888",
            password="1234",
            zip_code="15500000",
        )
        request = RequestStub()

        with patch("app.services.account_recovery.secrets.choice", side_effect=list("123456")), patch(
            "app.api.v1.auth.send_password_reset_code_whatsapp",
            return_value=(True, "sent"),
        ) as send_mock:
            response = forgot_password(
                ForgotPasswordRequest(phone="+55 17 99999-8888"),
                request,
                self.db,
            )
        payload = json.loads(response.body)
        token_row = self.db.query(PasswordResetToken).one()

        self.assertTrue(payload["success"])
        self.assertNotIn("123456", response.body.decode("utf-8"))
        send_mock.assert_called_once_with(to_phone="17999998888", code="123456")
        self.assertEqual(token_row.destination_phone, "17999998888")

    def test_password_recovery_unknown_phone_returns_generic_without_sending(self):
        request = RequestStub()

        with patch("app.api.v1.auth.send_password_reset_code_whatsapp") as send_mock:
            response = forgot_password(
                ForgotPasswordRequest(phone="(17) 98888-7777"),
                request,
                self.db,
            )
        payload = json.loads(response.body)

        self.assertTrue(payload["success"])
        send_mock.assert_not_called()
        self.assertEqual(self.db.query(PasswordResetToken).count(), 0)

    def test_password_recovery_verifies_code_and_resets_password_once(self):
        customer = create_customer_account(
            self.db,
            name="Cliente Troca",
            phone="17999997777",
            password="1234",
            zip_code="15500000",
        )
        request = RequestStub()
        with patch("app.services.account_recovery.secrets.choice", side_effect=list("654321")), patch(
            "app.api.v1.auth.send_password_reset_code_whatsapp",
            return_value=(True, "sent"),
        ):
            forgot_password(ForgotPasswordRequest(phone="17 99999-7777"), request, self.db)

        verify_response = verify_reset_code(
            VerifyResetCodeRequest(phone="+55 17 99999-7777", code="654321"),
            self.db,
        )
        verify_payload = json.loads(verify_response.body)
        reset_token = verify_payload["data"]["resetToken"]

        reset_response = reset_password(
            ResetPasswordRequest(resetToken=reset_token, newPassword="4321"),
            self.db,
        )
        reused_response = reset_password(
            ResetPasswordRequest(resetToken=reset_token, newPassword="1111"),
            self.db,
        )
        self.db.refresh(customer)

        self.assertEqual(reset_response.status_code, 200)
        self.assertEqual(reused_response.status_code, 400)
        self.assertTrue(verify_password("4321", customer.pin_hash))


if __name__ == "__main__":
    unittest.main()
