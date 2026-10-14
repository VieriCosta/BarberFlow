import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .migrations import migrate
from .auth import router as auth_router
from .booking import app as booking_router
from .finance import router as finance_router
from .schedule import router as schedule_router


@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


app = FastAPI(title="BarberFlow API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=os.getenv("BARBERFLOW_CORS_ORIGINS", "http://localhost:4200").split(","),
    allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Bootstrap-Key"])
app.include_router(auth_router)
app.include_router(booking_router)
app.include_router(finance_router)
app.include_router(schedule_router)

from .customer_portal import router as portal_router
from .notifications import router as notifications_router
app.include_router(portal_router)
app.include_router(notifications_router)

from .catalog import app as catalog_router
app.include_router(catalog_router)
