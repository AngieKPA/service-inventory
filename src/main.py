# service-inventory/src/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import structlog
import time

from src.config.settings import settings
from src.config.database import init_db, close_db
from src.api.routes import stock, products, health
from src.api.middleware import MetricsMiddleware, LoggingMiddleware
from src.utils.logger import configure_logging
from src.utils.metrics import setup_metrics

# Configurar logging
configure_logging()
logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manejo del ciclo de vida de la aplicación"""
    # Startup
    logger.info("Iniciando servicio de inventario")
    await init_db()
    setup_metrics()
    
    yield
    
    # Shutdown
    logger.info("Cerrando servicio de inventario")
    await close_db()

# Crear aplicación FastAPI
app = FastAPI(
    title="Industrial Stock Inventory Service",
    description="API para gestión de inventario de productos de seguridad industrial",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
    lifespan=lifespan
)

# Middleware
app.add_middleware(CORSMiddleware, allow_origins=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)

# Rutas
app.include_router(stock.router, prefix="/api/v1", tags=["stock"])
app.include_router(products.router, prefix="/api/v1", tags=["products"])
app.include_router(health.router, prefix="/health", tags=["health"])

@app.get("/")
async def root():
    """Endpoint raíz"""
    return {
        "service": "Industrial Stock Inventory",
        "version": "1.0.0",
        "status": "operational",
        "environment": settings.environment
    }

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Manejador global de excepciones HTTP"""
    logger.error(
        "HTTP Exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        detail=exc.detail
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development"
    )