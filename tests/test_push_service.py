import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import AppDevice
from app.services import push


class PushServiceTests(unittest.TestCase):
    def test_fcm_uses_data_only_payload_for_background_delivery(self):
        captured = {}

        class FakeNotification:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeAndroidConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeMessage:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake_messaging = SimpleNamespace(
            AndroidConfig=FakeAndroidConfig,
            AndroidNotification=FakeNotification,
            Message=FakeMessage,
            send=lambda message: "message-id",
        )
        device = AppDevice(device_id="android-test", fcm_token="token-test")

        with patch("app.services.push.ensure_firebase_app", return_value=True), patch.object(push, "messaging", fake_messaging):
            sent = push.send_fcm(device, "Central Aguas", "Pedido aceito.", "/app", 123)

        self.assertTrue(sent)
        self.assertNotIn("notification", captured)
        self.assertEqual(captured["data"]["title"], "Central Aguas")
        self.assertEqual(captured["data"]["body"], "Pedido aceito.")
        self.assertEqual(captured["data"]["notification_id"], "123")
        self.assertEqual(captured["android"].kwargs["priority"], "high")


if __name__ == "__main__":
    unittest.main()
