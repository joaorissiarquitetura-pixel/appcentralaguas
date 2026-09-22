import json
import unittest

from test_support import get_session, reset_database

from app.models import Customer, CustomerHouseStock
from app.routers.public import _house_stock_note, _parse_house_stock_payload, _save_customer_house_stock


class AppOrderPayloadTests(unittest.TestCase):
    def setUp(self):
        reset_database()

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

    def test_house_stock_snapshot_is_saved_for_customer(self):
        db = get_session()
        try:
            customer = Customer(
                name="Joao Rissi",
                phone="17999999999",
                pin_hash="hash",
                referral_code="ABC123",
                card_token="token-123",
            )
            db.add(customer)
            db.commit()

            stock = _parse_house_stock_payload(json.dumps({
                "calibrated": True,
                "total": 4,
                "full": 2,
                "in_use": 1,
                "oldest_validity": "12/2026",
            }))
            _save_customer_house_stock(db, customer.id, stock, "APP-TESTE")
            db.commit()

            saved = db.query(CustomerHouseStock).filter_by(customer_id=customer.id).one()
            self.assertEqual(saved.total, 4)
            self.assertEqual(saved.full, 2)
            self.assertEqual(saved.in_use, 1)
            self.assertEqual(saved.empty, 1)
            self.assertEqual(saved.oldest_validity, "12/2026")
            self.assertEqual(saved.client_order_id, "APP-TESTE")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
