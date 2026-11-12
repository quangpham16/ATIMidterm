from uuid import uuid4
from typing import Literal

import json

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.database import delete_result, get_project, list_results, load_result, result_metadata, save_result
from app.security import current_user
from app.schemas import GenerationResult
from app.services.generator import generate_test_cases
from app.services.llm_client import GeminiClient
from app.services.source_project import (
    MAX_SOURCE_FILES,
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_TOTAL_BYTES,
    validate_source_project,
)

router = APIRouter(prefix="/testcases", tags=["testcases"])
def _parse_spec(filename: str, content: bytes) -> dict:
    try:
        parsed = yaml.safe_load(content.decode("utf-8")) if filename.lower().endswith((".yaml", ".yml")) else json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=400, detail="Swagger file must be valid JSON or YAML") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Swagger document must be a JSON/YAML object")
    return parsed


async def _read_source_files(files: list[UploadFile]) -> dict[str, str]:
    if len(files) > MAX_SOURCE_FILES:
        raise ValueError(f"Upload at most {MAX_SOURCE_FILES} Python files")
    sources = {}
    names = set()
    total_bytes = 0
    for file in files:
        name = file.filename or ""
        if name.casefold() in names:
            raise ValueError(f"Duplicate source filename: {name}")
        names.add(name.casefold())
        content = await file.read(MAX_SOURCE_FILE_BYTES + 1)
        if len(content) > MAX_SOURCE_FILE_BYTES:
            raise ValueError(f"{name}: source file exceeds 128 KiB")
        total_bytes += len(content)
        if total_bytes > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError("Source files exceed the total limit of 512 KiB")
        try:
            sources[name] = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name}: Python source files must use UTF-8 encoding") from exc
    return sources


@router.post("/generate")
async def generate(
    swagger_file: UploadFile | None = File(None),
    source_code: str = Form(""),
    source_language: Literal["python", "javascript", "typescript"] = Form("python"),
    project_id: str | None = Form(None),
    source_files: list[UploadFile] | None = File(None),
    source_entrypoint: str = Form(""),
    user: dict[str, str] = Depends(current_user),
) -> dict[str, object]:
    if swagger_file is None and not source_code.strip() and not source_files:
        raise HTTPException(
            status_code=400,
            detail="Upload a Swagger/OpenAPI file, provide raw source code, or upload Python source files",
        )
    project_id = project_id or None
    if project_id is not None and get_project(project_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    swagger = {}
    if swagger_file is not None:
        swagger = _parse_spec(swagger_file.filename or "swagger.json", await swagger_file.read())
    sources = {}
    try:
        if source_files:
            if source_language != "python":
                raise ValueError("Multiple source files are supported for Python only")
            if source_code.strip():
                raise ValueError("Use pasted source code or uploaded Python files, not both")
            sources, source_entrypoint = validate_source_project(
                await _read_source_files(source_files), source_entrypoint
            )
            result = await run_in_threadpool(
                generate_test_cases, swagger, source_code, GeminiClient(), source_language,
                source_files=sources, source_entrypoint=source_entrypoint,
            )
        else:
            if source_entrypoint:
                raise ValueError("Upload Python source files before choosing an entry file")
            result = await run_in_threadpool(generate_test_cases, swagger, source_code, GeminiClient(), source_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result_id = str(uuid4())
    if swagger_file is not None:
        title = (swagger_file.filename or "API test suite").replace("\\", "/").rsplit("/", 1)[-1][:120] or "API test suite"
    elif sources:
        title = f"{source_entrypoint} unit tests"
    else:
        language_name = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript"}[source_language]
        title = f"{language_name} unit tests"
    try:
        save_result(result_id, result, user["id"], title, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**result_metadata(result_id, user["id"]), **result.model_dump()}


@router.get("/history")
def history(project_id: str | None = Query(None), user: dict[str, str] = Depends(current_user)) -> list[dict[str, str | None]]:
    project_id = project_id or None
    if project_id is not None and get_project(project_id, user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list_results(user["id"], project_id)


@router.get("/{result_id}")
def read_saved_suite(result_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    metadata = result_metadata(result_id, user["id"])
    if metadata is None:
        raise HTTPException(status_code=404, detail="Saved suite not found")
    return {**metadata, **get_result(result_id, user).model_dump()}


@router.delete("/{result_id}")
def delete_saved_suite(result_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    if not delete_result(result_id, user["id"]):
        raise HTTPException(status_code=404, detail="Saved suite not found")
    return {"id": result_id, "status": "deleted"}


def get_result(result_id: str, user: dict[str, str]) -> GenerationResult:
    result = load_result(result_id, user["id"])
    if result is None:
        raise HTTPException(status_code=404, detail="Generated result not found")
    return result
