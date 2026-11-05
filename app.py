import csv
import io
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
PHONES = ["072 992 1118", "052 222 0315", "071 938 2718"]  # numbers printed on the bill
PASSWORD = "12345678"
TAGLINE = "Hardware & Building Materials"
FOOTER_NOTE = "Thank You Come Again !"
# Shop header image for the printed bill (name, ME logo and "Hardware & Building Materials" banner)
LOGO_B64 = "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"

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
                footer_note=FOOTER_NOTE, low_count=low_count, logo_b64=LOGO_B64, phones=PHONES)


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
                  sell=i.get("sell", 0), qty=i.get("qty", 0), low=i.get("low", 0),
                  image=i.get("image", ""))
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
                image=f.get("image", "").strip(),
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


@app.route("/items/import", methods=["GET", "POST"])
@login_required
def items_import():
    msg = ""
    if request.method == "POST":
        up = request.files.get("file")
        if not up or not up.filename:
            msg = "Choose a CSV file first"
        else:
            try:
                text = up.read().decode("utf-8-sig")
                have = {(i.get("name") or "").strip().lower() for i in db.items.find({}, {"name": 1})}
                new = []
                for r in csv.DictReader(io.StringIO(text)):
                    name = (r.get("name") or "").strip()
                    if not name or name.lower() in have:
                        continue
                    have.add(name.lower())

                    def n(k):
                        try:
                            return float(r.get(k) or 0)
                        except ValueError:
                            return 0.0
                    new.append(dict(code=(r.get("code") or "").strip(), name=name,
                                    category=(r.get("category") or "").strip(),
                                    image=(r.get("image") or "").strip(),
                                    unit=(r.get("unit") or "").strip() or "pcs",
                                    buy=n("buy"), sell=n("sell"), qty=n("qty"), low=n("low")))
                if new:
                    db.items.insert_many(new)
                msg = f"Added {len(new)} new items. Items already in the list were skipped."
            except Exception as e:
                msg = f"Import failed: {e}"
    return render_template("items_import.html", msg=msg)


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
.th{width:40px;height:40px;object-fit:cover;border-radius:6px;vertical-align:middle;margin-right:8px;border:1px solid var(--line);background:#fff}
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
 if(i.qty<=i.low)b.className='err';
 if(i.image){const m=document.createElement('img');m.src=i.image;m.className='th';m.onerror=()=>m.remove();d.append(m)}
 d.append(a,b);d.onclick=()=>pick(i);res.appendChild(d)});
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
 if(l){l.qty++;l.amount=r2(l.qty*l.price)}else cart.push({id:i.id,name:i.name,price:i.sell,qty:1,amount:i.sell,max:i.qty,img:i.image});draw()}
function draw(){body.innerHTML='';
 if(!cart.length){body.innerHTML='<tr><td colspan="5">Search and tap an item to add it.</td></tr>';calc();return}
 cart.forEach((l,k)=>{const tr=document.createElement('tr');
  tr.innerHTML='<td></td><td><input type="number" min="0" step="any"></td><td><input type="number" min="0" step="any"></td><td><input type="number" min="0" step="any"></td><td><button class="alt">&#10005;</button></td>';
  tr.cells[0].textContent=l.name;
  if(l.img){const m=document.createElement('img');m.src=l.img;m.className='th';m.onerror=()=>m.remove();tr.cells[0].prepend(m)}
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
<div class="row"><input name="image" type="url" placeholder="Image URL (optional) - paste a picture link to identify the item"></div>
<button>Add item</button></form>
<div class="chips"><a class="btn {{ '' if f == 'low' else 'alt' }}" href="/items?f=low">Low stock only ({{ nlow }})</a><a class="btn {{ 'alt' if f == 'low' else '' }}" href="/items">All items</a><a class="btn alt" href="/items/import">Import CSV</a></div>
<div class="card"><input id="s" placeholder="Search by name, code or category…"></div>
<div class="card wrap"><table id="t"><thead><tr><th>Code</th><th>Name</th><th>Category</th><th class="r">Buy</th><th class="r">Sell</th><th class="r">Stock</th><th></th></tr></thead>
{% for i in rows %}<tr class="{{ 'low' if i.qty <= i.low }}" data-s="{{ (i.code ~ ' ' ~ i.name ~ ' ' ~ i.category)|lower }}">
<td>{{ i.code }}</td><td>{% if i.image %}<img class="th" src="{{ i.image }}" loading="lazy" alt="" onerror="this.style.display='none'">{% endif %}{{ i.name }}</td><td>{{ i.category }}</td><td class="r">{{ i.buy|money }}</td><td class="r">{{ i.sell|money }}</td>
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
<div class="row"><label>Image URL (picture link to identify the item)<input name="image" type="url" value="{{ i.image or '' }}" placeholder="https://..."></label></div>
{% if i.image %}<p><img src="{{ i.image }}" alt="" style="max-height:140px;max-width:100%;border-radius:8px;border:1px solid var(--line)" onerror="this.style.display='none'"></p>{% endif %}
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
<title>Bill {{ b.id }}</title><style>
@page{size:{{ 80 if w80 else 58 }}mm auto;margin:0}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
html{background:#fff}
{% set off = request.args.get('o', '0')|float %}{% set sw = request.args.get('s', '35')|float %}
body{font:700 12px/1.35 Arial,Helvetica,sans-serif;color:#000;background:#fff;width:{{ 68 if w80 else sw }}mm;margin:0 auto;position:relative;left:{{ off }}mm;padding:2mm 0 12mm;-webkit-font-smoothing:none}
.logo{display:block;width:100%;height:auto;margin:0 auto 4px}
.addr{text-align:center;font-size:12px;line-height:1.3;margin-bottom:6px}
hr{border:0;border-top:1px solid #000;margin:6px 0}hr.d{border-top:1px solid #000;margin:2px 0 6px}hr.t{border-top:1px dashed #000}
.l{display:flex;justify-content:space-between;gap:6px}
.info{font-size:13px;line-height:1.3}
.hd{font-size:12px;letter-spacing:.2px;border-bottom:1px solid #000;padding-bottom:2px;margin-bottom:5px}
.nm{font-size:13px}.it{padding-left:2mm;margin-bottom:4px;font-size:13px}.sm{font-size:12px}
.box{margin:6px 0;padding:2px 0;font-size:15px}
.b{font-weight:700}.c{text-align:center}.ty{text-align:center;font-size:13px;line-height:1.15}
.bar{text-align:center;margin-bottom:10px}.bar a,.bar button{font:14px sans-serif;padding:8px 14px;margin:2px}
@media print{.bar{display:none}}
</style></head><body>
<div class="bar"><button onclick="window.print()">Print</button><a href="/bill/new">New bill</a></div>
<img class="logo" alt="{{ shop }}" src="data:image/png;base64,{{ logo_b64 }}">
<div class="addr">{{ address }}{% for p in phones %}<br>TEL: {{ p }}{% endfor %}</div><hr>
<div class="info"><div class="l"><span>Bill No</span><span class="b">#{{ '%04d' % b.id }}</span></div>
<div class="l"><span>Date</span><span>{{ b.created.strftime('%Y-%m-%d') }}</span></div>
<div class="l"><span>Time</span><span>{{ b.created.strftime('%H:%M') }}</span></div>
{% if b.customer %}<div class="l"><span>Customer</span><span>{{ b.customer }}</span></div>{% endif %}</div><hr>
<div class="l hd"><span>ITEM</span><span>AMOUNT</span></div>
{% for l in b.lines %}<div class="nm">{{ loop.index }}. {{ l.name }}</div>
<div class="l it"><span>{{ l.qty|num }} x {{ l.price|money }}</span><span>{{ l.amount|money }}</span></div>{% endfor %}<hr class="t">
<div class="l sm"><span>Items: {{ b.lines|length }}</span><span>Total qty: {{ b.lines|sum(attribute='qty')|num }}</span></div>
<hr>
{% if b.discount %}<div class="l"><span>Subtotal</span><span>{{ sub|money }}</span></div>
<div class="l b"><span>Discount</span><span>- {{ b.discount|money }}</span></div>{% endif %}
<div class="box l"><span>TOTAL</span><span>Rs {{ b.total|money }}</span></div><hr class="d"><hr class="d">
{% if b.paid %}<div class="l"><span>Cash</span><span>{{ b.paid|money }}</span></div>
<div class="l b"><span>Change</span><span>{{ (b.paid - b.total)|money }}</span></div><hr class="d">{% endif %}
<div class="ty">Thank you for your purchase!</div><div class="c sm" style="margin-top:2px">Please visit us again</div>
{% if footer_note %}<div class="c sm" style="margin-top:4px">{{ footer_note }}</div>{% endif %}
<script>if(location.search.indexOf('p=0')<0&&document.referrer.indexOf('/bill/new')>-1){var go=function(){setTimeout(function(){window.print()},150)},im=document.querySelector('.logo');if(im.complete)go();else im.onload=go}</script>
</body></html>"""

IMPORT = """{% extends "base.html" %}{% block body %}
<h2>Import items</h2>
<form method="post" enctype="multipart/form-data" class="card">
<p>Choose a CSV file with the columns <b>code, name, category, unit, buy, sell, qty, low</b>. Only <b>name</b> is required. Items whose name is already in your list are skipped, so it is safe to import the same file twice.</p>
<p><input type="file" name="file" accept=".csv,text/csv"></p>
{% if msg %}<p><b>{{ msg }}</b></p>{% endif %}
<button>Import</button> <a class="btn alt" href="/items">Back to items</a></form>{% endblock %}"""

app.jinja_loader = DictLoader({
    "base.html": BASE, "login.html": LOGIN, "bill_form.html": BILL_FORM,
    "items.html": ITEMS, "help.html": HELP, "item_edit.html": ITEM_EDIT, "bills.html": BILLS, "report.html": REPORT,
    "print.html": PRINT, "items_import.html": IMPORT,
})

if __name__ == "__main__":
    app.run(debug=True)
