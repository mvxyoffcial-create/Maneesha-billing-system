import os
from datetime import datetime, timedelta
from functools import wraps

import certifi
from bson import ObjectId
from bson.errors import InvalidId
from flask import (Flask, request, redirect, render_template, session,
                   jsonify, url_for, abort)
from jinja2 import DictLoader
from pymongo import MongoClient, ReturnDocument

SHOP = "Maneesha Enterprises"
ADDRESS = "No:25, Katumana, Nuwaraeliya."
PHONE = "072 992 1118"
PASSWORD = "12345678"
TAGLINE = "Hardware & Building Materials"
FOOTER_NOTE = "Thank You Come Again !"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret")

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
_kw = {"tlsCAFile": certifi.where()} if MONGO_URI.startswith("mongodb+srv") else {}
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, **_kw)
db = client[os.getenv("MONGODB_DB", "maneesha")]
try:
    db.items.create_index("name")
    db.items.create_index("code")
    db.bills.create_index("created")
except Exception as e:  # database unreachable at start-up; requests will show the error
    print("MongoDB index setup skipped:", e)


class Doc(dict):
    """Dict with attribute access so templates can use i.name, b.total, etc."""

    def __getattr__(self, k):
        if k == "id":
            v = self.get("_id")
            return v if isinstance(v, int) else str(v)
        v = self.get(k)
        if isinstance(v, list):
            return [Doc(x) if isinstance(x, dict) else x for x in v]
        if isinstance(v, dict):
            return Doc(v)
        return v


def now():  # Sri Lanka time (UTC+5:30)
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def oid(x):
    try:
        return ObjectId(x)
    except (InvalidId, TypeError):
        abort(404)


def next_bill_no():
    r = db.counters.find_one_and_update(
        {"_id": "bill"}, {"$inc": {"seq": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER)
    return r["seq"]


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if PASSWORD and not session.get("ok"):
            return redirect(url_for("login"))
        return f(*a, **k)
    return w


@app.template_filter("money")
def money(v):
    return f"{(v or 0):,.2f}"


@app.template_filter("num")
def num(v):
    return f"{(v or 0):g}"


@app.context_processor
def inject():
    return dict(shop=SHOP, address=ADDRESS, phone=PHONE, tagline=TAGLINE,
                footer_note=FOOTER_NOTE)


@app.route("/health")
def health():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        if request.form.get("password") == PASSWORD:
            session["ok"] = True
            return redirect("/")
        err = "Wrong password"
    return render_template("login.html", err=err)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return redirect(url_for("bill_form"))


@app.route("/bill/new")
@login_required
def bill_form():
    items = [dict(id=str(i["_id"]), code=i.get("code", ""), name=i["name"],
                  unit=i.get("unit", ""), sell=i.get("sell", 0), qty=i.get("qty", 0))
             for i in db.items.find().sort("name", 1)]
    return render_template("bill_form.html", items=items)


@app.post("/bill/new")
@login_required
def bill_save():
    d = request.get_json() or {}
    lines = d.get("lines", [])
    if not lines:
        return jsonify(error="Add items first"), 400
    done, out, total = [], [], 0.0

    def rollback():
        for o, q in done:
            db.items.update_one({"_id": o}, {"$inc": {"qty": q}})

    for l in lines:
        try:
            o, q, p = ObjectId(l["id"]), float(l["qty"]), float(l["price"])
        except Exception:
            rollback()
            return jsonify(error="Invalid item line"), 400
        if q <= 0:
            rollback()
            return jsonify(error="Quantity must be more than 0"), 400
        it = db.items.find_one_and_update(  # atomic: only if enough stock
            {"_id": o, "qty": {"$gte": q}}, {"$inc": {"qty": -q}},
            return_document=ReturnDocument.BEFORE)
        if not it:
            rollback()
            cur = db.items.find_one({"_id": o})
            msg = (f"Only {cur.get('qty', 0):g} of {cur['name']} in stock"
                   if cur else "Item not found")
            return jsonify(error=msg), 400
        done.append((o, q))
        out.append(dict(item_id=str(o), name=it["name"], price=p,
                        cost=it.get("buy", 0), qty=q))
        total += p * q
    bill = dict(_id=next_bill_no(), created=now(),
                customer=(d.get("customer") or "").strip(),
                total=total, paid=float(d.get("paid") or 0), lines=out)
    db.bills.insert_one(bill)
    return jsonify(url=url_for("bill_print", bid=bill["_id"]))


@app.route("/bill/<int:bid>")
@login_required
def bill_print(bid):
    raw = db.bills.find_one({"_id": bid})
    if not raw:
        abort(404)
    b = Doc(raw)
    sub = sum(l["price"] * l["qty"] for l in raw["lines"])
    return render_template("print.html", b=b, sub=sub)


@app.route("/bills")
@login_required
def bills():
    rows = [Doc(b) for b in db.bills.find().sort("_id", -1).limit(100)]
    return render_template("bills.html", rows=rows)


def _fields(f):
    return dict(code=f.get("code", "").strip(), name=f["name"].strip(),
                category=f.get("category", "").strip(),
                unit=f.get("unit", "").strip() or "pcs",
                buy=float(f.get("buy") or 0), sell=float(f.get("sell") or 0),
                low=float(f.get("low") or 0))


@app.route("/items", methods=["GET", "POST"])
@login_required
def items():
    if request.method == "POST":
        doc = _fields(request.form)
        doc["qty"] = float(request.form.get("qty") or 0)
        db.items.insert_one(doc)
        return redirect(url_for("items"))
    rows = [Doc(i) for i in db.items.find().sort("name", 1)]
    value = sum(i["buy"] * i["qty"] for i in rows)
    nlow = sum(1 for i in rows if i["qty"] <= i["low"])
    return render_template("items.html", rows=rows, value=value, nlow=nlow)


@app.route("/items/<iid>/edit", methods=["GET", "POST"])
@login_required
def item_edit(iid):
    o = oid(iid)
    raw = db.items.find_one({"_id": o})
    if not raw:
        abort(404)
    if request.method == "POST":
        f = request.form
        doc = _fields(f)
        doc["qty"] = float(f.get("qty") or 0) + float(f.get("add") or 0)
        db.items.update_one({"_id": o}, {"$set": doc})
        return redirect(url_for("items"))
    return render_template("item_edit.html", i=Doc(raw))


@app.post("/items/<iid>/delete")
@login_required
def item_delete(iid):
    db.items.delete_one({"_id": oid(iid)})
    return redirect(url_for("items"))


@app.post("/bill/<int:bid>/delete")
@login_required
def bill_delete(bid):
    b = db.bills.find_one({"_id": bid})
    if b:
        for l in b["lines"]:  # void bill: put the stock back
            try:
                db.items.update_one({"_id": ObjectId(l["item_id"])},
                                    {"$inc": {"qty": l["qty"]}})
            except Exception:
                pass
        db.bills.delete_one({"_id": bid})
    return redirect(url_for("bills"))


@app.route("/report")
@login_required
def report():
    try:
        day = datetime.strptime(request.args.get("d", ""), "%Y-%m-%d").date()
    except ValueError:
        day = now().date()
    start = datetime.combine(day, datetime.min.time())
    rows = [Doc(b) for b in db.bills.find(
        {"created": {"$gte": start, "$lt": start + timedelta(days=1)}}).sort("_id", 1)]
    sales = sum(b["total"] for b in rows)
    profit = sum((l["price"] - l["cost"]) * l["qty"] for b in rows for l in b["lines"])
    low = [Doc(i) for i in db.items.find(
        {"$expr": {"$lte": ["$qty", "$low"]}}).sort("qty", 1)]
    return render_template("report.html", day=day, rows=rows, sales=sales,
                           profit=profit, low=low)


BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ shop }}</title><style>
:root{--ink:#1f2933;--bg:#f3f1ec;--line:#d6d2c8;--accent:#b4531a;--card:#fff}
*{box-sizing:border-box}body{margin:0;font:15px/1.4 system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--ink);color:#fff;padding:10px 14px}
header b{font-size:17px}nav{display:flex;gap:4px;flex-wrap:wrap;margin-top:8px}
nav a{color:#fff;text-decoration:none;padding:6px 12px;border-radius:6px;background:#3a4753}
nav a:hover{background:var(--accent)}main{padding:14px;max-width:900px;margin:auto}
h2{margin:4px 0 12px}table{width:100%;border-collapse:collapse;background:var(--card)}
label{display:block;font-size:13px;color:#6b7280}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
.wrap{overflow-x:auto}input{font:inherit;padding:7px;border:1px solid var(--line);border-radius:6px;width:100%;min-width:60px}
button,.btn{font:inherit;background:var(--accent);color:#fff;border:0;border-radius:6px;padding:9px 14px;cursor:pointer;text-decoration:none;display:inline-block}
button.alt{background:#6b7280}.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.row>*{flex:1;min-width:110px}.card{background:var(--card);padding:12px;border-radius:8px;margin-bottom:12px}
.low{background:#fde8d8}.hit{padding:9px;border-bottom:1px solid var(--line);cursor:pointer;background:#fff}
.hit:hover{background:#fde8d8}.r{text-align:right}.err{color:#b91c1c}.big{font-size:22px;font-weight:700}footer{text-align:center;color:#6b7280;font-size:13px;padding:16px 14px 24px}
</style></head><body>
<header><b>{{ shop }}</b>
{% if request.endpoint != 'login' %}<nav><a href="/bill/new">New bill</a><a href="/items">Items</a>
<a href="/bills">Bills</a><a href="/report">Report</a><a href="/logout">Log out</a></nav>{% endif %}</header>
<main>{% block body %}{% endblock %}</main>
<footer>Developed and managed by Spidy</footer></body></html>"""

LOGIN = """{% extends "base.html" %}{% block body %}
<form method="post" class="card"><h2>Log in</h2>
<p><input type="password" name="password" placeholder="Password" autofocus></p>
<p class="err">{{ err }}</p><button>Log in</button></form>{% endblock %}"""

BILL_FORM = """{% extends "base.html" %}{% block body %}
<h2>New bill</h2>
<div class="card"><input id="q" placeholder="Search item name or scan barcode…" autocomplete="off"><div id="res"></div></div>
<div class="card wrap"><table><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th class="r">Amount</th><th></th></tr></thead>
<tbody id="cart"><tr><td colspan="5">Search and tap an item to add it.</td></tr></tbody></table></div>
<div class="card"><div class="row"><input id="cust" placeholder="Customer name (optional)">
<input id="paid" type="number" min="0" step="any" placeholder="Cash received (Rs)"></div>
<p>Total: <span class="big" id="tot">0.00</span></p>
<p class="err" id="err"></p><button id="save">Save and print</button></div>
<script>
const items={{ items|tojson }};let cart=[];
const q=document.getElementById('q'),res=document.getElementById('res'),body=document.getElementById('cart');
const f=n=>n.toLocaleString('en-LK',{minimumFractionDigits:2,maximumFractionDigits:2});
let hits=[];
q.oninput=()=>{const s=q.value.toLowerCase().trim();res.innerHTML='';hits=[];if(!s)return;
 hits=items.filter(i=>i.name.toLowerCase().includes(s)||(i.code&&i.code.toLowerCase().includes(s))).slice(0,8);
 hits.forEach(i=>{const d=document.createElement('div');d.className='hit';
  d.textContent=(i.code?i.code+' - ':'')+i.name+' - Rs '+f(i.sell)+' ('+i.qty+' '+i.unit+')';
  d.onclick=()=>pick(i);res.appendChild(d)})};
q.onkeydown=e=>{if(e.key==='Enter'&&hits.length){e.preventDefault();pick(hits[0])}};
function pick(i){add(i);q.value='';res.innerHTML='';hits=[];q.focus()}
function add(i){const l=cart.find(c=>c.id==i.id);if(l)l.qty++;else cart.push({id:i.id,name:i.name,price:i.sell,qty:1});draw()}
function draw(){body.innerHTML='';if(!cart.length){body.innerHTML='<tr><td colspan="5">Search and tap an item to add it.</td></tr>'}
 cart.forEach((l,k)=>{const tr=document.createElement('tr');
  tr.innerHTML='<td>'+l.name+'</td><td><input type="number" min="0" step="any" value="'+l.qty+'"></td><td><input type="number" min="0" step="any" value="'+l.price+'"></td><td class="r"></td><td><button class="alt">✕</button></td>';
  const [a,b]=tr.querySelectorAll('input');
  a.oninput=()=>{l.qty=+a.value;calc()};b.oninput=()=>{l.price=+b.value;calc()};
  tr.querySelector('button').onclick=()=>{cart.splice(k,1);draw()};body.appendChild(tr)});calc()}
function calc(){let s=0;[...body.rows].forEach((tr,k)=>{if(!cart[k])return;const a=cart[k].qty*cart[k].price;s+=a;tr.cells[3].textContent=f(a)});
 document.getElementById('tot').textContent=f(s)}
document.getElementById('save').onclick=async()=>{const e=document.getElementById('err');e.textContent='';
 const r=await fetch('/bill/new',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({lines:cart,customer:document.getElementById('cust').value,paid:document.getElementById('paid').value})});
 const j=await r.json();if(!r.ok){e.textContent=j.error;return}location=j.url};
</script>{% endblock %}"""

ITEMS = """{% extends "base.html" %}{% block body %}
<h2>Items and stock</h2>
<p>{{ rows|length }} items &nbsp;|&nbsp; Stock value (cost): Rs {{ value|money }} &nbsp;|&nbsp; Low stock: <b>{{ nlow }}</b></p>
<form method="post" class="card"><b>Add new item</b><div class="row" style="margin-top:8px">
<input name="code" placeholder="Code / barcode"><input name="name" placeholder="Item name" required>
<input name="category" placeholder="Category"><input name="unit" placeholder="Unit (pcs, kg, m)"></div>
<div class="row"><input name="buy" type="number" step="any" placeholder="Buying price">
<input name="sell" type="number" step="any" placeholder="Selling price">
<input name="qty" type="number" step="any" placeholder="Opening stock"><input name="low" type="number" step="any" placeholder="Low alert at"></div>
<button>Add item</button></form>
<div class="card"><input id="s" placeholder="Search by name, code or category…"></div>
<div class="card wrap"><table id="t"><thead><tr><th>Code</th><th>Name</th><th>Category</th><th class="r">Buy</th><th class="r">Sell</th><th class="r">Stock</th><th></th></tr></thead>
{% for i in rows %}<tr class="{{ 'low' if i.qty <= i.low }}" data-s="{{ (i.code ~ ' ' ~ i.name ~ ' ' ~ i.category)|lower }}">
<td>{{ i.code }}</td><td>{{ i.name }}</td><td>{{ i.category }}</td><td class="r">{{ i.buy|money }}</td><td class="r">{{ i.sell|money }}</td>
<td class="r">{{ i.qty|num }} {{ i.unit }}</td>
<td style="white-space:nowrap"><a class="btn" href="/items/{{ i.id }}/edit">Edit</a>
<form method="post" action="/items/{{ i.id }}/delete" style="display:inline" onsubmit="return confirm('Delete {{ i.name|e }}?')"><button class="alt">Delete</button></form></td></tr>
{% else %}<tr><td colspan="7">No items yet. Add your first item above.</td></tr>{% endfor %}</table></div>
<script>document.getElementById('s').oninput=e=>{const v=e.target.value.toLowerCase();
document.querySelectorAll('#t tr[data-s]').forEach(r=>r.style.display=r.dataset.s.includes(v)?'':'none')}</script>{% endblock %}"""

ITEM_EDIT = """{% extends "base.html" %}{% block body %}
<h2>Edit item</h2>
<form method="post" class="card"><div class="row"><input name="code" value="{{ i.code }}" placeholder="Code / barcode">
<input name="name" value="{{ i.name }}" required><input name="category" value="{{ i.category }}" placeholder="Category">
<input name="unit" value="{{ i.unit }}" placeholder="Unit"></div>
<div class="row"><label>Buying price<input name="buy" type="number" step="any" value="{{ i.buy|num }}"></label>
<label>Selling price<input name="sell" type="number" step="any" value="{{ i.sell|num }}"></label>
<label>Low alert at<input name="low" type="number" step="any" value="{{ i.low|num }}"></label></div>
<div class="row"><label>Stock now<input name="qty" type="number" step="any" value="{{ i.qty|num }}"></label>
<label>Add stock (+)<input name="add" type="number" step="any" placeholder="0"></label></div>
<button>Save changes</button> <a class="btn alt" href="/items">Cancel</a></form>{% endblock %}"""

BILLS = """{% extends "base.html" %}{% block body %}<h2>Recent bills</h2>
<div class="card wrap"><table><tr><th>No.</th><th>Date</th><th>Customer</th><th class="r">Total</th><th></th></tr>
{% for b in rows %}<tr><td>{{ b.id }}</td><td>{{ b.created.strftime('%Y-%m-%d %H:%M') }}</td><td>{{ b.customer }}</td>
<td class="r">{{ b.total|money }}</td><td style="white-space:nowrap"><a class="btn" href="/bill/{{ b.id }}">Reprint</a>
<form method="post" action="/bill/{{ b.id }}/delete" style="display:inline" onsubmit="return confirm('Void bill {{ b.id }}? Stock will be put back.')"><button class="alt">Void</button></form></td></tr>
{% else %}<tr><td colspan="5">No bills yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

REPORT = """{% extends "base.html" %}{% block body %}<h2>Daily report</h2>
<form class="card row"><input type="date" name="d" value="{{ day }}"><button>Show</button></form>
<div class="card"><p>Bills: <b>{{ rows|length }}</b></p><p>Sales: <span class="big">Rs {{ sales|money }}</span></p>
<p>Profit: <b>Rs {{ profit|money }}</b></p></div>
<div class="card wrap"><table><tr><th>No.</th><th>Time</th><th>Customer</th><th class="r">Total</th></tr>
{% for b in rows %}<tr><td><a href="/bill/{{ b.id }}">{{ b.id }}</a></td><td>{{ b.created.strftime('%H:%M') }}</td><td>{{ b.customer }}</td><td class="r">{{ b.total|money }}</td></tr>
{% else %}<tr><td colspan="4">No bills on this day.</td></tr>{% endfor %}</table></div>
<h2>Low stock</h2><div class="card wrap"><table><tr><th>Item</th><th>In stock</th></tr>
{% for i in low %}<tr class="low"><td>{{ i.name }}</td><td>{{ i.qty|num }}</td></tr>
{% else %}<tr><td colspan="2">All items are above their alert level.</td></tr>{% endfor %}</table></div>{% endblock %}"""

PRINT = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{% set w80 = request.args.get('w') == '80' %}
<title>Bill {{ b.id }}</title><style>
@page{size:{{ 80 if w80 else 58 }}mm auto;margin:0}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font:11px/1.45 'Courier New',monospace;color:#000;width:{{ 72 if w80 else 48 }}mm;margin:0 auto;padding:3mm 0}
.brand{background:#000;color:#fff;text-align:center;padding:7px 4px;border-radius:4px;font:700 {{ 20 if w80 else 17 }}px/1.15 Arial,Helvetica,sans-serif;letter-spacing:.5px}
.tag{text-align:center;font:700 10px Arial,Helvetica,sans-serif;letter-spacing:.8px;margin:5px 0 2px}
.addr{text-align:center;font-size:10px;line-height:1.35}
hr{border:0;border-top:1px dashed #000;margin:6px 0}hr.s{border-top:1px solid #000}hr.d{border-top:3px double #000}
.l{display:flex;justify-content:space-between;gap:6px}
.hd{font:700 10px Arial,Helvetica,sans-serif;letter-spacing:.6px;border-bottom:1px solid #000;padding-bottom:2px;margin-bottom:4px}
.nm{font-weight:700}.it{padding-left:3mm;margin-bottom:3px}.sm{font-size:10px}
.box{margin:5px 0;padding:2px 0;font:700 16px Arial,Helvetica,sans-serif}
.b{font-weight:700}.c{text-align:center}.ty{text-align:center;font:700 11px Arial,Helvetica,sans-serif;letter-spacing:.5px}
.bar{text-align:center;margin-bottom:10px}.bar a,.bar button{font:14px sans-serif;padding:8px 14px;margin:2px}
@media print{.bar{display:none}}
</style></head><body>
<div class="bar"><button onclick="window.print()">Print</button><a href="/bill/new">New bill</a></div>
<div class="brand">{{ shop }}</div>
{% if tagline %}<div class="tag">{{ tagline }}</div>{% endif %}
<div class="addr">{{ address }}{% if phone %}<br>TEL: {{ phone }}{% endif %}</div><hr class="d">
<div class="l"><span>Bill No</span><span class="b">#{{ '%04d' % b.id }}</span></div>
<div class="l"><span>Date</span><span>{{ b.created.strftime('%Y-%m-%d') }}</span></div>
<div class="l"><span>Time</span><span>{{ b.created.strftime('%H:%M') }}</span></div>
{% if b.customer %}<div class="l"><span>Customer</span><span>{{ b.customer }}</span></div>{% endif %}<hr class="d">
<div class="l hd"><span>ITEM</span><span>AMOUNT (Rs)</span></div>
{% for l in b.lines %}<div class="nm">{{ loop.index }}. {{ l.name }}</div>
<div class="l it"><span>{{ l.qty|num }} x {{ l.price|money }}</span><span>{{ (l.qty*l.price)|money }}</span></div>{% endfor %}<hr>
<div class="l sm"><span>Items: {{ b.lines|length }}</span><span>Total qty: {{ b.lines|sum(attribute='qty')|num }}</span></div>
<hr class="s">
<div class="box l"><span>TOTAL</span><span>Rs {{ b.total|money }}</span></div><hr class="s">
{% if b.paid %}<div class="l"><span>Cash</span><span>{{ b.paid|money }}</span></div>
<div class="l b"><span>Change</span><span>{{ (b.paid - b.total)|money }}</span></div>{% endif %}
<hr class="d">
<div class="ty">Thank you for your purchase!</div><div class="c sm">Please visit us again</div>
{% if footer_note %}<div class="c sm" style="margin-top:3px">{{ footer_note }}</div>{% endif %}
<script>if(location.search.indexOf('p=0')<0&&document.referrer.indexOf('/bill/new')>-1)window.print()</script>
</body></html>"""

app.jinja_loader = DictLoader({
    "base.html": BASE, "login.html": LOGIN, "bill_form.html": BILL_FORM,
    "items.html": ITEMS, "item_edit.html": ITEM_EDIT, "bills.html": BILLS, "report.html": REPORT,
    "print.html": PRINT,
})

if __name__ == "__main__":
    app.run(debug=True)
