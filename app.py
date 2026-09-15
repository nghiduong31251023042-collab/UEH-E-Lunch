from flask import Flask, render_template, jsonify, request
import sqlite3, os, uuid, base64, io, json
from datetime import datetime
import qrcode

app = Flask(__name__)
DB = os.environ.get('DATABASE_PATH', 'ueh_elunch.db')
STAFF_PIN = os.environ.get('STAFF_PIN', '2468')

MENU = [
    {'id':1,'name':'Mì Quảng thập cẩm','price':35000,'category':'Món nước','img':'mi_quang.jpg','status':'available','orders':12,'rating':4.8,'prep':10},
    {'id':2,'name':'Hủ tiếu Nam Vang','price':35000,'category':'Món nước','img':'hu_tieu.jpg','status':'low','orders':28,'rating':4.7,'prep':12},
    {'id':3,'name':'Nui xào bò','price':35000,'category':'Món xào','img':'nui_xao.jpg','status':'available','orders':15,'rating':4.6,'prep':10},
    {'id':4,'name':'Phở xào bò','price':35000,'category':'Món xào','img':'pho.jpg','status':'soldout','orders':42,'rating':4.9,'prep':12},
    {'id':5,'name':'Thịt heo cuốn bánh tráng','price':35000,'category':'Món cuốn','img':'thit_heo_cuon.jpg','status':'available','orders':21,'rating':4.8,'prep':8},
    {'id':6,'name':'Chả trứng cuốn bánh tráng','price':35000,'category':'Món cuốn','img':'cha_trung_cuon.jpg','status':'available','orders':9,'rating':4.5,'prep':8},
    {'id':7,'name':'Gà rô ti','price':35000,'category':'Cơm','img':'ga_roti.jpg','status':'low','orders':31,'rating':4.8,'prep':10},
    {'id':8,'name':'Gà xối mỡ','price':35000,'category':'Cơm','img':'ga_xoi_mo.jpg','status':'available','orders':19,'rating':4.7,'prep':12},
    {'id':9,'name':'Cá chiên mắm tỏi','price':35000,'category':'Cơm','img':'ca_chien.jpg','status':'available','orders':17,'rating':4.6,'prep':12},
    {'id':10,'name':'Thịt kho trứng','price':35000,'category':'Cơm','img':'thit_kho.jpg','status':'available','orders':14,'rating':4.9,'prep':10},
    {'id':11,'name':'Sandwich','price':25000,'category':'Ăn vặt','img':'sandwich.jpg','status':'available','orders':8,'rating':4.4,'prep':5},
    {'id':12,'name':'Salad trộn','price':25000,'category':'Ăn vặt','img':'salad.jpg','status':'available','orders':7,'rating':4.6,'prep':5},
    {'id':13,'name':'Bánh giò chả trứng','price':30000,'category':'Ăn vặt','img':'banh_gio.jpg','status':'low','orders':23,'rating':4.7,'prep':5},
    {'id':14,'name':'Trái cây thập cẩm','price':30000,'category':'Ăn vặt','img':'trai_cay.jpg','status':'available','orders':6,'rating':4.5,'prep':3},
    {'id':15,'name':'Hoành thánh chiên','price':35000,'category':'Ăn vặt','img':'hoanh_thanh.jpg','status':'available','orders':18,'rating':4.8,'prep':8},
    {'id':16,'name':'Gà lắc','price':35000,'category':'Ăn vặt','img':'ga_lac.jpg','status':'available','orders':25,'rating':4.8,'prep':8},
    {'id':17,'name':'Sữa chua trái cây','price':30000,'category':'Đồ uống','img':'sua_chua.jpg','status':'available','orders':11,'rating':4.6,'prep':4},
    {'id':18,'name':'Trà trái cây','price':25000,'category':'Đồ uống','img':'tra_cay.jpg','status':'available','orders':13,'rating':4.7,'prep':4},
    {'id':19,'name':'Matcha latte','price':30000,'category':'Đồ uống','img':'matcha.jpg','status':'available','orders':10,'rating':4.7,'prep':5},
    {'id':20,'name':'Trà sữa trân châu','price':30000,'category':'Đồ uống','img':'tra_sua.jpg','status':'low','orders':29,'rating':4.8,'prep':5},
]

STATUS_OVERRIDE = {}

# Giới hạn suất theo từng khung giờ nhận món. Có thể chỉnh tại đây khi cần.
PICKUP_SLOTS = {
    '11:15 - 11:30': 30,
    '11:30 - 11:45': 30,
    '11:45 - 12:00': 35,
    '12:00 - 12:15': 30,
    '12:15 - 12:30': 30,
    '12:30 - 12:45': 30,
}

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = conn()
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
      id TEXT PRIMARY KEY, items TEXT NOT NULL, total INTEGER NOT NULL,
      pickup TEXT NOT NULL, prep INTEGER NOT NULL, status TEXT NOT NULL,
      paid INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pickup_slots (
      pickup TEXT PRIMARY KEY, capacity INTEGER NOT NULL
    )''')
    for slot, cap in PICKUP_SLOTS.items():
        c.execute('INSERT OR IGNORE INTO pickup_slots (pickup, capacity) VALUES (?,?)', (slot, cap))
    c.commit(); c.close()

init_db()

def get_slot_capacities(c=None):
    own=False
    if c is None:
        c=conn(); own=True
    rows=c.execute('SELECT pickup, capacity FROM pickup_slots ORDER BY rowid').fetchall()
    caps={r['pickup']:int(r['capacity']) for r in rows}
    if own: c.close()
    return caps

def current_capacity(pickup, c=None):
    caps=get_slot_capacities(c)
    return caps.get(pickup, PICKUP_SLOTS.get(pickup))

@app.route('/')
def home(): return render_template('index.html')

@app.get('/api/menu')
def api_menu():
    data=[]
    for m in MENU:
        x=dict(m); x['status']=STATUS_OVERRIDE.get(m['id'],m['status']); data.append(x)
    return jsonify(data)

@app.post('/api/orders')
def create_order():
    d=request.get_json(force=True)
    items=d.get('items',[])
    if not items: return jsonify({'error':'Giỏ hàng trống'}),400
    menu={m['id']:m for m in MENU}
    normalized=[]; total=0; prep=0
    for it in items:
        mid=int(it['id']); qty=max(1,int(it.get('qty',1)))
        m=menu.get(mid)
        if not m: continue
        if STATUS_OVERRIDE.get(mid,m['status'])=='soldout':
            return jsonify({'error':f"{m['name']} đã hết món"}),409
        normalized.append({'id':mid,'name':m['name'],'price':m['price'],'qty':qty,'img':m['img']})
        total += m['price']*qty; prep=max(prep,m['prep'])
    oid='EL-'+uuid.uuid4().hex[:8].upper()
    pickup=d.get('pickup') or '11:30 - 11:45'
    if pickup not in PICKUP_SLOTS:
        return jsonify({'error':'Khung giờ nhận món không hợp lệ'}),400

    # Mỗi món trong đơn được tính là 1 suất; hủy đơn sẽ trả lại suất.
    requested_slots=sum(x['qty'] for x in normalized)
    c=conn()
    active_rows=c.execute(
        "SELECT items FROM orders WHERE pickup=? AND status NOT LIKE 'Đã hủy%'",
        (pickup,)
    ).fetchall()
    used=0
    for row in active_rows:
        try:
            used += sum(int(x.get('qty', 0)) for x in json.loads(row['items']))
        except Exception:
            pass
    capacity=current_capacity(pickup, c)
    if used + requested_slots > capacity:
        c.close()
        return jsonify({'error':f'Khung {pickup} đã hết slot. Còn {max(0, capacity-used)} suất.'}),409

    c.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)',
      (oid,json.dumps(normalized,ensure_ascii=False),total,pickup,prep,'Chờ thanh toán',0,datetime.now().isoformat(timespec='seconds')))
    c.commit(); c.close()
    return jsonify({'id':oid,'total':total,'pickup':pickup,'prep':prep})


@app.get('/api/staff/orders')
def staff_orders():
    pin = request.headers.get('X-Staff-PIN', '')
    if str(pin) != STAFF_PIN:
        return jsonify({'error':'Sai PIN nhân viên'}),403

    c = conn()
    rows = c.execute("""
        SELECT id, items, total, pickup, prep, status, paid, created_at
        FROM orders
        ORDER BY created_at DESC
    """).fetchall()
    c.close()

    orders = []
    for row in rows:
        try:
            items = json.loads(row['items'])
        except Exception:
            items = []

        orders.append({
            'id': row['id'],
            'items': items,
            'total': row['total'],
            'pickup': row['pickup'],
            'prep': row['prep'],
            'status': row['status'],
            'paid': row['paid'],
            'created_at': row['created_at']
        })

    return jsonify(orders)

@app.post('/api/orders/<oid>/pay')
def pay(oid):
    c=conn(); c.execute("UPDATE orders SET paid=1,status='Đã thanh toán - đang chuẩn bị' WHERE id=?",(oid,)); c.commit(); c.close()
    return jsonify({'ok':True})

@app.post('/api/orders/<oid>/cancel')
def cancel(oid):
    c=conn(); row=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
    if not row: c.close(); return jsonify({'error':'Không tìm thấy đơn'}),404
    if 'Hoàn tất' in row['status']: c.close(); return jsonify({'error':'Đơn đã hoàn tất'}),409
    c.execute("UPDATE orders SET status='Đã hủy' WHERE id=?",(oid,)); c.commit(); c.close(); return jsonify({'ok':True})

@app.post('/api/orders/<oid>/pickup')
def change_pickup(oid):
    pickup=request.get_json(force=True).get('pickup','')
    if pickup not in PICKUP_SLOTS:
        return jsonify({'error':'Khung giờ nhận món không hợp lệ'}),400
    c=conn(); row=c.execute('SELECT items,status FROM orders WHERE id=?',(oid,)).fetchone()
    if not row:
        c.close(); return jsonify({'error':'Không tìm thấy đơn'}),404
    if row['status'].startswith('Đã hủy'):
        c.close(); return jsonify({'error':'Đơn đã hủy'}),409
    requested=sum(int(x.get('qty',0)) for x in json.loads(row['items']))
    rows=c.execute(
        "SELECT items FROM orders WHERE pickup=? AND id<>? AND status NOT LIKE 'Đã hủy%'",
        (pickup,oid)
    ).fetchall()
    used=sum(sum(int(x.get('qty',0)) for x in json.loads(r['items'])) for r in rows)
    capacity=current_capacity(pickup, c)
    if used + requested > capacity:
        c.close(); return jsonify({'error':f'Khung {pickup} đã hết slot. Còn {max(0,capacity-used)} suất.'}),409
    c.execute('UPDATE orders SET pickup=? WHERE id=?',(pickup,oid)); c.commit(); c.close(); return jsonify({'ok':True})

@app.get('/api/pickup-slots')
def pickup_slots():
    c=conn()
    rows=c.execute("SELECT pickup, items FROM orders WHERE status NOT LIKE 'Đã hủy%'").fetchall()
    c.close()
    used={slot:0 for slot in PICKUP_SLOTS}
    for row in rows:
        if row['pickup'] not in used:
            continue
        try:
            used[row['pickup']] += sum(int(x.get('qty',0)) for x in json.loads(row['items']))
        except Exception:
            pass
    return jsonify([
        {'time':slot,'used':used[slot],'capacity':cap,'full':used[slot]>=cap}
        for slot,cap in get_slot_capacities().items()
    ])

@app.get('/api/orders/<oid>')
def get_order(oid):
    c=conn(); r=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); c.close()
    if not r: return jsonify({'error':'Không tìm thấy đơn'}),404
    d=dict(r); d['items']=json.loads(d['items'])
    payload=f"UEH-E-LUNCH|{oid}|PICKUP:{d['pickup']}|TOTAL:{d['total']}"
    qr=qrcode.make(payload); b=io.BytesIO(); qr.save(b,format='PNG')
    d['qr']='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
    return jsonify(d)

@app.get('/api/staff/pickup-slots')
def staff_pickup_slots():
    pin = request.headers.get('X-Staff-PIN', '')
    if str(pin) != STAFF_PIN:
        return jsonify({'error':'Sai PIN nhân viên'}),403
    c=conn()
    caps=get_slot_capacities(c)
    rows=c.execute("SELECT pickup, items FROM orders WHERE status NOT LIKE 'Đã hủy%'").fetchall()
    c.close()
    used={slot:0 for slot in caps}
    for row in rows:
        if row['pickup'] not in used:
            continue
        try:
            used[row['pickup']] += sum(int(x.get('qty',0)) for x in json.loads(row['items']))
        except Exception:
            pass
    return jsonify([{'time':slot,'used':used[slot],'capacity':cap,'remaining':max(0,cap-used[slot]),'full':used[slot]>=cap} for slot,cap in caps.items()])

@app.post('/api/staff/pickup-slots')
def update_staff_pickup_slots():
    d=request.get_json(force=True)
    pin = request.headers.get('X-Staff-PIN', '') or str(d.get('pin', ''))
    if str(pin) != STAFF_PIN:
        return jsonify({'error':'Sai PIN nhân viên'}),403
    slot=str(d.get('time','')).strip()
    try:
        capacity=int(d.get('capacity'))
    except Exception:
        return jsonify({'error':'Số suất phải là số nguyên'}),400
    if capacity < 1 or capacity > 500:
        return jsonify({'error':'Số suất phải từ 1 đến 500'}),400
    c=conn()
    caps=get_slot_capacities(c)
    if slot not in caps:
        c.close(); return jsonify({'error':'Khung giờ không hợp lệ'}),400
    rows=c.execute("SELECT items FROM orders WHERE pickup=? AND status NOT LIKE 'Đã hủy%'",(slot,)).fetchall()
    used=0
    for row in rows:
        try: used += sum(int(x.get('qty',0)) for x in json.loads(row['items']))
        except Exception: pass
    if capacity < used:
        c.close(); return jsonify({'error':f'Không thể giảm xuống {capacity} vì đã có {used} suất được đặt.'}),409
    c.execute('UPDATE pickup_slots SET capacity=? WHERE pickup=?',(capacity,slot))
    c.commit(); c.close()
    return jsonify({'ok':True,'time':slot,'capacity':capacity,'used':used,'remaining':capacity-used})

@app.post('/api/staff/status')
def staff_status():
    d=request.get_json(force=True)
    if str(d.get('pin')) != STAFF_PIN: return jsonify({'error':'Sai PIN nhân viên'}),403
    mid=int(d['id']); status=d['status']
    if status not in ('available','low','soldout'): return jsonify({'error':'Trạng thái không hợp lệ'}),400
    STATUS_OVERRIDE[mid]=status
    return jsonify({'ok':True})

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
