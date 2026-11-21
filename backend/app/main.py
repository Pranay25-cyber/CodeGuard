
import logging

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.database.connection import engine, Base
from app.database import models

from app.routes.auth import router as auth_router
from app.routes.github_installations import router as github_installations_router
from app.routes.repositories import router as repository_router
from app.routes.github import router as github_router
from app.routes.reviews import router as reviews_router
from app.routes.fixes import router as fixes_router
from app.routes.dashboard import router as dashboard_router
from app.routes.code_editor import router as code_editor_router
import os
from app.routes.github_installations import (
    router as github_installations_router,
)

from starlette.middleware.sessions import SessionMiddleware
from app.routes.auth import router as auth_router
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# Initialize database tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")

except Exception:
    logger.exception("Database table initialization failed.")
    raise


# Create FastAPI application
app = FastAPI(
    title="AI Code Review Agent",
    description="Automated AI-powered code review system",
    version="1.0.0",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY"),
    session_cookie="code_review_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=True,  # Local development only
)


# Register API routers
app.include_router(repository_router)
app.include_router(github_router)
app.include_router(reviews_router)
app.include_router(fixes_router)
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(github_installations_router)
app.include_router(code_editor_router)

# Configure frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    logger.info("AI Code Review Agent started successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("AI Code Review Agent is shutting down.")


@app.get("/")
def home():
    logger.info("Home endpoint accessed.")

    return {
        "message": "Welcome to AI Code Review Agent",
        "status": "Running",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "AI Code Review Agent",
    }


@app.get("/health/db")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        logger.info("Database health check successful.")

        return {
            "status": "success",
            "database": "PostgreSQL",
            "message": "Database connection successful",
        }

    except Exception:
        logger.exception("Database health check failed.")

        return {
            "status": "error",
            "message": "Database connection failed",
        }
