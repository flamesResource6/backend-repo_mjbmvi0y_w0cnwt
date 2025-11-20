import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import (
    RegisterRequest, LoginRequest,
    StartSessionRequest, EndSessionRequest,
    CreateOrderRequest, UpdateOrderStatusRequest,
    CheckoutRequest, CreateMenuItemRequest,
    UpdateStationStatusRequest,
    Cafe, User, Station, Session, MenuItem, Order, OrderItem, Payment, Settings, KDSUpdate, Notification, AuditLog
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def audit(action: str, table: str, record_id: Optional[str], payload: Optional[dict], user_id: Optional[str] = None, cafe_id: Optional[str] = None):
    try:
        create_document("auditlog", AuditLog(
            user_id=user_id,
            cafe_id=cafe_id,
            action=action,
            table=table,
            record_id=record_id,
            payload=payload or {}
        ))
    except Exception:
        pass


@app.get("/")
def read_root():
    return {"message": "Gamifisys POS+KDS Backend (MongoDB)"}


@app.get("/test_database")
def test_database():
    if db is None:
        return {"backend": "running", "database": "not-configured"}
    return {
        "backend": "running",
        "database": "connected",
        "collections": db.list_collection_names(),
    }


# Auth (simple email+password hash placeholder for demo). In production use a proper auth provider.
@app.post("/auth/register")
def register(req: RegisterRequest):
    existing = db.user.find_one({"email": req.email})
    if existing:
        raise HTTPException(400, "Email already registered")
    user = User(
        email=req.email,
        password_hash=req.password,  # NOTE: replace with proper hashing in production
        name=req.name,
        role=req.role,
        is_active=True,
    )
    uid = create_document("user", user)
    audit("create", "user", uid, user.model_dump())
    return {"user_id": uid}


@app.post("/auth/login")
def login(req: LoginRequest):
    user = db.user.find_one({"email": req.email, "password_hash": req.password, "is_active": True})
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"user_id": str(user["_id"]), "name": user.get("name"), "role": user.get("role")}


# Stations
@app.get("/stations")
def fetch_stations(cafe_id: Optional[str] = None):
    q = {"cafe_id": cafe_id} if cafe_id else {}
    items = list(db.station.find(q))
    for x in items:
        x["_id"] = str(x["_id"]) 
    return items


@app.post("/stations")
def create_station(station: Station):
    sid = create_document("station", station)
    audit("create", "station", sid, station.model_dump(), cafe_id=station.cafe_id)
    return {"station_id": sid}


@app.post("/stations/status")
def update_station_status(req: UpdateStationStatusRequest):
    st = db.station.find_one({"_id": oid(req.station_id)})
    if not st:
        raise HTTPException(404, "Station not found")
    db.station.update_one({"_id": oid(req.station_id)}, {"$set": {"status": req.status, "updated_at": datetime.now(timezone.utc)}})
    audit("update", "station", req.station_id, {"status": req.status}, cafe_id=st.get("cafe_id"))
    return {"ok": True}


# Sessions
@app.post("/sessions/start")
def start_session(req: StartSessionRequest):
    st = db.station.find_one({"_id": oid(req.station_id)})
    if not st:
        raise HTTPException(404, "Station not found")
    if st.get("status") == "in-use":
        raise HTTPException(409, "Station already in use")

    session = Session(
        cafe_id=req.cafe_id,
        station_id=req.station_id,
        status="active",
        customer_name=req.customer_name,
        started_at=now_iso(),
    )
    sid = create_document("session", session)
    db.station.update_one({"_id": oid(req.station_id)}, {"$set": {"status": "in-use", "current_session_id": sid}})
    audit("create", "session", sid, session.model_dump(), cafe_id=req.cafe_id)
    return {"session_id": sid}


@app.post("/sessions/end")
def end_session(req: EndSessionRequest):
    sess = db.session.find_one({"_id": oid(req.session_id)})
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("status") == "ended":
        return {"ok": True}

    db.session.update_one({"_id": oid(req.session_id)}, {"$set": {"status": "ended", "ended_at": now_iso()}})
    db.station.update_one({"_id": oid(sess["station_id"])}, {"$set": {"status": "available", "current_session_id": None}})
    audit("update", "session", req.session_id, {"status": "ended"}, cafe_id=sess.get("cafe_id"))
    return {"ok": True}


@app.get("/sessions")
def fetch_sessions(cafe_id: Optional[str] = None, status: Optional[str] = None):
    q = {}
    if cafe_id:
        q["cafe_id"] = cafe_id
    if status:
        q["status"] = status
    items = list(db.session.find(q).sort("created_at", -1).limit(100))
    for x in items:
        x["_id"] = str(x["_id"]) 
    return items


# Menu
@app.get("/menu")
def fetch_menu(cafe_id: Optional[str] = None):
    q = {"cafe_id": cafe_id} if cafe_id else {}
    items = list(db.menuitem.find(q))
    for x in items:
        x["_id"] = str(x["_id"]) 
    return items


@app.post("/menu")
def create_menu_item(req: CreateMenuItemRequest):
    mi = MenuItem(**req.model_dump())
    mid = create_document("menuitem", mi)
    audit("create", "menuitem", mid, mi.model_dump(), cafe_id=mi.cafe_id)
    return {"menu_item_id": mid}


# Orders
@app.post("/orders")
def create_order(req: CreateOrderRequest):
    if not req.items:
        raise HTTPException(400, "Order must have items")

    # Build OrderItems from authoritative prices in MenuItem
    items: list[OrderItem] = []
    subtotal = 0.0
    for it in req.items:
        item_doc = db.menuitem.find_one({"_id": oid(it["item_id"])})
        if not item_doc or not item_doc.get("is_active", True):
            raise HTTPException(400, f"Invalid menu item: {it['item_id']}")
        qty = int(it.get("qty", 1))
        if qty <= 0:
            raise HTTPException(400, "Invalid quantity")
        unit_price = float(item_doc["price"]) 
        line_total = unit_price * qty
        subtotal += line_total
        items.append(OrderItem(
            item_id=str(item_doc["_id"]),
            name=item_doc["name"],
            qty=qty,
            unit_price=unit_price,
            total_price=line_total,
        ))

    settings = db.settings.find_one({"cafe_id": req.cafe_id}) or {"tax_rate": 0.0}
    tax = round(subtotal * float(settings.get("tax_rate", 0.0)), 2)
    total = round(subtotal + tax, 2)

    order = Order(
        cafe_id=req.cafe_id,
        session_id=req.session_id,
        station_id=req.station_id,
        items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        status="pending",
        notes=req.notes,
    )
    oid_new = create_document("order", order)
    audit("create", "order", oid_new, order.model_dump(), cafe_id=req.cafe_id)
    return {"order_id": oid_new, "total": total}


@app.post("/orders/status")
def update_order_status(req: UpdateOrderStatusRequest):
    o = db.order.find_one({"_id": oid(req.order_id)})
    if not o:
        raise HTTPException(404, "Order not found")
    db.order.update_one({"_id": oid(req.order_id)}, {"$set": {"status": req.status, "updated_at": datetime.now(timezone.utc)}})
    audit("update", "order", req.order_id, {"status": req.status}, cafe_id=o.get("cafe_id"))
    return {"ok": True}


@app.get("/orders/pending")
def fetch_pending_orders(cafe_id: Optional[str] = None):
    q = {"status": {"$in": ["pending", "preparing"]}}
    if cafe_id:
        q["cafe_id"] = cafe_id
    items = list(db.order.find(q).sort("created_at", -1).limit(100))
    for x in items:
        x["_id"] = str(x["_id"]) 
    return items


# Payments / Checkout
@app.post("/checkout")
def checkout(req: CheckoutRequest):
    # Basic idempotency: if payment with idempotency_key exists and success, return it
    existing = db.payment.find_one({"idempotency_key": req.idempotency_key, "status": "success"})
    if existing:
        return {"payment_id": str(existing["_id"]), "status": "success"}

    payment = Payment(
        cafe_id=req.cafe_id,
        order_id=req.order_id,
        session_id=req.session_id,
        amount=req.amount,
        method=req.method,
        status="success",
        idempotency_key=req.idempotency_key,
    )
    pid = create_document("payment", payment)

    # If closing a session, mark ended and free station
    if req.session_id:
        sess = db.session.find_one({"_id": oid(req.session_id)})
        if sess and sess.get("status") != "ended":
            db.session.update_one({"_id": oid(req.session_id)}, {"$set": {"status": "ended", "ended_at": now_iso()}})
            db.station.update_one({"_id": oid(sess["station_id"])}, {"$set": {"status": "available", "current_session_id": None}})
            audit("update", "session", req.session_id, {"status": "ended"}, cafe_id=sess.get("cafe_id"))

    if req.order_id:
        db.order.update_one({"_id": oid(req.order_id)}, {"$set": {"status": "served"}})
        audit("update", "order", req.order_id, {"status": "served"})

    audit("create", "payment", pid, payment.model_dump(), cafe_id=req.cafe_id)
    return {"payment_id": pid, "status": "success"}


# Settings
@app.get("/settings")
def get_settings(cafe_id: str):
    s = db.settings.find_one({"cafe_id": cafe_id})
    if not s:
        # default
        s = Settings(cafe_id=cafe_id, currency="INR", tax_rate=0.05, service_charge_rate=0.0).model_dump()
        create_document("settings", s)
    s["_id"] = str(s.get("_id", ""))
    return s


@app.post("/settings")
def update_settings(s: Settings):
    existing = db.settings.find_one({"cafe_id": s.cafe_id})
    if existing:
        db.settings.update_one({"_id": existing["_id"]}, {"$set": s.model_dump()})
        sid = str(existing["_id"])
    else:
        sid = create_document("settings", s)
    audit("update", "settings", sid, s.model_dump(), cafe_id=s.cafe_id)
    return {"ok": True}


# Minimal dashboard stats
@app.get("/dashboard/stats")
def fetch_dashboard_stats(cafe_id: Optional[str] = None):
    q = {"cafe_id": cafe_id} if cafe_id else {}
    total_orders = db.order.count_documents(q)
    total_sessions = db.session.count_documents(q)
    total_payments = db.payment.count_documents(q)
    revenue = 0.0
    for p in db.payment.find(q):
        revenue += float(p.get("amount", 0))
    return {
        "orders": total_orders,
        "sessions": total_sessions,
        "payments": total_payments,
        "revenue": round(revenue, 2),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
