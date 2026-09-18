import unittest
from unittest.mock import patch

from tests.test_support import get_session, reset_database

from app.models import AppDevice, Customer
from app.routers.admin import _diagnose_fcm_device


class PushDiagnosticTests(unittest.TestCase):
    def setUp(self):
        reset_database()
        self.db = get_session()

    def tearDown(self):
        self.db.close()

    def create_customer(self):
        customer = Customer(
            name="Cliente Push",
            phone="17999990001",
            pin_hash="hash",
            referral_code="PUSH1",
            card_token="push-token-1",
        )
        self.db.add(customer)
        self.db.commit()
        return customer

    def test_diagnostic_identifies_missing_fcm_token(self):
        customer = self.create_customer()
        device = AppDevice(
            device_id="android-sem-token",
            customer_id=customer.id,
            platform="android",
            notification_permission="granted",
        )
        self.db.add(device)
        self.db.commit()

        with patch("app.routers.admin.fcm_configured", return_value=True):
            result = _diagnose_fcm_device(self.db, device)

        self.assertFalse(result["ok"])
        self.assertEqual(result["probable_reason"], "Celular nao registrou token FCM.")

    def test_diagnostic_points_to_related_fcm_device_for_same_customer(self):
        customer = self.create_customer()
        web_device = AppDevice(
            device_id="ca-webview",
            customer_id=customer.id,
            platform="android-webview",
            notification_permission="unsupported",
        )
        native_device = AppDevice(
            device_id="android-native",
            customer_id=customer.id,
            platform="android",
            notification_permission="granted",
            fcm_token="fcm-token",
        )
        self.db.add_all([web_device, native_device])
        self.db.commit()

        with patch("app.routers.admin.fcm_configured", return_value=True):
            result = _diagnose_fcm_device(self.db, web_device)

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["related_fcm_devices"]), 1)
        self.assertIn("existe outro dispositivo do mesmo cliente com token", result["probable_reason"])

    def test_diagnostic_identifies_unlinked_customer(self):
        device = AppDevice(
            device_id="android-sem-cliente",
            platform="android",
            notification_permission="granted",
            fcm_token="fcm-token",
        )
        self.db.add(device)
        self.db.commit()

        with patch("app.routers.admin.fcm_configured", return_value=True):
            result = _diagnose_fcm_device(self.db, device)

        self.assertFalse(result["ok"])
        self.assertEqual(result["probable_reason"], "Token FCM esta sem cliente vinculado.")

    def test_diagnostic_sends_real_test_when_checks_pass(self):
        customer = self.create_customer()
        device = AppDevice(
            device_id="android-ok",
            customer_id=customer.id,
            platform="android",
            notification_permission="granted",
            fcm_token="fcm-token",
        )
        self.db.add(device)
        self.db.commit()

        with patch("app.routers.admin.fcm_configured", return_value=True), patch(
            "app.routers.admin.send_fcm",
            return_value=True,
        ) as send_fcm:
            result = _diagnose_fcm_device(self.db, device)

        self.assertTrue(result["ok"])
        self.assertTrue(result["send_attempted"])
        self.assertTrue(result["send_ok"])
        self.assertEqual(send_fcm.call_count, 1)


if __name__ == "__main__":
    unittest.main()
