from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict
from datetime import datetime, date
from enum import Enum

class ProductCategory(str, Enum):
    EPP = "EPP"                   # Equipo de Protección Personal
    SEÑALIZACION = "SEÑALIZACION"
    EXTINCION = "EXTINCION"
    DOTACIONES = "DOTACIONES"
    MONITOREO = "MONITOREO"
    PRIMEROS_AUXILIOS = "PRIMEROS_AUXILIOS"
    HERRAMIENTAS = "HERRAMIENTAS"

class SafetyLevel(str, Enum):
    CRITICO = "CRITICO"      # Productos críticos para seguridad
    ALTO = "ALTO"           # Alta prioridad (cascos, respiradores)
    MEDIO = "MEDIO"         # Prioridad media (guantes, lentes)
    BAJO = "BAJO"           # Baja prioridad (señalización general)

class StockRequest(BaseModel):
    """Request para consulta de stock industrial"""
    product_id: str = Field(..., min_length=3, max_length=50, 
                          description="ID del producto (ej: CASCO-001)")
    warehouse_id: Optional[str] = Field(None, min_length=3, max_length=20,
                                      description="ID de la bodega (ej: BOD-01)")
    include_history: bool = Field(False, description="Incluir historial de movimientos")
    include_compliance: bool = Field(False, description="Incluir info de cumplimiento normativo")
    
    @validator('product_id')
    def validate_product_format(cls, v):
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError('ID de producto debe ser alfanumérico')
        return v.upper()

class IndustrialStockResponse(BaseModel):
    """Response para productos de seguridad industrial"""
    product_id: str
    product_name: str
    category: ProductCategory
    description: Optional[str]
    
    warehouse_id: str
    warehouse_name: str
    warehouse_location: str
    
    # Stock information
    current_stock: int = Field(..., ge=0)
    reserved_stock: int = Field(..., ge=0)
    available_stock: int = Field(..., ge=0)
    unit: str = Field(..., description="Unidad de medida (unidad, caja, par, etc.)")
    
    # Safety information
    safety_level: SafetyLevel
    reorder_point: int = Field(..., ge=0)
    min_stock_level: int = Field(..., ge=0)
    max_stock_level: Optional[int] = Field(None, ge=0)
    
    # Regulatory compliance
    certification: Optional[str] = Field(None, description="Certificación (ANSI, OSHA, etc.)")
    compliance_standard: Optional[str] = Field(None, description="Norma de cumplimiento")
    expiry_date: Optional[date] = Field(None, description="Fecha de vencimiento")
    days_to_expiry: Optional[int] = Field(None, description="Días hasta vencimiento")
    requires_calibration: bool = Field(False)
    last_calibration_date: Optional[date]
    
    # Business logic
    needs_reorder: bool
    expiry_alert: Optional[str]
    suggested_order_quantity: Optional[int]
    
    # Performance metrics
    response_time_ms: float
    cache_hit: bool = Field(False)
    last_updated: datetime
    
    @validator('available_stock', pre=True, always=True)
    def calculate_available_stock(cls, v, values):
        if 'current_stock' in values and 'reserved_stock' in values:
            return max(values['current_stock'] - values['reserved_stock'], 0)
        return v
    
    @validator('needs_reorder', pre=True, always=True)
    def calculate_needs_reorder(cls, v, values):
        if 'available_stock' in values and 'reorder_point' in values:
            return values['available_stock'] <= values['reorder_point']
        return v
    
    @validator('days_to_expiry', pre=True, always=True)
    def calculate_days_to_expiry(cls, v, values):
        if 'expiry_date' in values and values['expiry_date']:
            from datetime import date
            delta = values['expiry_date'] - date.today()
            return delta.days
        return None
    
    @validator('expiry_alert', pre=True, always=True)
    def calculate_expiry_alert(cls, v, values):
        if 'days_to_expiry' in values and values['days_to_expiry'] is not None:
            days = values['days_to_expiry']
            if days <= 0:
                return "VENCIDO"
            elif days <= 30:
                return f"VENCE EN {days} DÍAS"
            elif days <= 90:
                return "VIGILANCIA"
        return None

class CriticalAlert(BaseModel):
    """Alerta para productos críticos"""
    alert_id: str
    product_id: str
    product_name: str
    warehouse_id: str
    alert_type: str = Field(..., description="STOCK_BAJO, VENCIMIENTO, SIN_CERTIFICACION")
    severity: str = Field(..., description="CRITICO, ALTO, MEDIO")
    current_value: int
    threshold_value: int
    message: str
    suggested_action: str
    timestamp: datetime
    
class BatchStockRequest(BaseModel):
    """Request para consulta batch de múltiples productos"""
    products: List[StockRequest] = Field(..., max_items=100)
    
class BatchStockResponse(BaseModel):
    """Response para consulta batch"""
    results: List[IndustrialStockResponse]
    total_products: int
    products_needing_reorder: int
    critical_alerts: int
    average_response_time_ms: float
    generated_at: datetime

class SafetyComplianceReport(BaseModel):
    """Reporte de cumplimiento normativo"""
    warehouse_id: str
    total_products: int
    compliant_products: int
    compliance_rate: float
    expired_products: List[str]
    missing_certifications: List[str]
    next_audit_date: Optional[date]
    safety_score: float = Field(..., ge=0, le=100)