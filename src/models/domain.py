from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List
from enum import Enum

@dataclass
class Product:
    """Entidad de dominio: Producto de seguridad industrial"""
    id: str
    name: str
    category: str
    description: Optional[str]
    unit: str
    unit_cost: float
    lead_time_days: int
    safety_certification: Optional[str]
    compliance_standard: Optional[str]
    requires_calibration: bool
    calibration_frequency_days: Optional[int]
    min_storage_temperature: Optional[float]
    max_storage_temperature: Optional[float]
    
@dataclass
class Warehouse:
    """Entidad de dominio: Bodega especializada"""
    id: str
    name: str
    location: str
    capacity: int
    current_utilization: float
    temperature_controlled: bool
    security_level: str
    specialty: Optional[str]
    
@dataclass
class StockItem:
    """Entidad de dominio: Item de inventario"""
    product: Product
    warehouse: Warehouse
    current_quantity: int
    reserved_quantity: int
    reorder_point: int
    min_stock_level: int
    max_stock_level: Optional[int]
    expiry_date: Optional[date]
    last_audit_date: Optional[date]
    last_updated: datetime
    
    @property
    def available_quantity(self) -> int:
        return max(self.current_quantity - self.reserved_quantity, 0)
    
    @property
    def needs_reorder(self) -> bool:
        return self.available_quantity <= self.reorder_point
    
    @property
    def is_below_minimum(self) -> bool:
        return self.available_quantity <= self.min_stock_level
    
    @property
    def days_to_expiry(self) -> Optional[int]:
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None
    
    @property
    def expiry_status(self) -> str:
        days = self.days_to_expiry
        if days is None:
            return "NO_APPLICA"
        elif days <= 0:
            return "VENCIDO"
        elif days <= 30:
            return "PROXIMO_VENCER"
        elif days <= 90:
            return "VIGILANCIA"
        else:
            return "VIGENTE"

@dataclass
class StockAlert:
    """Alerta de stock"""
    id: str
    stock_item: StockItem
    alert_type: str  # "REORDER", "EXPIRY", "MINIMUM", "AUDIT"
    severity: str    # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    message: str
    suggested_action: str
    created_at: datetime
    acknowledged: bool = False