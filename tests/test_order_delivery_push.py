import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from app.models import AppDevice, AppNotification, AppOrderPushEvent, Customer
from app.routers.app_api import _notify_out_for_delivery


class OrderDeliveryPushTests(unittest.TestCase):
    def setUp(self):
        reset_database()
        self.db = get_session()

    def tearDown(self):
        self.db.close()

    def test_out_for_delivery_push_is_sent_once_per_order(self):
        customer = Customer(
            name="Cliente Teste",
            phone="17999990000",
            pin_hash="hash",
            referral_code="TESTE1",
            card_token="token-teste-1",
        )
        self.db.add(customer)
        self.db.commit()

        self.db.add(
            AppDevice(
                device_id="android-1",
                customer_id=customer.id,
                platform="android",
                notification_permission="granted",
                fcm_token="fcm-token-1",
            )
        )
        self.db.commit()

        order = {
            "client_order_id": "APP-20260918-140522",
            "grj_order_id": 148200,
            "app_status": "out_for_delivery",
            "delivery_driver_name": "Gilberto",
        }

        with patch("app.routers.app_api.send_fcm", return_value=True) as send_fcm:
            _notify_out_for_delivery(self.db, customer.id, [order])
            _notify_out_for_delivery(self.db, customer.id, [order])

        self.assertEqual(send_fcm.call_count, 1)
        self.assertEqual(self.db.query(AppNotification).count(), 1)
        self.assertEqual(self.db.query(AppOrderPushEvent).count(), 1)


if __name__ == "__main__":
    unittest.main()
