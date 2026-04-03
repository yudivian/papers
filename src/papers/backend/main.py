from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from papers.backend.api import api_router
from papers.backend.tasks import manager
from castor.server import Server

import threading

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Instanciar el servidor de ejecución de Castor
    # manager_path es el string para que los procesos hijos re-importen el manager
    server = Server(
        manager=manager,
        workers=2, 
        threads=4, 
        manager_path="papers.backend.tasks:manager"
    )
    
    # 2. El método .serve() es un bucle infinito bloqueante. 
    # Lo lanzamos en un hilo daemon para que viva con la app de FastAPI.
    worker_thread = threading.Thread(target=server.serve, daemon=True)
    worker_thread.start()
    
    yield
    
    # 3. Al apagar la app, detenemos los executors del servidor
    server.stop()

app = FastAPI(
    title="Papers AI Engine",
    description="Autonomous Academic Research and Semantic Search API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")