import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["GARAGELOG_DB"] = _tmp.name

import app as app_module  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")


def _today(offset=0):
    return (datetime.now(JST) + timedelta(days=offset)).strftime("%Y-%m-%d")


class GarageLogTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM records")
            conn.commit()

    def _add(self, **kw):
        data = {
            "rdate": "2026-10-01", "vehicle": "バイク", "category": "給油",
            "odometer": "", "liters": "", "amount": "", "memo": "", "due_date": "",
        }
        data.update(kw)
        return self.client.post("/add", data=data)

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_ok(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("うちのガレージ記録", res.get_data(as_text=True))

    def test_fuel_economy(self):
        self._add(rdate="2026-10-01", odometer="10000", liters="10")
        self._add(rdate="2026-10-15", odometer="10500", liters="10")
        body = self.client.get("/").get_data(as_text=True)
        # (10500-10000)/10 = 50.0 km/L が2件目の行に出る
        self.assertIn("50.0 km/L", body)

    def test_fuel_economy_per_vehicle(self):
        self._add(vehicle="バイク", rdate="2026-10-01", odometer="10000", liters="10")
        self._add(vehicle="クルマ", rdate="2026-10-02", odometer="50000", liters="30")
        self._add(vehicle="バイク", rdate="2026-10-15", odometer="10300", liters="10")
        body = self.client.get("/").get_data(as_text=True)
        # バイク: (10300-10000)/10 = 30.0 km/L。クルマは前回がないので燃費なし
        self.assertIn("30.0 km/L", body)
        self.assertNotIn("130.0 km/L", body)

    def test_due_list_and_overdue(self):
        self._add(category="車検・点検", rdate=_today(-10), due_date=_today(7), memo="車検")
        self._add(category="整備", rdate=_today(-20), due_date=_today(-1), memo="オイル交換")
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("期限が近いもの", body)
        self.assertIn("車検", body)
        self.assertIn("期限切れ", body)

    def test_add_and_delete(self):
        self._add(category="整備", memo="タイヤ交換", amount="12000")
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("タイヤ交換", body)
        with app_module.app.app_context():
            conn = app_module.get_db()
            rid = conn.execute("SELECT id FROM records").fetchone()["id"]
        res = self.client.post(f"/delete/{rid}")
        self.assertEqual(res.status_code, 302)
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("タイヤ交換", body)


if __name__ == "__main__":
    unittest.main()
