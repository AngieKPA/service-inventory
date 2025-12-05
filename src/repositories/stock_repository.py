import asyncpg
from typing import Optional, List, Dict, Any
import logging
from datetime import date, datetime
from src.core.database import get_postgres_pool
from src.models.domain import Product, Warehouse, StockItem

logger = logging.getLogger(__name__)

class StockRepository:
    """Repositorio para acceso a datos de stock"""
    
    async def get_stock_item(self, product_id: str, warehouse_id: Optional[str] = None) -> Optional[StockItem]:
        """Obtener item de stock específico"""
        try:
            pool = get_postgres_pool()
            
            if warehouse_id:
                query = """
                SELECT 
                    p.id as product_id, p.name as product_name, p.category,
                    p.description, p.unit, p.unit_cost, p.lead_time_days,
                    p.safety_certification, p.compliance_standard,
                    p.requires_calibration, p.calibration_frequency_days,
                    
                    w.id as warehouse_id, w.name as warehouse_name, 
                    w.location, w.capacity, w.current_utilization,
                    w.temperature_controlled, w.security_level, w.specialty,
                    
                    s.current_quantity, s.reserved_quantity, s.reorder_point,
                    s.min_stock_level, s.max_stock_level, s.expiry_date,
                    s.last_audit_date, s.last_updated
                    
                FROM stock s
                JOIN products p ON s.product_id = p.id
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE p.id = $1 AND w.id = $2
                """
                params = (product_id, warehouse_id)
            else:
                query = """
                SELECT 
                    p.id as product_id, p.name as product_name, p.category,
                    p.description, p.unit, p.unit_cost, p.lead_time_days,
                    p.safety_certification, p.compliance_standard,
                    p.requires_calibration, p.calibration_frequency_days,
                    
                    w.id as warehouse_id, w.name as warehouse_name, 
                    w.location, w.capacity, w.current_utilization,
                    w.temperature_controlled, w.security_level, w.specialty,
                    
                    s.current_quantity, s.reserved_quantity, s.reorder_point,
                    s.min_stock_level, s.max_stock_level, s.expiry_date,
                    s.last_audit_date, s.last_updated
                    
                FROM stock s
                JOIN products p ON s.product_id = p.id
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE p.id = $1
                ORDER BY s.current_quantity DESC
                LIMIT 1
                """
                params = (product_id,)
            
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
                
                if row:
                    # Crear objetos de dominio
                    product = Product(
                        id=row['product_id'],
                        name=row['product_name'],
                        category=row['category'],
                        description=row['description'],
                        unit=row['unit'],
                        unit_cost=float(row['unit_cost']),
                        lead_time_days=row['lead_time_days'],
                        safety_certification=row['safety_certification'],
                        compliance_standard=row['compliance_standard'],
                        requires_calibration=row['requires_calibration'],
                        calibration_frequency_days=row['calibration_frequency_days'],
                        min_storage_temperature=None,
                        max_storage_temperature=None
                    )
                    
                    warehouse = Warehouse(
                        id=row['warehouse_id'],
                        name=row['warehouse_name'],
                        location=row['location'],
                        capacity=row['capacity'],
                        current_utilization=float(row['current_utilization']),
                        temperature_controlled=row['temperature_controlled'],
                        security_level=row['security_level'],
                        specialty=row['specialty']
                    )
                    
                    return StockItem(
                        product=product,
                        warehouse=warehouse,
                        current_quantity=row['current_quantity'],
                        reserved_quantity=row['reserved_quantity'],
                        reorder_point=row['reorder_point'],
                        min_stock_level=row['min_stock_level'],
                        max_stock_level=row['max_stock_level'],
                        expiry_date=row['expiry_date'],
                        last_audit_date=row['last_audit_date'],
                        last_updated=row['last_updated']
                    )
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting stock item: {str(e)}")
            raise
    
    async def get_batch_stock(self, product_ids: List[str], warehouse_id: Optional[str] = None) -> List[StockItem]:
        """Obtener múltiples items de stock eficientemente"""
        if not product_ids:
            return []
        
        try:
            pool = get_postgres_pool()
            
            placeholders = ','.join([f'${i+1}' for i in range(len(product_ids))])
            
            if warehouse_id:
                query = f"""
                SELECT 
                    p.id as product_id, p.name as product_name, p.category,
                    p.description, p.unit, p.unit_cost, p.lead_time_days,
                    p.safety_certification, p.compliance_standard,
                    p.requires_calibration, p.calibration_frequency_days,
                    
                    w.id as warehouse_id, w.name as warehouse_name, 
                    w.location, w.capacity, w.current_utilization,
                    w.temperature_controlled, w.security_level, w.specialty,
                    
                    s.current_quantity, s.reserved_quantity, s.reorder_point,
                    s.min_stock_level, s.max_stock_level, s.expiry_date,
                    s.last_audit_date, s.last_updated
                    
                FROM stock s
                JOIN products p ON s.product_id = p.id
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE p.id IN ({placeholders}) AND w.id = ${len(product_ids) + 1}
                """
                params = (*product_ids, warehouse_id)
            else:
                query = f"""
                WITH ranked_stock AS (
                    SELECT 
                        p.id as product_id, p.name as product_name, p.category,
                        p.description, p.unit, p.unit_cost, p.lead_time_days,
                        p.safety_certification, p.compliance_standard,
                        p.requires_calibration, p.calibration_frequency_days,
                        
                        w.id as warehouse_id, w.name as warehouse_name, 
                        w.location, w.capacity, w.current_utilization,
                        w.temperature_controlled, w.security_level, w.specialty,
                        
                        s.current_quantity, s.reserved_quantity, s.reorder_point,
                        s.min_stock_level, s.max_stock_level, s.expiry_date,
                        s.last_audit_date, s.last_updated,
                        ROW_NUMBER() OVER (PARTITION BY p.id ORDER BY s.current_quantity DESC) as rn
                    FROM stock s
                    JOIN products p ON s.product_id = p.id
                    JOIN warehouses w ON s.warehouse_id = w.id
                    WHERE p.id IN ({placeholders})
                )
                SELECT * FROM ranked_stock WHERE rn = 1
                """
                params = tuple(product_ids)
            
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                
                stock_items = []
                for row in rows:
                    product = Product(
                        id=row['product_id'],
                        name=row['product_name'],
                        category=row['category'],
                        description=row['description'],
                        unit=row['unit'],
                        unit_cost=float(row['unit_cost']),
                        lead_time_days=row['lead_time_days'],
                        safety_certification=row['safety_certification'],
                        compliance_standard=row['compliance_standard'],
                        requires_calibration=row['requires_calibration'],
                        calibration_frequency_days=row['calibration_frequency_days'],
                        min_storage_temperature=None,
                        max_storage_temperature=None
                    )
                    
                    warehouse = Warehouse(
                        id=row['warehouse_id'],
                        name=row['warehouse_name'],
                        location=row['location'],
                        capacity=row['capacity'],
                        current_utilization=float(row['current_utilization']),
                        temperature_controlled=row['temperature_controlled'],
                        security_level=row['security_level'],
                        specialty=row['specialty']
                    )
                    
                    stock_item = StockItem(
                        product=product,
                        warehouse=warehouse,
                        current_quantity=row['current_quantity'],
                        reserved_quantity=row['reserved_quantity'],
                        reorder_point=row['reorder_point'],
                        min_stock_level=row['min_stock_level'],
                        max_stock_level=row['max_stock_level'],
                        expiry_date=row['expiry_date'],
                        last_audit_date=row['last_audit_date'],
                        last_updated=row['last_updated']
                    )
                    
                    stock_items.append(stock_item)
                
                return stock_items
                
        except Exception as e:
            logger.error(f"Error getting batch stock: {str(e)}")
            return []
    
    async def get_critical_alerts(self, warehouse_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Obtener alertas críticas de stock"""
        try:
            pool = get_postgres_pool()
            
            if warehouse_id:
                query = """
                SELECT 
                    p.id as product_id, p.name as product_name, p.category,
                    w.id as warehouse_id, w.name as warehouse_name,
                    s.current_quantity, s.reserved_quantity,
                    s.reorder_point, s.min_stock_level, s.expiry_date,
                    CASE 
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.min_stock_level THEN 'CRITICO'
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.reorder_point THEN 'ALTO'
                        WHEN s.expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN 'VENCIMIENTO'
                        ELSE 'NORMAL'
                    END as alert_level,
                    CASE 
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.min_stock_level 
                            THEN 'Stock por debajo del nivel mínimo'
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.reorder_point 
                            THEN 'Stock por debajo del punto de reorden'
                        WHEN s.expiry_date <= CURRENT_DATE + INTERVAL '30 days' 
                            THEN 'Producto próximo a vencer'
                        ELSE ''
                    END as alert_message
                FROM stock s
                JOIN products p ON s.product_id = p.id
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE w.id = $1 AND (
                    (s.current_quantity - s.reserved_quantity) <= s.reorder_point
                    OR s.expiry_date <= CURRENT_DATE + INTERVAL '30 days'
                )
                ORDER BY alert_level DESC
                """
                params = (warehouse_id,)
            else:
                query = """
                SELECT 
                    p.id as product_id, p.name as product_name, p.category,
                    w.id as warehouse_id, w.name as warehouse_name,
                    s.current_quantity, s.reserved_quantity,
                    s.reorder_point, s.min_stock_level, s.expiry_date,
                    CASE 
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.min_stock_level THEN 'CRITICO'
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.reorder_point THEN 'ALTO'
                        WHEN s.expiry_date <= CURRENT_DATE + INTERVAL '30 days' THEN 'VENCIMIENTO'
                        ELSE 'NORMAL'
                    END as alert_level,
                    CASE 
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.min_stock_level 
                            THEN 'Stock por debajo del nivel mínimo'
                        WHEN (s.current_quantity - s.reserved_quantity) <= s.reorder_point 
                            THEN 'Stock por debajo del punto de reorden'
                        WHEN s.expiry_date <= CURRENT_DATE + INTERVAL '30 days' 
                            THEN 'Producto próximo a vencer'
                        ELSE ''
                    END as alert_message
                FROM stock s
                JOIN products p ON s.product_id = p.id
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE (s.current_quantity - s.reserved_quantity) <= s.reorder_point
                    OR s.expiry_date <= CURRENT_DATE + INTERVAL '30 days'
                ORDER BY alert_level DESC
                """
                params = ()
            
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting critical alerts: {str(e)}")
            return []