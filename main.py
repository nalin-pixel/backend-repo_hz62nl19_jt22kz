import os
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
from bson import ObjectId
from datetime import datetime, timezone

from database import db, create_document, get_documents

app = FastAPI(title="ByteRize API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------- Helpers ----------------------

def oid_to_str(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # convert datetime to iso
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def require_admin(x_admin: Optional[str]):
    if x_admin != "true":
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------------------- Schemas ----------------------

class ProductIn(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    category: str = "Computers"
    image: Optional[str] = None
    in_stock: bool = True
    stock_qty: int = Field(10, ge=0)


class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "customer"  # customer | admin


class LoginReq(BaseModel):
    email: EmailStr
    password: str


class OrderItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int = Field(..., ge=1)


class OrderIn(BaseModel):
    user_email: EmailStr
    items: List[OrderItem]
    total: float = Field(..., ge=0)


# ---------------------- Root & Health ----------------------

@app.get("/")
def read_root():
    return {"message": "ByteRize FastAPI Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = getattr(db, "name", None) or "❌ Unknown"
            # list collections
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------------------- Products ----------------------

@app.get("/api/products")
def list_products() -> List[Dict[str, Any]]:
    docs = get_documents("product")
    return [oid_to_str(d) for d in docs]


@app.post("/api/products")
def create_product(product: ProductIn, x_admin: Optional[str] = Header(None)) -> Dict[str, Any]:
    require_admin(x_admin)
    data = product.model_dump()
    now = datetime.now(timezone.utc)
    data.update({"created_at": now, "updated_at": now})
    inserted_id = db["product"].insert_one(data).inserted_id
    created = db["product"].find_one({"_id": inserted_id})
    return oid_to_str(created)


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str, x_admin: Optional[str] = Header(None)) -> Dict[str, str]:
    require_admin(x_admin)
    try:
        res = db["product"].delete_one({"_id": ObjectId(product_id)})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")


# ---------------------- Users ----------------------

@app.post("/api/users/register")
def register_user(user: UserRegister) -> Dict[str, Any]:
    existing = db["user"].find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    approved = True if user.role == "admin" else False
    doc = {
        "name": user.name,
        "email": user.email,
        "password": user.password,  # NOTE: demo only; do NOT store plain text in production
        "role": user.role,
        "approved": approved,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    inserted_id = db["user"].insert_one(doc).inserted_id
    created = db["user"].find_one({"_id": inserted_id})
    return oid_to_str(created)


@app.post("/api/users/login")
def login(req: LoginReq) -> Dict[str, Any]:
    user = db["user"].find_one({"email": req.email})
    if not user or user.get("password") != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("approved"):
        raise HTTPException(status_code=403, detail="Account awaiting approval")
    return {
        "email": user["email"],
        "name": user.get("name"),
        "role": user.get("role", "customer"),
        "approved": True,
    }


@app.get("/api/users")
def list_users(x_admin: Optional[str] = Header(None)) -> List[Dict[str, Any]]:
    require_admin(x_admin)
    users = list(db["user"].find({}, {"password": 0}))
    return [oid_to_str(u) for u in users]


@app.post("/api/users/{email}/approve")
def approve_user(email: str, x_admin: Optional[str] = Header(None)) -> Dict[str, str]:
    require_admin(x_admin)
    res = db["user"].update_one({"email": email}, {"$set": {"approved": True, "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "approved"}


# ---------------------- Orders ----------------------

@app.post("/api/orders")
def create_order(order: OrderIn) -> Dict[str, Any]:
    # basic validation for totals
    calc_total = sum(i.price * i.quantity for i in order.items)
    if round(calc_total, 2) != round(order.total, 2):
        raise HTTPException(status_code=400, detail="Total mismatch")
    doc = order.model_dump()
    now = datetime.now(timezone.utc)
    doc.update({"status": "pending", "created_at": now, "updated_at": now})

    # decrement stock quantities (best-effort/simple)
    for item in order.items:
        try:
            db["product"].update_one(
                {"_id": ObjectId(item.product_id), "stock_qty": {"$gte": item.quantity}},
                {"$inc": {"stock_qty": -item.quantity}, "$set": {"updated_at": now}},
            )
        except Exception:
            continue

    inserted_id = db["order"].insert_one(doc).inserted_id
    created = db["order"].find_one({"_id": inserted_id})
    return oid_to_str(created)


@app.get("/api/orders")
def list_orders(email: Optional[EmailStr] = Query(None), x_admin: Optional[str] = Header(None)) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if email and x_admin != "true":
        q["user_email"] = email
    orders = list(db["order"].find(q))
    return [oid_to_str(o) for o in orders]


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
