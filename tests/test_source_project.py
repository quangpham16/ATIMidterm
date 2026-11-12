"""Exercise project validation, prompt context and runnable cross-module tests."""

import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.services.generator import generate_test_cases
from app.services.prompt_builder import build_generation_prompt
from app.services.source_project import (
    MAX_SOURCE_FILE_BYTES,
    MAX_SOURCE_FILES,
    MAX_SOURCE_TOTAL_BYTES,
    validate_source_project,
)


SOURCE_FILES = {
    "student_service.py": (
        "from repository import RepositoryUnavailable, load_student\n\n"
        "def get_student(student_id):\n"
        "    try:\n"
        "        return load_student(student_id)\n"
        "    except RepositoryUnavailable as exc:\n"
        "        raise ValueError('repository unavailable') from exc\n"
    ),
    "repository.py": (
        "class RepositoryUnavailable(RuntimeError):\n"
        "    pass\n\n"
        "def load_student(student_id):\n"
        "    return {'id': student_id, 'name': 'Ada'}\n"
    ),
}

PROJECT_TEST_CODE = """import pytest
from unittest.mock import patch
import student_service as sut
from repository import RepositoryUnavailable


def test_get_student_uses_real_repository():
    assert sut.get_student('s1') == {'id': 's1', 'name': 'Ada'}


def test_get_student_translates_repository_exception():
    failure = RepositoryUnavailable('offline')
    with patch.object(sut, 'load_student', side_effect=failure) as dependency:
        with pytest.raises(ValueError, match='repository unavailable') as caught:
            sut.get_student('s1')
        assert caught.value.__cause__ is failure
        dependency.assert_called_once_with('s1')
"""

UNIT_CASES = [
    {
        "id": "UNIT-STUDENT-001", "title": "Loads a student", "api_method": "UNIT",
        "endpoint": "get_student", "expected_result": "Returns the repository student",
    },
    {
        "id": "UNIT-STUDENT-002", "title": "Translates a repository failure", "api_method": "UNIT",
        "endpoint": "get_student", "expected_result": "Raises ValueError caused by RepositoryUnavailable",
    },
]


def fake_client(code=PROJECT_TEST_CODE):
    return Mock(generate_json=Mock(return_value={
        "api_test_cases": [], "unit_test_cases": UNIT_CASES, "unit_test_code": code,
    }))


def test_validation_preserves_module_names_contents_and_default_entry():
    files, entry = validate_source_project(SOURCE_FILES)
    assert files == SOURCE_FILES
    assert files is not SOURCE_FILES
    assert entry == "student_service.py"
    assert validate_source_project(SOURCE_FILES, "repository.py")[1] == "repository.py"


@pytest.mark.parametrize("filename", [
    "../service.py", "nested/service.py", "nested\\service.py", "service.txt",
    "service.PY", "bad-name.py", "class.py", ".py", "test_generated.py", "TEST_GENERATED.py",
    "pytest.py", "PYTEST.py", "__main__.py", "__MAIN__.py", "K.py", "étudiant.py", "学生.py",
])
def test_rejects_unusable_or_reserved_module_names(filename):
    with pytest.raises(ValueError):
        validate_source_project({filename: "value = 1\n"})


def test_rejects_names_that_collide_on_case_insensitive_filesystems():
    with pytest.raises(ValueError, match="unique"):
        validate_source_project({"service.py": "value = 1", "Service.py": "value = 2"})


@pytest.mark.parametrize("source_files", [{}, None, [], {"service.py": "  \n"}, {"service.py": None}])
def test_rejects_empty_or_invalid_source_files(source_files):
    with pytest.raises(ValueError):
        validate_source_project(source_files)


def test_missing_entry_module_is_rejected_before_gemini():
    client = fake_client()
    with pytest.raises(ValueError, match="one of the uploaded"):
        generate_test_cases({}, "", client, source_files=SOURCE_FILES, source_entrypoint="missing.py")
    client.generate_json.assert_not_called()


@pytest.mark.parametrize("invalid_source", ["def broken(:", "return 1", "value = '\x00'"])
def test_invalid_python_file_is_rejected_before_gemini(invalid_source):
    client = fake_client()
    with pytest.raises(ValueError, match="repository.py: Python source has a syntax error"):
        generate_test_cases({}, "", client, source_files={**SOURCE_FILES, "repository.py": invalid_source})
    client.generate_json.assert_not_called()


def test_validation_does_not_execute_source(tmp_path):
    marker = tmp_path / "must_not_exist"
    files = {"service.py": f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"}
    assert validate_source_project(files)[0] == files
    assert not marker.exists()


def test_project_count_and_utf8_byte_limits():
    with pytest.raises(ValueError, match="at most 20"):
        validate_source_project({f"module_{i}.py": "value = 1" for i in range(MAX_SOURCE_FILES + 1)})
    # One comment is valid Python, but non-ASCII characters still cost UTF-8 bytes.
    with pytest.raises(ValueError, match="128 KiB"):
        validate_source_project({"service.py": "#" + "é" * (MAX_SOURCE_FILE_BYTES // 2)})
    content = "#" * MAX_SOURCE_FILE_BYTES
    with pytest.raises(ValueError, match="512 KiB"):
        validate_source_project({f"module_{i}.py": content for i in range(MAX_SOURCE_TOTAL_BYTES // MAX_SOURCE_FILE_BYTES + 1)})


@pytest.mark.parametrize("language, pasted_code", [("javascript", ""), ("typescript", ""), ("python", "value = 1")])
def test_rejects_non_python_project_or_combined_pasted_code_before_gemini(language, pasted_code):
    client = fake_client()
    with pytest.raises(ValueError):
        generate_test_cases({}, pasted_code, client, language, SOURCE_FILES)
    client.generate_json.assert_not_called()


def test_prompt_contains_complete_named_files_and_preserves_literal_placeholders():
    files = {**SOURCE_FILES, "labels.py": "LABEL = '{module} {python_module} {files} {code}'\n"}
    prompt = build_generation_prompt({}, "", "python", files, "student_service.py")
    block = prompt.split("<source_files>\n", 1)[1].split("\n</source_files>", 1)[0]
    assert json.loads(block) == files
    assert "import student_service as sut" in prompt
    assert "sut.load" in prompt
    assert "inter-module exceptions" in prompt
    assert "side_effect" in prompt
    assert "Never mock the entry target itself" in prompt


def test_generated_project_metadata_and_actual_target_are_preserved():
    client = fake_client()
    result = generate_test_cases({}, "", client, source_files=SOURCE_FILES)
    client.generate_json.assert_called_once()
    assert result.source_files == SOURCE_FILES
    assert result.source_entrypoint == "student_service.py"
    assert result.unit_test_code == result.pytest_code
    assert "import student_service as sut" in result.pytest_code
    assert "Keep student_service.py and its companion source files" in result.pytest_code


def test_wrong_target_import_is_repaired_using_original_project_and_cases():
    wrong_target = PROJECT_TEST_CODE.replace("import student_service as sut", "import source_under_test as sut")
    client = fake_client(wrong_target)
    client.generate_json.side_effect = [client.generate_json.return_value, {
        "api_test_cases": [], "unit_test_cases": [], "unit_test_code": PROJECT_TEST_CODE,
    }]
    result = generate_test_cases({}, "", client, source_files=SOURCE_FILES)
    assert client.generate_json.call_count == 2
    repair_prompt = client.generate_json.call_args.args[0]
    assert "import student_service as sut" in repair_prompt
    assert "did not call the source module (student_service)" in repair_prompt
    assert "repository.py" in repair_prompt
    assert [case.id for case in result.unit_test_cases] == [case["id"] for case in UNIT_CASES]
    assert "import student_service as sut" in result.unit_test_code


def test_target_import_without_a_real_target_call_is_rejected():
    client = fake_client("import student_service as sut\n\ndef test_no_target():\n    assert True\n")
    with pytest.raises(RuntimeError, match="did not call the source module"):
        generate_test_cases({}, "", client, source_files=SOURCE_FILES)
    assert client.generate_json.call_count == 3


def test_generated_cross_module_tests_run_and_detect_a_broken_exception_handler(tmp_path):
    result = generate_test_cases({}, "", fake_client(), source_files=SOURCE_FILES)
    for filename, code in result.source_files.items():
        (tmp_path / filename).write_text(code, encoding="utf-8")
    (tmp_path / "test_generated.py").write_text(result.pytest_code, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", "test_generated.py"]
    success = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert success.returncode == 0, success.stdout + success.stderr
    assert "2 passed" in success.stdout

    # Keep the syntax valid while breaking the inter-module exception contract.
    broken = SOURCE_FILES["student_service.py"].replace(
        "raise ValueError('repository unavailable') from exc", "return None"
    )
    (tmp_path / "student_service.py").write_text(broken, encoding="utf-8")
    failure = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert failure.returncode == 1, failure.stdout + failure.stderr
    assert "DID NOT RAISE" in failure.stdout
