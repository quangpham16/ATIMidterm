import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database import create_project, get_project, list_projects
from app.security import current_user

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: str
    suite_count: int


@router.post("", status_code=201, response_model=ProjectResponse)
def create(request: CreateProjectRequest, user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    project_id = str(uuid4())
    try:
        create_project(project_id, user["id"], request.name)
    except sqlite3.IntegrityError as exc:
        if any(project["name"].lower() == request.name.lower() for project in list_projects(user["id"])):
            raise HTTPException(status_code=409, detail="A project with this name already exists") from exc
        raise
    project = get_project(project_id, user["id"])
    if project is None:
        raise RuntimeError("Created project could not be loaded")
    return project


@router.get("", response_model=list[ProjectResponse])
def index(user: dict[str, str] = Depends(current_user)) -> list[dict[str, object]]:
    return list_projects(user["id"])


@router.get("/{project_id}", response_model=ProjectResponse)
def show(project_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    project = get_project(project_id, user["id"])
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
