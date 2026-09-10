import unittest

from tests.test_support import reset_database

from app.routers import attendant, public


def fake_request():
    return type(
        "RequestStub",
        (),
        {
            "base_url": "http://testserver/",
            "session": {},
        },
    )()


class SmokeRoutesTests(unittest.TestCase):
    def setUp(self):
        reset_database()

    def test_public_pages_render(self):
        request = fake_request()
        home_response = public.home(request)
        self.assertEqual(home_response.status_code, 307)
        self.assertEqual(home_response.headers["location"], "/app")

        loyalty_response = public.loyalty_page(request)
        self.assertEqual(loyalty_response.status_code, 307)
        self.assertEqual(loyalty_response.headers["location"], "/app?screen=loyalty")

        shop_response = public.shop_page(request)
        self.assertEqual(shop_response.status_code, 307)
        self.assertEqual(shop_response.headers["location"], "/app?screen=store")

        responses = [
            public.app_home(request),
            public.login_page(request),
            public.subscribe_page(request),
            attendant.attendant_login_page(request),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200)

    def test_cep_endpoint_rejects_invalid_input(self):
        response = public.api_cep("123")
        self.assertEqual(response.status_code, 400)

    def test_reverse_location_endpoint_rejects_invalid_input(self):
        response = public.api_reverse_location("abc", "def")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
