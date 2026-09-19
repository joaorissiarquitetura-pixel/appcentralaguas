import json
import unittest

from app.routers.public import _house_stock_note, _parse_house_stock_payload


class AppOrderPayloadTests(unittest.TestCase):
    def test_house_stock_payload_keeps_customer_bottle_counts(self):
        stock = _parse_house_stock_payload(json.dumps({
            "calibrated": True,
            "total": 4,
            "full": 1,
            "in_use": 1,
            "validities": [
                {"gallon": 1, "month": "12", "year": "2026"},
                {"gallon": 2, "month": "08", "year": "2028"},
            ],
        }))

        self.assertEqual(stock["total"], 4)
        self.assertEqual(stock["full"], 1)
        self.assertEqual(stock["in_use"], 1)
        self.assertEqual(stock["empty"], 2)
        self.assertEqual(stock["validities"][0]["month"], "12")
        self.assertIn("2 vazio(s)", _house_stock_note(stock))

    def test_house_stock_payload_does_not_trust_impossible_counts(self):
        stock = _parse_house_stock_payload(json.dumps({
            "calibrated": True,
            "total": 2,
            "full": 4,
            "in_use": 1,
        }))

        self.assertEqual(stock["total"], 2)
        self.assertEqual(stock["full"], 1)
        self.assertEqual(stock["in_use"], 1)
        self.assertEqual(stock["empty"], 0)


if __name__ == "__main__":
    unittest.main()
