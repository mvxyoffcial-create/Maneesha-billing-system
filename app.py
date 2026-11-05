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


def low_count():
    try:
        return db.items.count_documents({"$expr": {"$lte": ["$qty", "$low"]}})
    except Exception:
        return 0


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
                footer_note=FOOTER_NOTE, low_count=low_count)


@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")


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
                  unit=i.get("unit", ""), category=i.get("category", ""),
                  sell=i.get("sell", 0), qty=i.get("qty", 0), low=i.get("low", 0))
             for i in db.items.find().sort("name", 1)]
    return render_template("bill_form.html", items=items)


@app.post("/bill/new")
@login_required
def bill_save():
    d = request.get_json() or {}
    lines = d.get("lines", [])
    if not lines:
        return jsonify(error="Add items first"), 400
    done, out, subtotal = [], [], 0.0

    def rollback():
        for o, q in done:
            db.items.update_one({"_id": o}, {"$inc": {"qty": q}})

    for l in lines:
        try:
            o, q, p = ObjectId(l["id"]), float(l["qty"]), float(l["price"])
        except Exception:
            rollback()
            return jsonify(error="Invalid item line"), 400
        amt = l.get("amount")
        try:
            amt = float(amt) if amt not in (None, "") else p * q
        except (TypeError, ValueError):
            amt = p * q
        if q <= 0 or amt < 0 or p < 0:
            rollback()
            return jsonify(error="Quantity must be more than 0 and amounts cannot be negative"), 400
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
        out.append(dict(item_id=str(o), name=it["name"], price=p, amount=amt,
                        cost=it.get("buy", 0), qty=q))
        subtotal += amt
    try:
        discount = float(d.get("discount") or 0)
    except (TypeError, ValueError):
        discount = 0.0
    discount = round(min(max(discount, 0.0), subtotal), 2)
    total = round(subtotal - discount, 2)
    bill = dict(_id=next_bill_no(), created=now(),
                customer=(d.get("customer") or "").strip(),
                subtotal=round(subtotal, 2), discount=discount,
                total=total, paid=float(d.get("paid") or 0), lines=out)
    db.bills.insert_one(bill)
    alerts = []  # automatic stock alert for items that are now low / finished
    for o, _ in done:
        cur = db.items.find_one({"_id": o})
        if cur and cur.get("qty", 0) <= cur.get("low", 0):
            alerts.append(f"{cur['name']} ({cur.get('qty', 0):g} {cur.get('unit', '')} left)")
    return jsonify(url=url_for("bill_print", bid=bill["_id"]), alerts=alerts)


@app.route("/bill/<int:bid>")
@login_required
def bill_print(bid):
    raw = db.bills.find_one({"_id": bid})
    if not raw:
        abort(404)
    b = Doc(raw)
    sub = raw.get("subtotal")
    if sub is None:
        sub = sum(l.get("amount", l["price"] * l["qty"]) for l in raw["lines"])
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
    f = request.args.get("f", "")
    rows = [Doc(i) for i in db.items.find().sort("name", 1)]
    value = sum(i["buy"] * i["qty"] for i in rows)
    nlow = sum(1 for i in rows if i["qty"] <= i["low"])
    if f == "low":
        rows = [i for i in rows if i["qty"] <= i["low"]]
    return render_template("items.html", rows=rows, value=value, nlow=nlow, f=f)


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
    discounts = sum(b.get("discount", 0) or 0 for b in rows)
    profit = sum(l.get("amount", l["price"] * l["qty"]) - l["cost"] * l["qty"]
                 for b in rows for l in b["lines"]) - discounts
    low = [Doc(i) for i in db.items.find(
        {"$expr": {"$lte": ["$qty", "$low"]}}).sort("qty", 1)]
    return render_template("report.html", day=day, rows=rows, sales=sales,
                           profit=profit, discounts=discounts, low=low)


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
.hit:hover{background:#fde8d8}.r{text-align:right}.err{color:#b91c1c}.big{font-size:22px;font-weight:700}.alert{display:block;background:#b91c1c;color:#fff;text-align:center;padding:9px;text-decoration:none;font-weight:600}.hit.sel{background:#fde8d8}.hit.out{opacity:.5}.chips{display:flex;gap:6px;margin-bottom:10px}footer{text-align:center;color:#6b7280;font-size:13px;padding:16px 14px 24px}
</style></head><body>
<header><b>{{ shop }}</b>
{% if request.endpoint != 'login' %}<nav><a href="/bill/new">New bill</a><a href="/items">Items</a>
<a href="/bills">Bills</a><a href="/report">Report</a><a href="/help">Help</a><a href="/logout">Log out</a></nav>{% endif %}</header>
{% if request.endpoint != 'login' %}{% set n = low_count() %}{% if n %}<a class="alert" href="/items?f=low">&#9888; Stock alert: {{ n }} item{{ 's' if n > 1 }} low or finished - tap to view</a>{% endif %}{% endif %}
<main>{% block body %}{% endblock %}</main>
<footer>Developed and managed by Spidy</footer></body></html>"""

HELP = """{% extends "base.html" %}{% block body %}
<h2>How this system works</h2>
<div class="card"><b>1. Add your items (once)</b>
<p>Go to <b>Items</b>. Fill the name, buying price, selling price and how many you have in stock, then tap <b>Add item</b>.
Set "Low alert at" so you are warned when stock is running out. Use <b>Edit</b> to change prices or add new stock when goods arrive.
<b>Delete</b> removes an item.</p></div>
<div class="card"><b>2. Make a bill</b>
<p>Go to <b>New bill</b>. Type part of an item name, tap the item to add it, and change the quantity or price if needed.
Enter the customer name (optional) and the cash received, then tap <b>Save and print</b>.
The stock goes down automatically. The bill shows the total, cash and change.<br>
<b>Discount:</b> type a discount in Rs, or a percentage (%), under the item list. You can also type the final total you want to charge and the discount is worked out for you. The bill shows the subtotal, the discount and the new total.</p></div>
<div class="card"><b>3. Print</b>
<p>The print window opens by itself. Choose your thermal printer (YHD-5890, 58mm), set paper size to 58mm, margins to "None" and scale to 100%. Bills are 58mm wide;
for an 80mm printer add <b>?w=80</b> at the end of the bill address. To print again later, open <b>Bills</b> and tap <b>Reprint</b>.</p></div>
<div class="card"><b>4. Wrong bill?</b>
<p>In <b>Bills</b> tap <b>Void</b>. The bill is deleted and its items go back into stock.</p></div>
<div class="card"><b>Automatic stock alert</b>
<p>When an item reaches its "Low alert" number, a red bar appears at the top of every page, and after saving a bill the system pops up a warning with the item name. Tap the bar to see all low items.</p></div>
<div class="card"><b>5. Reports</b>
<p><b>Report</b> shows the sales, discounts, profit and bills for any day, and the list of items that are low in stock.</p></div>
{% endblock %}"""

LOGIN = """{% extends "base.html" %}{% block body %}
<form method="post" class="card"><h2>Log in</h2>
<p><input type="password" name="password" placeholder="Password" autofocus></p>
<p class="err">{{ err }}</p><button>Log in</button></form>{% endblock %}"""

BILL_FORM = """{% extends "base.html" %}{% block body %}
<h2>New bill</h2>
<div class="card"><input id="q" placeholder="Search item name or code…" autocomplete="off"><div id="res"></div></div>
<div class="card wrap"><table><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Amount</th><th></th></tr></thead>
<tbody id="cart"><tr><td colspan="5">Search and tap an item to add it.</td></tr></tbody></table></div>
<div class="card"><div class="row"><input id="cust" placeholder="Customer name (optional)">
<input id="paid" type="number" min="0" step="any" placeholder="Cash received (Rs)"></div>
<div class="row"><label>Subtotal (Rs)<input id="sub" readonly></label>
<label>Discount (Rs)<input id="disc" type="number" min="0" step="any" placeholder="0"></label>
<label>Discount (%)<input id="dpct" type="number" min="0" max="100" step="any" placeholder="0"></label></div>
<p><label>Total to pay (Rs) - or type the final price you want and the discount is set for you<input id="ftot" type="number" min="0" step="any" class="big"></label></p>
<p class="err" id="err"></p><button id="save">Save and print</button></div>
<script>
const items={{ items|tojson }};let cart=[];
const q=document.getElementById('q'),res=document.getElementById('res'),body=document.getElementById('cart');
const subE=document.getElementById('sub'),discE=document.getElementById('disc'),dpctE=document.getElementById('dpct'),ftE=document.getElementById('ftot');
let pctMode=false;
const f=n=>n.toLocaleString('en-LK',{minimumFractionDigits:2,maximumFractionDigits:2});
let hits=[],sel=0;
const norm=s=>(s||'').toLowerCase();
function find(txt){const t=norm(txt).split(/\\s+/).filter(Boolean);if(!t.length)return[];
 return items.map(i=>{const n=norm(i.name),c=norm(i.code),hay=n+' '+c+' '+norm(i.category);
  if(!t.every(w=>hay.includes(w)))return null;
  let sc=0;if(n.startsWith(t[0]))sc+=3;if(n.split(/\\s+/).some(w=>w.startsWith(t[0])))sc+=2;if(c&&c===t.join(' '))sc+=5;if(i.qty>0)sc+=1;
  return{i,sc}}).filter(Boolean).sort((a,b)=>b.sc-a.sc||a.i.name.localeCompare(b.i.name)).slice(0,10).map(x=>x.i)}
function show(){res.innerHTML='';hits.forEach((i,k)=>{const d=document.createElement('div');
 d.className='hit'+(k==sel?' sel':'')+(i.qty<=0?' out':'');
 const a=document.createElement('b');a.textContent=i.name;
 const b=document.createElement('span');b.textContent='  Rs '+f(i.sell)+' | '+i.qty+' '+i.unit+(i.qty<=0?' - OUT OF STOCK':i.qty<=i.low?' - LOW':'');
 if(i.qty<=i.low)b.className='err';d.append(a,b);d.onclick=()=>pick(i);res.appendChild(d)});
 if(!hits.length&&q.value.trim())res.innerHTML='<div class="hit">No item found</div>'}
q.oninput=()=>{hits=find(q.value);sel=0;show()};
q.onkeydown=e=>{if(!hits.length)return;
 if(e.key==='ArrowDown'){e.preventDefault();sel=(sel+1)%hits.length;show()}
 else if(e.key==='ArrowUp'){e.preventDefault();sel=(sel-1+hits.length)%hits.length;show()}
 else if(e.key==='Enter'){e.preventDefault();pick(hits[sel])}
 else if(e.key==='Escape'){hits=[];show()}};
function pick(i){const e=document.getElementById('err');e.textContent='';
 if(i.qty<=0){e.textContent=i.name+' is out of stock';return}
 add(i);q.value='';res.innerHTML='';hits=[];q.focus()}
const r2=n=>Math.round((n+Number.EPSILON)*100)/100;
function add(i){const l=cart.find(c=>c.id==i.id);
 if(l){l.qty++;l.amount=r2(l.qty*l.price)}else cart.push({id:i.id,name:i.name,price:i.sell,qty:1,amount:i.sell,max:i.qty});draw()}
function draw(){body.innerHTML='';
 if(!cart.length){body.innerHTML='<tr><td colspan="5">Search and tap an item to add it.</td></tr>';calc();return}
 cart.forEach((l,k)=>{const tr=document.createElement('tr');
  tr.innerHTML='<td></td><td><input type="number" min="0" step="any"></td><td><input type="number" min="0" step="any"></td><td><input type="number" min="0" step="any"></td><td><button class="alt">&#10005;</button></td>';
  tr.cells[0].textContent=l.name;
  const [qi,pi,ai]=tr.querySelectorAll('input');qi.value=l.qty;pi.value=l.price;ai.value=l.amount;
  qi.oninput=()=>{l.qty=+qi.value;l.amount=r2(l.qty*l.price);ai.value=l.amount;calc()};
  pi.oninput=()=>{l.price=+pi.value;l.amount=r2(l.qty*l.price);ai.value=l.amount;calc()};
  ai.oninput=()=>{l.amount=+ai.value;if(l.qty>0){l.price=r2(l.amount/l.qty);pi.value=l.price}calc()};
  tr.querySelector('button').onclick=()=>{cart.splice(k,1);draw()};body.appendChild(tr)});calc()}
function subtotal(){return cart.reduce((x,l)=>x+l.amount,0)}
function calc(){const s=subtotal();
 cart.forEach((l,k)=>{const r=body.rows[k],qi=r&&r.querySelector('input');if(qi)qi.style.borderColor=l.qty>l.max?'#b91c1c':''});
 if(pctMode&&dpctE.value!=='')discE.value=r2(s*Math.min(Math.max(+dpctE.value||0,0),100)/100);
 let d=Math.max(+discE.value||0,0);if(d>s){d=s;discE.value=r2(d)}
 subE.value=cart.length?r2(s):'';
 if(document.activeElement!==ftE)ftE.value=cart.length?r2(s-d):''}
discE.oninput=()=>{pctMode=false;dpctE.value='';calc();ftE.value=cart.length?r2(subtotal()-(+discE.value||0)):''};
dpctE.oninput=()=>{pctMode=true;calc();ftE.value=cart.length?r2(subtotal()-(+discE.value||0)):''};
ftE.onchange=e=>{const T=+e.target.value,S=subtotal();
 if(!cart.length||!(T>=0)||S<=0)return;
 pctMode=false;dpctE.value='';discE.value=T>=S?'':r2(S-T);ftE.blur();calc()};
document.getElementById('save').onclick=async()=>{const e=document.getElementById('err');e.textContent='';
 const r=await fetch('/bill/new',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({lines:cart,customer:document.getElementById('cust').value,paid:document.getElementById('paid').value,discount:discE.value})});
 const j=await r.json();if(!r.ok){e.textContent=j.error;return}
 if(j.alerts&&j.alerts.length)alert('Stock alert - low or finished: '+j.alerts.join(', '));location=j.url};
</script>{% endblock %}"""

ITEMS = """{% extends "base.html" %}{% block body %}
<h2>Items and stock</h2>
<p>{{ rows|length }} items &nbsp;|&nbsp; Stock value (cost): Rs {{ value|money }} &nbsp;|&nbsp; Low stock: <b>{{ nlow }}</b></p>
<form method="post" class="card"><b>Add new item</b><div class="row" style="margin-top:8px">
<input name="code" placeholder="Item code (optional)"><input name="name" placeholder="Item name" required>
<input name="category" placeholder="Category"><input name="unit" placeholder="Unit (pcs, kg, m)"></div>
<div class="row"><input name="buy" type="number" step="any" placeholder="Buying price">
<input name="sell" type="number" step="any" placeholder="Selling price">
<input name="qty" type="number" step="any" placeholder="Opening stock"><input name="low" type="number" step="any" placeholder="Low alert at"></div>
<button>Add item</button></form>
<div class="chips"><a class="btn {{ '' if f == 'low' else 'alt' }}" href="/items?f=low">Low stock only ({{ nlow }})</a><a class="btn {{ 'alt' if f == 'low' else '' }}" href="/items">All items</a></div>
<div class="card"><input id="s" placeholder="Search by name, code or category…"></div>
<div class="card wrap"><table id="t"><thead><tr><th>Code</th><th>Name</th><th>Category</th><th class="r">Buy</th><th class="r">Sell</th><th class="r">Stock</th><th></th></tr></thead>
{% for i in rows %}<tr class="{{ 'low' if i.qty <= i.low }}" data-s="{{ (i.code ~ ' ' ~ i.name ~ ' ' ~ i.category)|lower }}">
<td>{{ i.code }}</td><td>{{ i.name }}</td><td>{{ i.category }}</td><td class="r">{{ i.buy|money }}</td><td class="r">{{ i.sell|money }}</td>
<td class="r">{{ i.qty|num }} {{ i.unit }}{% if i.qty <= 0 %} <b class="err">OUT</b>{% elif i.qty <= i.low %} <b class="err">LOW</b>{% endif %}</td>
<td style="white-space:nowrap"><a class="btn" href="/items/{{ i.id }}/edit">Edit</a>
<form method="post" action="/items/{{ i.id }}/delete" style="display:inline" onsubmit="return confirm('Delete {{ i.name|e }}?')"><button class="alt">Delete</button></form></td></tr>
{% else %}<tr><td colspan="7">No items yet. Add your first item above.</td></tr>{% endfor %}</table></div>
<script>document.getElementById('s').oninput=e=>{const v=e.target.value.toLowerCase();
const t=v.split(/\\s+/).filter(Boolean);
document.querySelectorAll('#t tr[data-s]').forEach(r=>r.style.display=t.every(w=>r.dataset.s.includes(w))?'':'none')}</script>{% endblock %}"""

ITEM_EDIT = """{% extends "base.html" %}{% block body %}
<h2>Edit item</h2>
<form method="post" class="card"><div class="row"><input name="code" value="{{ i.code }}" placeholder="Item code (optional)">
<input name="name" value="{{ i.name }}" required><input name="category" value="{{ i.category }}" placeholder="Category">
<input name="unit" value="{{ i.unit }}" placeholder="Unit"></div>
<div class="row"><label>Buying price<input name="buy" type="number" step="any" value="{{ i.buy|num }}"></label>
<label>Selling price<input name="sell" type="number" step="any" value="{{ i.sell|num }}"></label>
<label>Low alert at<input name="low" type="number" step="any" value="{{ i.low|num }}"></label></div>
<div class="row"><label>Stock now<input name="qty" type="number" step="any" value="{{ i.qty|num }}"></label>
<label>Add stock (+)<input name="add" type="number" step="any" placeholder="0"></label></div>
<button>Save changes</button> <a class="btn alt" href="/items">Cancel</a></form>{% endblock %}"""

BILLS = """{% extends "base.html" %}{% block body %}<h2>Recent bills</h2>
<div class="card wrap"><table><tr><th>No.</th><th>Date</th><th>Customer</th><th class="r">Discount</th><th class="r">Total</th><th></th></tr>
{% for b in rows %}<tr><td>{{ b.id }}</td><td>{{ b.created.strftime('%Y-%m-%d %H:%M') }}</td><td>{{ b.customer }}</td>
<td class="r">{{ b.discount|money if b.discount else '-' }}</td>
<td class="r">{{ b.total|money }}</td><td style="white-space:nowrap"><a class="btn" href="/bill/{{ b.id }}">Reprint</a>
<form method="post" action="/bill/{{ b.id }}/delete" style="display:inline" onsubmit="return confirm('Void bill {{ b.id }}? Stock will be put back.')"><button class="alt">Void</button></form></td></tr>
{% else %}<tr><td colspan="6">No bills yet.</td></tr>{% endfor %}</table></div>{% endblock %}"""

REPORT = """{% extends "base.html" %}{% block body %}<h2>Daily report</h2>
<form class="card row"><input type="date" name="d" value="{{ day }}"><button>Show</button></form>
<div class="card"><p>Bills: <b>{{ rows|length }}</b></p><p>Sales: <span class="big">Rs {{ sales|money }}</span></p>
<p>Discounts given: <b>Rs {{ discounts|money }}</b></p>
<p>Profit: <b>Rs {{ profit|money }}</b></p></div>
<div class="card wrap"><table><tr><th>No.</th><th>Time</th><th>Customer</th><th class="r">Total</th></tr>
{% for b in rows %}<tr><td><a href="/bill/{{ b.id }}">{{ b.id }}</a></td><td>{{ b.created.strftime('%H:%M') }}</td><td>{{ b.customer }}</td><td class="r">{{ b.total|money }}</td></tr>
{% else %}<tr><td colspan="4">No bills on this day.</td></tr>{% endfor %}</table></div>
<h2 id="low">Low stock</h2><div class="card wrap"><table><tr><th>Item</th><th>In stock</th></tr>
{% for i in low %}<tr class="low"><td>{{ i.name }}</td><td>{{ i.qty|num }}</td></tr>
{% else %}<tr><td colspan="2">All items are above their alert level.</td></tr>{% endfor %}</table></div>{% endblock %}"""

PRINT = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{% set w80 = request.args.get('w') == '80' %}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,800;1,700&display=swap" rel="stylesheet">
<title>Bill {{ b.id }}</title><style>
@page{size:{{ 80 if w80 else 58 }}mm auto;margin:0}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
html{background:#fff}
body{font:700 11px/1.45 'Courier New',monospace;color:#000;background:#fff;width:{{ 72 if w80 else 48 }}mm;margin:0 auto;padding:2mm 0 12mm;-webkit-font-smoothing:none}
.brand{text-align:center;color:#000;background:none;padding:5px 2px 4px;border-top:2px solid #000;border-bottom:2px solid #000;font:900 {{ 28 if w80 else 22 }}px/1.1 'Playfair Display',Georgia,'Times New Roman',serif;letter-spacing:.3px}
.rc{text-align:center;font:700 9px Arial,Helvetica,sans-serif;letter-spacing:3px;margin-bottom:3px}
.tag{text-align:center;font:italic 700 12px 'Playfair Display',Georgia,serif;letter-spacing:.3px;margin:5px 0 2px}
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
<div class="rc">RECEIPT</div>
<div class="brand">{{ shop }}</div>
{% if tagline %}<div class="tag">{{ tagline }}</div>{% endif %}
<div class="addr">{{ address }}{% if phone %}<br>TEL: {{ phone }}{% endif %}</div><hr class="d">
<div class="l"><span>Bill No</span><span class="b">#{{ '%04d' % b.id }}</span></div>
<div class="l"><span>Date</span><span>{{ b.created.strftime('%Y-%m-%d') }}</span></div>
<div class="l"><span>Time</span><span>{{ b.created.strftime('%H:%M') }}</span></div>
{% if b.customer %}<div class="l"><span>Customer</span><span>{{ b.customer }}</span></div>{% endif %}<hr class="d">
<div class="l hd"><span>ITEM</span><span>AMOUNT (Rs)</span></div>
{% for l in b.lines %}<div class="nm">{{ loop.index }}. {{ l.name }}</div>
<div class="l it"><span>{{ l.qty|num }} x {{ l.price|money }}</span><span>{{ l.amount|money }}</span></div>{% endfor %}<hr>
<div class="l sm"><span>Items: {{ b.lines|length }}</span><span>Total qty: {{ b.lines|sum(attribute='qty')|num }}</span></div>
<hr class="s">
{% if b.discount %}<div class="l"><span>Subtotal</span><span>{{ sub|money }}</span></div>
<div class="l b"><span>Discount</span><span>- {{ b.discount|money }}</span></div>{% endif %}
<div class="box l"><span>TOTAL</span><span>Rs {{ b.total|money }}</span></div><hr class="s">
{% if b.paid %}<div class="l"><span>Cash</span><span>{{ b.paid|money }}</span></div>
<div class="l b"><span>Change</span><span>{{ (b.paid - b.total)|money }}</span></div>{% endif %}
<hr class="d">
<div class="ty">Thank you for your purchase!</div><div class="c sm">Please visit us again</div>
{% if footer_note %}<div class="c sm" style="margin-top:3px">{{ footer_note }}</div>{% endif %}
<script>if(location.search.indexOf('p=0')<0&&document.referrer.indexOf('/bill/new')>-1){(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(()=>setTimeout(()=>window.print(),150))}</script>
</body></html>"""

app.jinja_loader = DictLoader({
    "base.html": BASE, "login.html": LOGIN, "bill_form.html": BILL_FORM,
    "items.html": ITEMS, "help.html": HELP, "item_edit.html": ITEM_EDIT, "bills.html": BILLS, "report.html": REPORT,
    "print.html": PRINT,
})

if __name__ == "__main__":
    app.run(debug=True)
