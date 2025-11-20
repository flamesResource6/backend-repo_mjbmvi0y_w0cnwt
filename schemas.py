"""
Database Schemas (MongoDB via Pydantic)

Each Pydantic model corresponds to a MongoDB collection (lowercased model name).
Use these models for validation at API boundaries.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr, conint, confloat

# Core domain schemas
class Cafe(BaseModel):
    name: str
    address: Optional[str] = None
    timezone: Optional[str] = "UTC"
    is_active: bool = True

class Role(BaseModel):
    name: Literal["admin", "cashier", "chef", "manager"]
    description: Optional[str] = None

class User(BaseModel):
    email: EmailStr
    password_hash: str
    name: str
    role: Literal["admin", "cashier", "chef", "manager"] = "cashier"
    cafe_id: Optional[str] = None
    is_active: bool = True

class Station(BaseModel):
    cafe_id: str
    name: str
    status: Literal["available", "in-use", "offline", "maintenance"] = "available"
    current_session_id: Optional[str] = None

class Session(BaseModel):
    cafe_id: str
    station_id: str
    user_id: Optional[str] = None  # staff who started
    customer_name: Optional[str] = None
    status: Literal["active", "ended", "paused"] = "active"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_minutes: Optional[int] = None
    total_amount: Optional[confloat(ge=0)] = 0.0

class MenuItem(BaseModel):
    cafe_id: str
    name: str
    category: Optional[str] = None
    price: confloat(ge=0)
    sku: Optional[str] = None
    is_active: bool = True

class Inventory(BaseModel):
    cafe_id: str
    sku: str
    name: str
    qty: conint(ge=0)
    min_qty: Optional[conint(ge=0)] = 0

class OrderItem(BaseModel):
    item_id: str  # MenuItem _id
    name: str
    qty: conint(gt=0)
    unit_price: confloat(ge=0)
    total_price: confloat(ge=0)

class Order(BaseModel):
    cafe_id: str
    session_id: Optional[str] = None
    station_id: Optional[str] = None
    status: Literal["pending", "preparing", "ready", "served", "canceled"] = "pending"
    items: List[OrderItem] = []
    subtotal: confloat(ge=0) = 0.0
    tax: confloat(ge=0) = 0.0
    total: confloat(ge=0) = 0.0
    notes: Optional[str] = None

class Payment(BaseModel):
    cafe_id: str
    order_id: Optional[str] = None
    session_id: Optional[str] = None
    amount: confloat(ge=0)
    method: Literal["cash", "upi", "card"]
    status: Literal["initiated", "success", "failed", "refunded"] = "success"
    idempotency_key: Optional[str] = None
    reference: Optional[str] = None

class Settings(BaseModel):
    cafe_id: str
    currency: str = "INR"
    tax_rate: confloat(ge=0) = 0.0
    service_charge_rate: confloat(ge=0) = 0.0

class KDSUpdate(BaseModel):
    cafe_id: str
    order_id: str
    status: Literal["pending", "preparing", "ready", "served"]
    note: Optional[str] = None

class Notification(BaseModel):
    cafe_id: str
    type: Literal["order", "session", "payment", "system"]
    title: str
    body: Optional[str] = None
    read: bool = False

class AuditLog(BaseModel):
    user_id: Optional[str] = None
    cafe_id: Optional[str] = None
    action: str
    table: str
    record_id: Optional[str] = None
    payload: Optional[dict] = None

# Request DTOs
class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: Literal["admin", "cashier", "chef", "manager"] = "cashier"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class StartSessionRequest(BaseModel):
    cafe_id: str
    station_id: str
    customer_name: Optional[str] = "Walk-in"

class EndSessionRequest(BaseModel):
    session_id: str

class CreateOrderRequest(BaseModel):
    cafe_id: str
    session_id: Optional[str] = None
    station_id: Optional[str] = None
    items: List[dict]
    notes: Optional[str] = None

class UpdateOrderStatusRequest(BaseModel):
    order_id: str
    status: Literal["pending", "preparing", "ready", "served", "canceled"]

class CheckoutRequest(BaseModel):
    cafe_id: str
    session_id: Optional[str] = None
    order_id: Optional[str] = None
    amount: confloat(ge=0)
    method: Literal["cash", "upi", "card"]
    idempotency_key: str

class CreateMenuItemRequest(BaseModel):
    cafe_id: str
    name: str
    price: confloat(ge=0)
    category: Optional[str] = None
    sku: Optional[str] = None

class UpdateStationStatusRequest(BaseModel):
    station_id: str
    status: Literal["available", "in-use", "offline", "maintenance"]
