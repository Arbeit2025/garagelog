"""うちのガレージ記録 garagelog

車・バイクの給油／整備／車検・点検などを1か所に記録する小さなツール。
給油記録からは前回給油との走行距離と給油量で燃費（km/L）を計算し、
期限（due date）のある記録は「期限が近いもの」として一覧する。
単一ファイル Flask + SQLite。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("GARAGELOG_DB", os.path.join(os.path.dirname(__file__), "garagelog.db"))

CATEGORIES = ["給油", "整備", "車検・点検", "その他"]


def today_str():
    return datetime.now(JST).strftime("%Y-%m-%d")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rdate TEXT NOT NULL,
            vehicle TEXT NOT NULL,
            category TEXT NOT NULL,
            odometer INTEGER,
            liters REAL,
            amount INTEGER,
            memo TEXT NOT NULL DEFAULT '',
            due_date TEXT
        );
        """
    )
    db.commit()
    db.close()


def with_economy(rows):
    """給油記録に前回給油（同一車両）からの燃費 km/L を付ける。

    rows は日付・id の昇順で渡すこと。戻り値は dict のリスト。
    """
    out = []
    prev_fuel = {}  # vehicle -> (odometer)
    for r in rows:
        d = dict(r)
        d["economy"] = None
        if r["category"] == "給油" and r["odometer"] is not None and r["liters"]:
            prev_odo = prev_fuel.get(r["vehicle"])
            if prev_odo is not None and r["odometer"] > prev_odo:
                d["economy"] = round((r["odometer"] - prev_odo) / r["liters"], 1)
            prev_fuel[r["vehicle"]] = r["odometer"]
        out.append(d)
    return out


PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>うちのガレージ記録</title>
<style>body{font-family:sans-serif;max-width:760px;margin:2em auto;padding:0 1em}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ccc;padding:.3em .5em;text-align:left}
.overdue{color:#b00020;font-weight:bold}.duebox{background:#fff8e1;border:1px solid #d9b84a;padding:.5em 1em;border-radius:8px}
input,select,textarea{margin:.2em}</style>
</head><body>
<h1>うちのガレージ記録</h1>
<p>車・バイクの給油・整備・車検などを記録します。給油を続けると燃費（km/L）が自動で計算されます。</p>

<h2>記録を追加</h2>
<form method="post" action="{{ url_for('add') }}">
  <label>日付 <input type="date" name="rdate" value="{{ today }}" required></label>
  <label>車両名 <input type="text" name="vehicle" placeholder="例：愛車のバイク" required></label>
  <label>区分 <select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select></label><br>
  <label>走行距離(km) <input type="number" name="odometer" min="0" placeholder="任意"></label>
  <label>給油量(L) <input type="number" name="liters" step="0.01" min="0" placeholder="給油時"></label>
  <label>金額(円) <input type="number" name="amount" min="0" placeholder="任意"></label><br>
  <label>メモ <input type="text" name="memo" placeholder="任意"></label>
  <label>期限 <input type="date" name="due_date"></label>
  <button type="submit">追加</button>
</form>

<h2>期限が近いもの</h2>
<div class="duebox">
{% if due_list %}
<ul>
{% for r in due_list %}
<li>{% if r.due_date < today %}<span class="overdue">期限切れ</span> {% endif %}{{ r.due_date }}：{{ r.vehicle }}（{{ r.category }}）{% if r.memo %} - {{ r.memo }}{% endif %}</li>
{% endfor %}
</ul>
{% else %}<p>期限のある記録はまだありません</p>{% endif %}
</div>

<h2>記録一覧</h2>
<table>
<tr><th>日付</th><th>車両</th><th>区分</th><th>走行距離</th><th>給油量</th><th>燃費</th><th>金額</th><th>メモ</th><th>操作</th></tr>
{% for r in records %}
<tr><td>{{ r.rdate }}</td><td>{{ r.vehicle }}</td><td>{{ r.category }}</td>
<td>{% if r.odometer is not none %}{{ r.odometer }} km{% endif %}</td>
<td>{% if r.liters is not none %}{{ r.liters }} L{% endif %}</td>
<td>{% if r.economy is not none %}{{ r.economy }} km/L{% endif %}</td>
<td>{% if r.amount is not none %}{{ r.amount }} 円{% endif %}</td>
<td>{{ r.memo }}</td>
<td><form method="post" action="{{ url_for('delete', rid=r.id) }}" style="display:inline" onsubmit="return confirm('この記録を削除しますか？')"><button type="submit">削除</button></form></td></tr>
{% else %}<tr><td colspan="9">記録はまだありません</td></tr>
{% endfor %}
</table>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    rows = db.execute("SELECT * FROM records ORDER BY rdate ASC, id ASC").fetchall()
    records = list(reversed(with_economy(rows)))
    due_list = db.execute(
        "SELECT * FROM records WHERE due_date IS NOT NULL AND due_date != '' ORDER BY due_date ASC, id ASC"
    ).fetchall()
    return render_template_string(
        PAGE, records=records, due_list=due_list, categories=CATEGORIES, today=today_str()
    )


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def _float_or_none(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


@app.route("/add", methods=["POST"])
def add():
    rdate = (request.form.get("rdate") or "").strip() or today_str()
    vehicle = (request.form.get("vehicle") or "").strip()
    category = request.form.get("category", "その他")
    if category not in CATEGORIES:
        category = "その他"
    due_date = (request.form.get("due_date") or "").strip() or None
    if vehicle:
        db = get_db()
        db.execute(
            "INSERT INTO records(rdate, vehicle, category, odometer, liters, amount, memo, due_date)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rdate, vehicle, category,
                _int_or_none(request.form.get("odometer")),
                _float_or_none(request.form.get("liters")),
                _int_or_none(request.form.get("amount")),
                (request.form.get("memo") or "").strip(),
                due_date,
            ),
        )
        db.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:rid>", methods=["POST"])
def delete(rid):
    db = get_db()
    db.execute("DELETE FROM records WHERE id = ?", (rid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
