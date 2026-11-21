
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


DOCKER_IMAGE = "code-review-test:latest"

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120

MAX_FILES = 200
MAX_FILE_SIZE = 500_000
MAX_TOTAL_SIZE = 10_000_000


def validate_repository_path(filename: str) -> PurePosixPath:
    """Validate a repository-relative file path."""

    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Filename cannot be empty")

    path = PurePosixPath(filename)

    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in filename
        or "\x00" in filename
        or not path.parts
        or path.suffix.lower() != ".py"
    ):
        raise ValueError("Invalid Python file path")

    return path


def run_automated_tests(
    fixed_code: str,
    filename: str,
    repository_files: dict[str, str],
    timeout: int = DEFAULT_TIMEOUT,
):
    """
    Run repository tests against Claude's proposed code
    inside a restricted Docker container.

    repository_files must contain repository-relative paths
    and their text contents at the original PR commit.
    """

    # STEP 1: INPUT VALIDATION

    if not isinstance(fixed_code, str) or not fixed_code.strip():
        raise ValueError("Fixed code cannot be empty")

    source_path = validate_repository_path(filename)

    if not isinstance(repository_files, dict) or not repository_files:
        raise ValueError("Repository files are required")

    if len(repository_files) > MAX_FILES:
        raise ValueError("Repository snapshot contains too many files")

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or timeout <= 0
        or timeout > MAX_TIMEOUT
    ):
        raise ValueError(
            f"Timeout must be between 1 and {MAX_TIMEOUT} seconds"
        )

    # STEP 2: VALIDATE AND PREPARE REPOSITORY FILES

    prepared_files = {}
    total_size = 0

    for filename_in_repo, content in repository_files.items():

        if not isinstance(filename_in_repo, str):
            raise ValueError("Repository file paths must be strings")

        relative_path = PurePosixPath(filename_in_repo)

        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not relative_path.parts
            or "\\" in filename_in_repo
            or "\x00" in filename_in_repo
        ):
            raise ValueError("Invalid repository file path")

        # Do not include Git metadata, virtual environments,
        # secrets, or dependency caches in the test workspace.
        blocked_parts = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
        }

        if any(part in blocked_parts for part in relative_path.parts):
            continue

        if relative_path.name.lower() in {
            ".env",
            ".env.local",
            ".env.production",
        }:
            continue

        if not isinstance(content, str):
            raise ValueError("Repository file contents must be strings")

        content_size = len(content.encode("utf-8"))

        if content_size > MAX_FILE_SIZE:
            continue

        total_size += content_size

        if total_size > MAX_TOTAL_SIZE:
            raise ValueError("Repository snapshot exceeds size limit")

        prepared_files[relative_path.as_posix()] = content

    # STEP 3: CHECK THAT TEST FILES EXIST

    test_files = [
        path
        for path in prepared_files
        if path.endswith(".py")
        and (
            PurePosixPath(path).name.startswith("test_")
            or PurePosixPath(path).name.endswith("_test.py")
            or "tests" in PurePosixPath(path).parts[:-1]
        )
    ]

    if not test_files:
        return {
            "status": "not_found",
            "return_code": None,
            "test_output": "",
            "error_output": (
                "No conventional Python test files were found "
                "in the repository snapshot."
            ),
        }

    # STEP 4: CREATE TEMPORARY REPOSITORY WORKSPACE

    with tempfile.TemporaryDirectory(
        prefix="code_review_test_"
    ) as temp_dir:

        workspace = Path(temp_dir).resolve()

        for relative_name, content in prepared_files.items():

            destination = workspace.joinpath(*PurePosixPath(relative_name).parts)

            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")

        # Replace the original source file with Claude's fixed code.
        fixed_source = workspace.joinpath(*source_path.parts)

        fixed_source.parent.mkdir(parents=True, exist_ok=True)
        fixed_source.write_text(fixed_code, encoding="utf-8")

        # STEP 5: PREPARE RESTRICTED DOCKER COMMAND

        command = [
            "docker",
            "run",
            "--rm",
            "--network", "none",
            "--memory", "256m",
            "--cpus", "1",
            "--pids-limit", "64",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--mount",
            (
                f"type=bind,source={workspace},"
                "target=/workspace,readonly"
            ),
            "--workdir", "/workspace",
            DOCKER_IMAGE,
            "python", "-m", "pytest",
            "-v",
            "-p", "no:cacheprovider",
            ".",
        ]

        # STEP 6: EXECUTE REPOSITORY TESTS

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "status": (
                    "passed"
                    if result.returncode == 0
                    else "failed"
                ),
                "return_code": result.returncode,
                "test_output": result.stdout,
                "error_output": result.stderr,
                "test_files": test_files,
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "return_code": None,
                "test_output": "",
                "error_output": (
                    f"Tests exceeded the {timeout}-second limit."
                ),
                "test_files": test_files,
            }

        except FileNotFoundError as error:
            raise RuntimeError(
                "Docker command not found. Check Docker Desktop."
            ) from error

        except subprocess.SubprocessError as error:
            raise RuntimeError(
                f"Docker test execution failed: {error}"
            ) from error

        except OSError as error:
            raise RuntimeError(
                f"Operating system error during Docker execution: {error}"
            ) from error
