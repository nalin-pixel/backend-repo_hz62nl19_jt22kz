"""
Database Schemas for ByteRize (Computer Store)

Each Pydantic model represents a collection in MongoDB. The collection
name is the lowercase of the class name (e.g., Product -> "product").
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class User(BaseModel):
    """
    Users collection schema
    Collection: "user"
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Hashed password or demo password")
    role: str = Field("customer", description="Role: customer or admin")
    approved: bool = Field(False, description="Whether login is approved by admin")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Product(BaseModel):
    """
    Products collection schema
    Collection: "product"
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in USD")
    category: str = Field("Computers", description="Product category")
    image: Optional[str] = Field(None, description="Image URL")
    in_stock: bool = Field(True, description="Availability")
    stock_qty: int = Field(10, ge=0, description="Stock quantity")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OrderItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int = Field(..., ge=1)


class Order(BaseModel):
    """
    Orders collection schema
    Collection: "order"
    """
    user_email: EmailStr
    items: List[OrderItem]
    total: float = Field(..., ge=0)
    status: str = Field("pending", description="pending | paid | shipped | cancelled")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
