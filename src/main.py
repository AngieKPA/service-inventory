from fastapi import FastAPI
import asyncpg
import os

app = FastAPI(title="Inventario Seguridad Industrial")

@app.get("/")
async def root():
    return {"message": "Sistema de Inventario - Seguridad Industrial"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "inventory-api"}

@app.post("/api/v1/industrial/stock")
async def query_stock_industrial(data: dict):
    """Endpoint SIMULADO para productos industriales"""
    return {
        "product_id": data.get("product_id", "CASCO-001"),
        "product_name": "Casco de Seguridad Tipo II",
        "category": "EPP",
        "warehouse_id": data.get("warehouse_id", "BOD-01"),
        "current_stock": 250,
        "reserved_stock": 45,
        "available_stock": 205,
        "reorder_point": 50,
        "safety_level": "ALTO",
        "certification": "ANSI Z89.1",
        "response_time_ms": 120.5,
        "needs_reorder": False
    }

@app.get("/api/v1/industrial/alerts")
async def get_alerts():
    """Alertas críticas simuladas"""
    return [
        {
            "product_id": "RESP-001",
            "product_name": "Respirador N95",
            "alert": "STOCK BAJO",
            "current": 15,
            "minimum": 30,
            "urgency": "ALTA"
        }
    ]