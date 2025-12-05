import redis.asyncio as redis
import json
import logging
from typing import Optional, Any
from datetime import timedelta
from src.core.cache import get_redis

logger = logging.getLogger(__name__)

class CacheRepository:
    """Repositorio para operaciones de cache"""
    
    def __init__(self):
        self.redis = get_redis()
        self.default_ttl = timedelta(seconds=30)
    
    async def get_stock_cache(self, product_id: str, warehouse_id: Optional[str] = None) -> Optional[dict]:
        """Obtener stock del cache"""
        try:
            key = self._generate_stock_key(product_id, warehouse_id)
            cached_data = await self.redis.get(key)
            
            if cached_data:
                logger.debug(f"Cache hit for {key}")
                return json.loads(cached_data)
            
            logger.debug(f"Cache miss for {key}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting from cache: {str(e)}")
            return None
    
    async def set_stock_cache(self, product_id: str, warehouse_id: Optional[str], data: dict, ttl: Optional[timedelta] = None):
        """Guardar stock en cache"""
        try:
            key = self._generate_stock_key(product_id, warehouse_id)
            ttl = ttl or self.default_ttl
            
            await self.redis.setex(
                key,
                int(ttl.total_seconds()),
                json.dumps(data, default=str)
            )
            logger.debug(f"Cache set for {key} with TTL {ttl}")
            
        except Exception as e:
            logger.error(f"Error setting cache: {str(e)}")
    
    async def invalidate_stock_cache(self, product_id: str, warehouse_id: Optional[str] = None):
        """Invalidar cache de stock"""
        try:
            if warehouse_id:
                key = self._generate_stock_key(product_id, warehouse_id)
                await self.redis.delete(key)
                logger.info(f"Invalidated cache for {key}")
            else:
                pattern = f"stock:{product_id}:*"
                keys = await self.redis.keys(pattern)
                if keys:
                    await self.redis.delete(*keys)
                    logger.info(f"Invalidated {len(keys)} cache keys for product {product_id}")
                    
        except Exception as e:
            logger.error(f"Error invalidating cache: {str(e)}")
    
    async def get_rate_limit(self, identifier: str) -> int:
        """Obtener contador de rate limiting"""
        try:
            key = f"ratelimit:{identifier}"
            count = await self.redis.get(key)
            return int(count) if count else 0
        except:
            return 0
    
    async def increment_rate_limit(self, identifier: str, window_seconds: int = 60) -> int:
        """Incrementar contador de rate limiting"""
        try:
            key = f"ratelimit:{identifier}"
            
            # Usar pipeline para atomicidad
            async with self.redis.pipeline() as pipe:
                await pipe.incr(key)
                await pipe.expire(key, window_seconds)
                results = await pipe.execute()
            
            return results[0]
        except Exception as e:
            logger.error(f"Error incrementing rate limit: {str(e)}")
            return 0
    
    def _generate_stock_key(self, product_id: str, warehouse_id: Optional[str]) -> str:
        """Generar clave de cache para stock"""
        warehouse_key = warehouse_id or "all"
        return f"stock:{product_id}:{warehouse_key}"