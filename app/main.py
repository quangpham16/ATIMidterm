from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.config import FRONTEND_ORIGINS
from app.routers import auth, export, projects, testcases

app = FastAPI(title="AI Test Case Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(testcases.router)
app.include_router(export.router)
app.include_router(auth.router)
app.include_router(projects.router)
init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
