# service-inventory/src/api/routes/stock.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import structlog
import time

from src.application.use_cases.get_stock import GetStockUseCase
from src.application.use_cases.update_stock import UpdateStockUseCase
from src.infrastructure.repositories.stock_repository import PostgresStockRepository
from src.infrastructure.cache.redis_cache import RedisCache
from src.utils.metrics import record_metric
from src.utils.security import validate_jwt

router = APIRouter()
logger = structlog.get_logger()

# Modelos Pydantic
class StockQuery(BaseModel):
    product_id: str = Field(..., description="ID del producto", example="CASCO-001")
    warehouse_id: str = Field(None, description="ID de la bodega", example="BOD-01")

class StockResponse(BaseModel):
    product_id: str
    product_name: str
    category: str
    warehouse_id: str
    current_stock: int
    reserved_stock: int
    available_stock: int
    reorder_point: int
    safety_level: str
    certification: str
    last_updated: str
    needs_reorder: bool

class StockUpdate(BaseModel):
    product_id: str
    quantity_change: int
    operation: str = Field(..., pattern="^(ADD|REMOVE|SET)$")
    reason: str

# Dependencias
async def get_stock_repository():
    """Inyección de dependencias para el repositorio"""
    return PostgresStockRepository()

async def get_cache():
    """Inyección de dependencias para cache"""
    return RedisCache()

@router.post("/stock", response_model=StockResponse)
async def get_stock(
    query: StockQuery,
    background_tasks: BackgroundTasks,
    token: dict = Depends(validate_jwt),
    stock_repo = Depends(get_stock_repository),
    cache = Depends(get_cache)
):
    """Consulta el stock de un producto"""
    start_time = time.time()
    
    try:
        logger.info(
            "Consultando stock",
            product_id=query.product_id,
            warehouse_id=query.warehouse_id,
            user=token.get("username")
        )
        
        # Verificar cache
        cache_key = f"stock:{query.product_id}:{query.warehouse_id or 'all'}"
        cached_data = await cache.get(cache_key)
        
        if cached_data:
            response_time = (time.time() - start_time) * 1000
            record_metric("inventory_query_latency", response_time)
            record_metric("cache_hits", 1)
            
            # Registrar en background para no bloquear respuesta
            background_tasks.add_task(
                logger.info,
                "Consulta de stock desde cache",
                product_id=query.product_id,
                response_time=response_time
            )
            
            return cached_data
        
        # Ejecutar caso de uso
        use_case = GetStockUseCase(stock_repo, cache)
        stock_data = await use_case.execute(
            product_id=query.product_id,
            warehouse_id=query.warehouse_id
        )
        
        response_time = (time.time() - start_time) * 1000
        
        # Métricas
        record_metric("inventory_query_latency", response_time)
        record_metric("cache_misses", 1)
        
        # Verificar ASR de latencia
        if response_time > 3000:
            record_metric("asr_latency_violation", 1)
            logger.warning(
                "Consulta lenta detectada",
                product_id=query.product_id,
                response_time=response_time,
                threshold=3000
            )
        
        # Tareas en background
        background_tasks.add_task(
            cache.set,
            cache_key,
            stock_data.dict(),
            ttl=30  # 30 segundos TTL
        )
        
        background_tasks.add_task(
            logger.info,
            "Consulta de stock completada",
            product_id=query.product_id,
            response_time=response_time,
            meets_asr=response_time < 3000
        )
        
        return stock_data
        
    except ValueError as e:
        logger.error("Error de validación", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en consulta de stock", error=str(e))
        record_metric("stock_query_errors", 1)
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@router.put("/stock")
async def update_stock(
    update: StockUpdate,
    token: dict = Depends(validate_jwt),
    stock_repo = Depends(get_stock_repository),
    cache = Depends(get_cache)
):
    """Actualiza el stock de un producto"""
    if token.get("role") not in ["admin", "warehouse_manager"]:
        raise HTTPException(
            status_code=403,
            detail="Permisos insuficientes para actualizar stock"
        )
    
    try:
        logger.info(
            "Actualizando stock",
            product_id=update.product_id,
            operation=update.operation,
            user=token.get("username")
        )
        
        # Ejecutar caso de uso
        use_case = UpdateStockUseCase(stock_repo, cache)
        result = await use_case.execute(
            product_id=update.product_id,
            quantity_change=update.quantity_change,
            operation=update.operation,
            user=token.get("username"),
            reason=update.reason
        )
        
        # Invalidar cache
        cache_keys = [
            f"stock:{update.product_id}:all",
            f"stock:{update.product_id}:*"
        ]
        for key in cache_keys:
            await cache.delete_pattern(key)
        
        record_metric("stock_updates", 1)
        
        return {
            "success": True,
            "message": "Stock actualizado correctamente",
            "new_quantity": result.new_quantity,
            "previous_quantity": result.previous_quantity
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error actualizando stock", error=str(e))
        raise HTTPException(status_code=500, detail="Error interno del servidor")

@router.get("/stock/health")
async def stock_health():
    """Health check específico del módulo de stock"""
    try:
        # Verificar conexión a base de datos
        from src.config.database import get_db_health
        db_health = await get_db_health()
        
        # Verificar cache
        from src.infrastructure.cache.redis_cache import get_cache_health
        cache_health = await get_cache_health()
        
        return {
            "status": "healthy",
            "database": db_health,
            "cache": cache_health,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error("Health check falló", error=str(e))
        raise HTTPException(status_code=503, detail="Servicio no saludable")