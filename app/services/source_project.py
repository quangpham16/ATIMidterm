"""Validate a small, flat Python project without importing or running it."""

import keyword


MAX_SOURCE_FILES = 20
MAX_SOURCE_FILE_BYTES = 128 * 1024
MAX_SOURCE_TOTAL_BYTES = 512 * 1024


def validate_source_project(
    source_files: dict[str, str], source_entrypoint: str = ""
) -> tuple[dict[str, str], str]:
    """Return a validated copy and entry filename; reject input before LLM calls."""
    if not isinstance(source_files, dict) or not source_files:
        raise ValueError("Upload at least one Python source file")
    if len(source_files) > MAX_SOURCE_FILES:
        raise ValueError(f"Upload at most {MAX_SOURCE_FILES} Python source files")

    validated = {}
    filenames = set()
    total_bytes = 0
    for filename, content in source_files.items():
        if (
            not isinstance(filename, str)
            or not filename.endswith(".py")
            or "/" in filename
            or "\\" in filename
            or not filename[:-3].isascii()
            or not filename[:-3].isidentifier()
            or keyword.iskeyword(filename[:-3])
        ):
            raise ValueError("Source filenames must be flat .py filenames with valid ASCII Python module names")
        if filename.casefold() in {"test_generated.py", "pytest.py", "__main__.py"}:
            raise ValueError(f"{filename} is reserved for the generated tests and pytest runner")
        if filename.casefold() in filenames:
            raise ValueError("Source filenames must be unique, ignoring letter case")
        filenames.add(filename.casefold())
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{filename}: source file must not be empty")
        try:
            size = len(content.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError(f"{filename}: source file must contain valid UTF-8 text") from exc
        if size > MAX_SOURCE_FILE_BYTES:
            raise ValueError(f"{filename}: source file must be at most 128 KiB")
        total_bytes += size
        if total_bytes > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError("Python source files must be at most 512 KiB in total")
        try:
            # Compilation checks syntax and invalid contexts, without executing code.
            compile(content, filename, "exec", dont_inherit=True)
        except SyntaxError as exc:
            raise ValueError(f"{filename}: Python source has a syntax error at line {exc.lineno}: {exc.msg}") from exc
        validated[filename] = content

    if not isinstance(source_entrypoint, str):
        raise ValueError("Choose an uploaded Python filename as the entry module")
    entrypoint = source_entrypoint or next(iter(validated))
    if entrypoint not in validated:
        raise ValueError("The entry module must be one of the uploaded Python files")
    return validated, entrypoint
