import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from app.models import AppDevice, AppNotification, AppOrderPushEvent, Customer
from app.routers.app_api import FcmTokenPayload, _notify_order_status_changes, save_fcm_token


class RequestStub:
    def __init__(self, customer_id=None):
        self.session = {}
        if customer_id is not None:
            self.session["customer_id"] = customer_id
        self.headers = {"user-agent": "test-client"}


class OrderDeliveryPushTests(unittest.TestCase):
    def setUp(self):
        reset_database()
        self.db = get_session()

    def tearDown(self):
        self.db.close()

    def create_customer_with_device(self):
        customer = Customer(
            name="Cliente Teste",
            phone="17999990000",
            pin_hash="hash",
            referral_code="TESTE1",
            card_token="token-teste-1",
        )
        self.db.add(customer)
        self.db.commit()

        device = AppDevice(
            device_id="android-1",
            customer_id=customer.id,
            platform="android",
            notification_permission="granted",
            fcm_token="fcm-token-1",
        )
        self.db.add(device)
        self.db.commit()
        return customer, device

    def test_order_status_pushes_are_sent_once_per_status(self):
        customer, _ = self.create_customer_with_device()
        orders = [
            {"client_order_id": "APP-20260918-140522", "grj_order_id": 148200, "app_status": "accepted"},
            {
                "client_order_id": "APP-20260918-140522",
                "grj_order_id": 148200,
                "app_status": "out_for_delivery",
                "delivery_driver_name": "Gilberto",
            },
            {"client_order_id": "APP-20260918-140522", "grj_order_id": 148200, "app_status": "done"},
        ]

        with patch("app.routers.app_api.send_fcm", return_value=True) as send_fcm:
            for order in orders:
                _notify_order_status_changes(self.db, customer.id, [order])
                _notify_order_status_changes(self.db, customer.id, [order])

        self.assertEqual(send_fcm.call_count, 3)
        self.assertEqual(self.db.query(AppNotification).count(), 3)
        self.assertEqual(self.db.query(AppOrderPushEvent).count(), 3)

    def test_fcm_token_without_session_does_not_clear_existing_customer_link(self):
        customer, device = self.create_customer_with_device()

        result = save_fcm_token(
            FcmTokenPayload(device_id=device.device_id, token="new-token", notification_permission="granted"),
            RequestStub(),
            self.db,
        )

        self.db.refresh(device)
        self.assertTrue(result["ok"])
        self.assertEqual(device.customer_id, customer.id)
        self.assertEqual(device.fcm_token, "new-token")


if __name__ == "__main__":
    unittest.main()
