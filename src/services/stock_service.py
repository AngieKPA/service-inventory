import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.models.schemas import IndustrialStockResponse, CriticalAlert, BatchStockResponse
from src.models.domain import StockItem
from src.repositories.stock_repository import StockRepository
from src.repositories.cache_repository import CacheRepository
from src.core.cache import CircuitBreaker

logger = logging.getLogger(__name__)

class StockService:
    """Servicio de lógica de negocio para stock industrial"""
    
    def __init__(self):
        self.stock_repo = StockRepository()
        self.cache_repo = CacheRepository()
        self.circuit_breaker = CircuitBreaker(
            name="stock_service",
            failure_threshold=5,
            recovery_timeout=30
        )
    
    @CircuitBreaker
    async def get_industrial_stock(
        self, 
        product_id: str, 
        warehouse_id: Optional[str] = None,
        include_compliance: bool = False
    ) -> IndustrialStockResponse:
        """Obtener información de stock para producto industrial"""
        start_time = time.time()
        
        try:
            # 1. Intentar obtener del cache primero
            cache_key = f"{product_id}:{warehouse_id or 'all'}"
            cached_data = await self.cache_repo.get_stock_cache(product_id, warehouse_id)
            
            if cached_data:
                logger.info(f"Cache hit for {cache_key}")
                response_time = (time.time() - start_time) * 1000
                cached_data['response_time_ms'] = response_time
                cached_data['cache_hit'] = True
                return IndustrialStockResponse(**cached_data)
            
            # 2. Consultar base de datos
            logger.info(f"Cache miss, querying DB for {cache_key}")
            stock_item = await self.stock_repo.get_stock_item(product_id, warehouse_id)
            
            if not stock_item:
                raise ValueError(f"Producto {product_id} no encontrado")
            
            # 3. Calcular campos derivados
            days_to_expiry = stock_item.days_to_expiry
            expiry_alert = stock_item.expiry_status if days_to_expiry else None
            
            suggested_order = None
            if stock_item.needs_reorder and stock_item.max_stock_level:
                suggested_order = stock_item.max_stock_level - stock_item.available_quantity
            
            # 4. Construir response
            response_data = {
                "product_id": stock_item.product.id,
                "product_name": stock_item.product.name,
                "category": stock_item.product.category,
                "description": stock_item.product.description,
                
                "warehouse_id": stock_item.warehouse.id,
                "warehouse_name": stock_item.warehouse.name,
                "warehouse_location": stock_item.warehouse.location,
                
                "current_stock": stock_item.current_quantity,
                "reserved_stock": stock_item.reserved_quantity,
                "available_stock": stock_item.available_quantity,
                "unit": stock_item.product.unit,
                
                "safety_level": self._calculate_safety_level(stock_item),
                "reorder_point": stock_item.reorder_point,
                "min_stock_level": stock_item.min_stock_level,
                "max_stock_level": stock_item.max_stock_level,
                
                "certification": stock_item.product.safety_certification if include_compliance else None,
                "compliance_standard": stock_item.product.compliance_standard if include_compliance else None,
                "expiry_date": stock_item.expiry_date if include_compliance else None,
                "days_to_expiry": days_to_expiry if include_compliance else None,
                "requires_calibration": stock_item.product.requires_calibration,
                "last_calibration_date": None,  # Implementar en futura versión
                
                "needs_reorder": stock_item.needs_reorder,
                "expiry_alert": expiry_alert,
                "suggested_order_quantity": suggested_order,
                
                "response_time_ms": (time.time() - start_time) * 1000,
                "cache_hit": False,
                "last_updated": stock_item.last_updated
            }
            
            response = IndustrialStockResponse(**response_data)
            
            # 5. Guardar en cache (excluir campos sensibles/time-sensitive)
            cache_data = response_data.copy()
            cache_data.pop('response_time_ms', None)
            cache_data.pop('last_updated', None)
            
            await self.cache_repo.set_stock_cache(product_id, warehouse_id, cache_data)
            
            # 6. Log analytics (asíncrono)
            await self._log_stock_query(
                product_id=product_id,
                warehouse_id=warehouse_id,
                response_time=response_data['response_time_ms'],
                cache_hit=False
            )
            
            logger.info(f"Stock query completed for {product_id} in {response_data['response_time_ms']:.2f}ms")
            
            return response
            
        except Exception as e:
            logger.error(f"Error in get_industrial_stock: {str(e)}", exc_info=True)
            raise
    
    async def get_batch_stock(self, requests: List[Dict[str, Any]]) -> BatchStockResponse:
        """Obtener stock para múltiples productos"""
        start_time = time.time()
        
        try:
            results = []
            product_ids = [req['product_id'] for req in requests]
            
            # Obtener todos los productos en batch
            warehouse_id = requests[0].get('warehouse_id') if len(requests) == 1 else None
            stock_items = await self.stock_repo.get_batch_stock(product_ids, warehouse_id)
            
            # Mapear resultados por product_id
            stock_by_product = {item.product.id: item for item in stock_items}
            
            for req in requests:
                product_id = req['product_id']
                stock_item = stock_by_product.get(product_id)
                
                if stock_item:
                    response_data = self._stock_item_to_response(stock_item)
                    response_data['response_time_ms'] = 0  # Se calcula al final
                    results.append(IndustrialStockResponse(**response_data))
            
            # Calcular métricas generales
            total_time = (time.time() - start_time) * 1000
            avg_time = total_time / len(results) if results else 0
            
            for result in results:
                result.response_time_ms = avg_time
            
            products_needing_reorder = sum(1 for r in results if r.needs_reorder)
            critical_alerts = sum(1 for r in results if r.expiry_alert in ['VENCIDO', 'VENCE EN'])
            
            return BatchStockResponse(
                results=results,
                total_products=len(results),
                products_needing_reorder=products_needing_reorder,
                critical_alerts=critical_alerts,
                average_response_time_ms=avg_time,
                generated_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Error in get_batch_stock: {str(e)}")
            raise
    
    async def get_critical_alerts(self, warehouse_id: Optional[str] = None) -> List[CriticalAlert]:
        """Obtener alertas críticas"""
        try:
            db_alerts = await self.stock_repo.get_critical_alerts(warehouse_id)
            
            alerts = []
            for alert in db_alerts:
                critical_alert = CriticalAlert(
                    alert_id=f"alert_{alert['product_id']}_{datetime.now().timestamp()}",
                    product_id=alert['product_id'],
                    product_name=alert['product_name'],
                    warehouse_id=alert['warehouse_id'],
                    alert_type=self._determine_alert_type(alert),
                    severity=alert['alert_level'],
                    current_value=alert['current_quantity'] - alert['reserved_quantity'],
                    threshold_value=alert['min_stock_level'],
                    message=alert['alert_message'],
                    suggested_action=self._generate_suggested_action(alert),
                    timestamp=datetime.now()
                )
                alerts.append(critical_alert)
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error in get_critical_alerts: {str(e)}", exc_info=True)
            raise
    
    async def update_stock_quantity(
        self, 
        product_id: str, 
        quantity_change: int, 
        operation: str,
        warehouse_id: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Actualizar cantidad de stock"""
        try:
            # Verificar que el cambio sea válido
            current_stock = await self.stock_repo.get_stock_item(product_id, warehouse_id)
            
            if not current_stock:
                raise ValueError(f"Producto {product_id} no encontrado en warehouse {warehouse_id}")
            
            new_quantity = current_stock.current_quantity + quantity_change
            
            if new_quantity < 0:
                raise ValueError(f"Stock no puede ser negativo. Cantidad actual: {current_stock.current_quantity}")
            
            if new_quantity > current_stock.max_stock_level:
                logger.warning(f"Stock excede nivel máximo para producto {product_id}")
            
            # Actualizar en base de datos
            await self.stock_repo.update_stock_quantity(
                product_id=product_id,
                warehouse_id=warehouse_id,
                new_quantity=new_quantity,
                operation=operation,
                user_id=user_id
            )
            
            # Invalidar cache
            await self.cache_repo.invalidate_stock_cache(product_id, warehouse_id)
            
            # Generar evento de stock actualizado
            await self._emit_stock_update_event(
                product_id=product_id,
                warehouse_id=warehouse_id,
                old_quantity=current_stock.current_quantity,
                new_quantity=new_quantity,
                operation=operation,
                user_id=user_id
            )
            
            # Verificar si se disparan alertas
            await self._check_and_trigger_alerts(
                product_id=product_id,
                warehouse_id=warehouse_id,
                current_quantity=new_quantity
            )
            
            return {
                "success": True,
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "previous_quantity": current_stock.current_quantity,
                "new_quantity": new_quantity,
                "quantity_change": quantity_change,
                "operation": operation,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in update_stock_quantity: {str(e)}", exc_info=True)
            raise
    
    async def check_compliance_status(self, product_id: str, warehouse_id: str) -> Dict[str, Any]:
        """Verificar estado de cumplimiento normativo"""
        try:
            stock_item = await self.stock_repo.get_stock_item(product_id, warehouse_id)
            
            if not stock_item:
                raise ValueError(f"Producto {product_id} no encontrado")
            
            compliance_checks = {
                "requires_certification": bool(stock_item.product.safety_certification),
                "certification_valid": True,  # Implementar lógica de validación real
                "requires_calibration": stock_item.product.requires_calibration,
                "calibration_due": False,  # Implementar lógica real
                "expiry_status": stock_item.expiry_status,
                "days_to_expiry": stock_item.days_to_expiry,
                "compliance_standard": stock_item.product.compliance_standard,
                "requires_special_storage": stock_item.product.special_storage_requirements,
                "storage_compliant": True,  # Verificar condiciones de almacenamiento
            }
            
            compliance_passed = all([
                compliance_checks["certification_valid"],
                not compliance_checks["calibration_due"],
                compliance_checks["expiry_status"] != "VENCIDO",
                compliance_checks["storage_compliant"]
            ])
            
            return {
                "product_id": product_id,
                "compliance_passed": compliance_passed,
                "checks": compliance_checks,
                "failed_checks": [
                    key for key, value in compliance_checks.items() 
                    if not value and key in ["certification_valid", "storage_compliant"] or
                    (key == "expiry_status" and value == "VENCIDO") or
                    (key == "calibration_due" and value == True)
                ],
                "recommendations": self._generate_compliance_recommendations(compliance_checks),
                "last_checked": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in check_compliance_status: {str(e)}", exc_info=True)
            raise
    
    async def get_warehouse_summary(self, warehouse_id: str) -> Dict[str, Any]:
        """Obtener resumen del warehouse"""
        try:
            # Intentar cache primero
            cache_key = f"warehouse_summary:{warehouse_id}"
            cached = await self.cache_repo.get(cache_key)
            
            if cached:
                return cached
            
            summary = await self.stock_repo.get_warehouse_summary(warehouse_id)
            
            # Calcular KPIs
            total_value = sum(item['current_quantity'] * item['unit_price'] for item in summary)
            total_items = sum(item['current_quantity'] for item in summary)
            
            critical_items = [
                item for item in summary 
                if (item['available_quantity'] <= item['min_stock_level'] * 1.5) or
                item['expiry_status'] == "VENCIDO"
            ]
            
            expiring_soon = [
                item for item in summary 
                if item['days_to_expiry'] and item['days_to_expiry'] <= 30
            ]
            
            result = {
                "warehouse_id": warehouse_id,
                "total_products": len(summary),
                "total_items": total_items,
                "total_value": total_value,
                "critical_items_count": len(critical_items),
                "expiring_soon_count": len(expiring_soon),
                "products_needing_reorder": len([item for item in summary if item['needs_reorder']]),
                "top_products": sorted(summary, key=lambda x: x['current_quantity'], reverse=True)[:10],
                "critical_items": critical_items[:5],
                "expiring_items": expiring_soon[:5],
                "generated_at": datetime.now().isoformat()
            }
            
            # Cache por 5 minutos
            await self.cache_repo.set(cache_key, result, ttl=300)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in get_warehouse_summary: {str(e)}", exc_info=True)
            raise
    
    # ==================== MÉTODOS PRIVADOS ====================
    
    def _calculate_safety_level(self, stock_item: StockItem) -> str:
        """Calcular nivel de seguridad del stock"""
        available = stock_item.available_quantity
        
        if available <= stock_item.min_stock_level:
            return "CRÍTICO"
        elif available <= stock_item.reorder_point:
            return "BAJO"
        elif available <= stock_item.max_stock_level * 0.5:
            return "MEDIO"
        else:
            return "ALTO"
    
    def _determine_alert_type(self, alert_data: Dict[str, Any]) -> str:
        """Determinar tipo de alerta"""
        if alert_data['available_quantity'] <= alert_data['min_stock_level']:
            return "STOCK_MINIMO"
        elif alert_data['expiry_status'] == "VENCIDO":
            return "PRODUCTO_VENCIDO"
        elif alert_data['expiry_status'] == "VENCE_EN" and alert_data['days_to_expiry'] <= 7:
            return "PRONTO_A_VENCER"
        elif alert_data['current_quantity'] >= alert_data['max_stock_level'] * 0.95:
            return "SOBRESTOCK"
        else:
            return "OTRO"
    
    def _generate_suggested_action(self, alert_data: Dict[str, Any]) -> str:
        """Generar acción sugerida basada en alerta"""
        alert_type = self._determine_alert_type(alert_data)
        
        actions = {
            "STOCK_MINIMO": f"Reordenar {alert_data['max_stock_level'] - alert_data['available_quantity']} unidades",
            "PRODUCTO_VENCIDO": "Retirar del inventario inmediatamente",
            "PRONTO_A_VENCER": f"Usar en los próximos {alert_data['days_to_expiry']} días o retirar",
            "SOBRESTOCK": f"Reducir pedidos. Nivel actual: {alert_data['current_quantity']}/{alert_data['max_stock_level']}",
            "OTRO": "Revisar manualmente"
        }
        
        return actions.get(alert_type, "Revisar manualmente")
    
    def _stock_item_to_response(self, stock_item: StockItem) -> Dict[str, Any]:
        """Convertir StockItem a diccionario de respuesta"""
        return {
            "product_id": stock_item.product.id,
            "product_name": stock_item.product.name,
            "warehouse_id": stock_item.warehouse.id,
            "warehouse_name": stock_item.warehouse.name,
            "current_stock": stock_item.current_quantity,
            "reserved_stock": stock_item.reserved_quantity,
            "available_stock": stock_item.available_quantity,
            "safety_level": self._calculate_safety_level(stock_item),
            "reorder_point": stock_item.reorder_point,
            "min_stock_level": stock_item.min_stock_level,
            "max_stock_level": stock_item.max_stock_level,
            "expiry_date": stock_item.expiry_date,
            "days_to_expiry": stock_item.days_to_expiry,
            "expiry_alert": stock_item.expiry_status if stock_item.days_to_expiry else None,
            "needs_reorder": stock_item.needs_reorder,
            "requires_calibration": stock_item.product.requires_calibration
        }
    
    async def _log_stock_query(
        self, 
        product_id: str, 
        warehouse_id: Optional[str], 
        response_time: float,
        cache_hit: bool
    ):
        """Log analytics de consulta de stock"""
        # En producción, enviar a sistema de analytics
        logger.info(
            f"Stock Query Analytics - "
            f"product_id: {product_id}, "
            f"warehouse_id: {warehouse_id or 'all'}, "
            f"response_time: {response_time:.2f}ms, "
            f"cache_hit: {cache_hit}"
        )
    
    async def _emit_stock_update_event(
        self,
        product_id: str,
        warehouse_id: str,
        old_quantity: int,
        new_quantity: int,
        operation: str,
        user_id: Optional[str]
    ):
        """Emitir evento de actualización de stock"""
        # En producción, publicar a message broker (Kafka/RabbitMQ)
        event = {
            "event_type": "STOCK_UPDATED",
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity,
            "delta": new_quantity - old_quantity,
            "operation": operation,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Stock event emitted: {event}")
    
    async def _check_and_trigger_alerts(
        self, 
        product_id: str, 
        warehouse_id: str, 
        current_quantity: int
    ):
        """Verificar y disparar alertas si es necesario"""
        # Lógica simplificada - en producción conectar con sistema de notificaciones
        stock_item = await self.stock_repo.get_stock_item(product_id, warehouse_id)
        
        if not stock_item:
            return
        
        if current_quantity <= stock_item.min_stock_level:
            logger.warning(
                f"ALERTA: Stock mínimo alcanzado para {product_id} en {warehouse_id}. "
                f"Cantidad actual: {current_quantity}, Mínimo: {stock_item.min_stock_level}"
            )
        
        if current_quantity >= stock_item.max_stock_level * 0.95:
            logger.warning(
                f"ALERTA: Sobrestock para {product_id} en {warehouse_id}. "
                f"Cantidad actual: {current_quantity}, Máximo: {stock_item.max_stock_level}"
            )
    
    def _generate_compliance_recommendations(self, checks: Dict[str, Any]) -> List[str]:
        """Generar recomendaciones de cumplimiento"""
        recommendations = []
        
        if not checks["certification_valid"]:
            recommendations.append("Renovar certificación de seguridad")
        
        if checks["calibration_due"]:
            recommendations.append("Calibrar equipo antes de su uso")
        
        if checks["expiry_status"] == "VENCIDO":
            recommendations.append("Retirar producto vencido del inventario")
        
        if not checks["storage_compliant"]:
            recommendations.append("Ajustar condiciones de almacenamiento según normativa")
        
        if checks["days_to_expiry"] and checks["days_to_expiry"] <= 30:
            recommendations.append(f"Planificar uso antes de {checks['days_to_expiry']} días")
        
        return recommendations if recommendations else ["Cumple con todas las normativas"]