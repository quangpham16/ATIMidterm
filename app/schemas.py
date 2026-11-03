from typing import Any, Literal

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    swagger: dict[str, Any] = Field(..., description="OpenAPI/Swagger document")
    source_code: str = ""


class TestCase(BaseModel):
    id: str
    title: str
    api_method: str = ""
    endpoint: str = ""
    priority: str = "medium"
    test_type: str = "functional"
    prerequisites: list[str] = Field(default_factory=list)
    request_data: dict[str, Any] = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)
    expected_result: str
    expected_status_code: int | None = None


class GenerationResult(BaseModel):
    test_cases: list[TestCase]
    pytest_code: str
    api_test_cases: list[TestCase] = Field(default_factory=list)
    unit_test_cases: list[TestCase] = Field(default_factory=list)
    unit_pytest_code: str = ""
    unit_test_code: str = ""
    source_language: Literal["python", "javascript", "typescript"] = "python"
    unit_test_framework: str = ""


class ExportResponse(BaseModel):
    content: str
    media_type: str
    filename: str
