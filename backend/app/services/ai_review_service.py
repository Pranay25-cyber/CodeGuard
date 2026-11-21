import json
import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def _safe_response_preview(text: str, limit: int = 300) -> str:
    """Return a short log preview with common secret formats redacted."""
    preview = (text or "")[:limit]

    patterns = [
        (
            r"(?i)(api[_ -]?key|token|password|secret)(\s*[:=]\s*)[^,\s\"']+",
            r"\1\2[REDACTED]",
        ),
        (r"sk-ant-[A-Za-z0-9_-]+", "[REDACTED_ANTHROPIC_KEY]"),
        (r"gh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED_GITHUB_TOKEN]"),
    ]

    for pattern, replacement in patterns:
        preview = re.sub(pattern, replacement, preview)

    return preview.replace("\r", " ").replace("\n", " ")


def _clean_model_json_text(text: str) -> str:
    """
    Remove common non-printing formatting characters that can be introduced
    when model output is copied or serialized.

    This deliberately does not attempt to repair arbitrary malformed JSON.
    """
    text = (text or "").replace("\ufeff", "")
    text = text.replace("\u200b", "").replace("\u200c", "")
    text = text.replace("\u200d", "").replace("\u2060", "")
    return text.strip()


def _extract_json_object(response_text: str, response_id: str, stop_reason: str):
    """Extract and decode the first JSON object from Claude's response."""
    cleaned_response = _clean_model_json_text(response_text)

    # Handle a response wrapped in a Markdown code fence.
    if cleaned_response.startswith("```"):
        lines = cleaned_response.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_response = _clean_model_json_text("\n".join(lines))

    json_start = cleaned_response.find("{")
    if json_start == -1:
        raise ValueError(
            "Claude response did not contain a JSON object. "
            f"Stop reason: {stop_reason}; response ID: {response_id}; "
            f"response length: {len(response_text)}"
        )

    json_text = _clean_model_json_text(cleaned_response[json_start:])

    # raw_decode does not skip leading whitespace. json_text starts at "{",
    # but lstrip is retained defensively in case the extraction changes later.
    json_text = json_text.lstrip()

    try:
        result, parsed_end = json.JSONDecoder().raw_decode(json_text)
        return result

    except json.JSONDecodeError as exc:
        prefix = json_text[:40]
        logger.error(
            "Claude JSON character diagnostic: prefix=%r codepoints=%s",
            prefix,
            [f"U+{ord(char):04X}" for char in prefix],
        )

        preview = _safe_response_preview(json_text, limit=300)
        logger.error(
            "Claude review response is not valid JSON. "
            "parser_error=%s position=%s stop_reason=%s "
            "response_id=%s response_preview=%r",
            exc.msg,
            exc.pos,
            stop_reason,
            response_id,
            preview,
        )

        raise ValueError(
            "Claude returned malformed or incomplete JSON. "
            f"Parser error: {exc.msg} at position {exc.pos}; "
            f"stop reason: {stop_reason}; response ID: {response_id}. "
            "Check the backend log for the sanitized preview and "
            "character diagnostic."
        ) from exc


# ============================================================
# Load environment variables
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


# ============================================================
# Anthropic Claude configuration
# ============================================================

API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is missing from backend .env")

client = anthropic.Anthropic(api_key=API_KEY)


# ============================================================
# Allowed AI response values
# ============================================================

ALLOWED_SEVERITIES = {
    "critical",
    "high",
    "medium",
    "low",
}

ALLOWED_ISSUE_TYPES = {
    "bug",
    "security",
    "logic",
    "quality",
}

ALLOWED_STATUSES = {
    "passed",
    "issues_found",
}


# ============================================================
# Validate individual issue
# ============================================================

def validate_issue(issue, issue_index, total_lines):
    """Validate one issue returned by Claude."""
    if not isinstance(issue, dict):
        raise ValueError(f"Issue {issue_index} must be a JSON object.")

    required_fields = [
        "title",
        "severity",
        "issue_type",
        "line_number",
        "description",
        "suggestion",
    ]

    for field in required_fields:
        if field not in issue:
            raise ValueError(
                f"Issue {issue_index} is missing '{field}'."
            )

    for field in ("title", "description", "suggestion"):
        if not isinstance(issue[field], str) or not issue[field].strip():
            raise ValueError(
                f"Issue {issue_index} has an invalid '{field}'."
            )

    replacement_code = issue.get("replacement_code")
    if replacement_code is not None and not isinstance(replacement_code, str):
        raise ValueError(
            f"Issue {issue_index} has an invalid 'replacement_code'."
        )

    severity = issue["severity"]
    if not isinstance(severity, str) or severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"Issue {issue_index} has invalid severity: {severity}"
        )

    issue_type = issue["issue_type"]
    if not isinstance(issue_type, str) or issue_type not in ALLOWED_ISSUE_TYPES:
        raise ValueError(
            f"Issue {issue_index} has invalid issue type: {issue_type}"
        )

    line_number = issue["line_number"]
    if line_number is not None:
        if (
            isinstance(line_number, bool)
            or not isinstance(line_number, int)
            or line_number < 1
            or line_number > total_lines
        ):
            raise ValueError(
                f"Issue {issue_index} has an invalid line number: "
                f"{line_number}"
            )


# ============================================================
# Validate complete AI response
# ============================================================

def validate_review_response(result, code):
    """Validate the complete Claude review response."""
    if not isinstance(result, dict):
        raise ValueError("Invalid AI review response format.")

    required_fields = ["summary", "overall_status", "issues"]
    for field in required_fields:
        if field not in result:
            if field == "issues":
                raise ValueError(
                    "Claude response has no valid issues list."
                )
            raise ValueError(f"Claude response is missing '{field}'.")

    if (
        not isinstance(result["summary"], str)
        or not result["summary"].strip()
    ):
        raise ValueError("Claude response has an invalid summary.")

    status = result["overall_status"]
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        raise ValueError(
            "Claude response has an invalid overall_status."
        )

    if not isinstance(result["issues"], list):
        raise ValueError("Claude response has no valid issues list.")

    total_lines = len(code.splitlines())

    for index, issue in enumerate(result["issues"], start=1):
        validate_issue(
            issue=issue,
            issue_index=index,
            total_lines=total_lines,
        )

    expected_status = (
        "issues_found" if result["issues"] else "passed"
    )
    if status != expected_status:
        raise ValueError(
            "Claude overall_status does not match the issues list."
        )

    return result


# ============================================================
# Claude AI Code Review
# ============================================================

def review_python_code(code, filename, static_analysis=None):
    """
    Review Python source code using Claude.

    Detects logical bugs, runtime errors, edge cases, security
    vulnerabilities, performance problems, and code quality issues.
    """
    static_analysis = static_analysis or {}

    instructions = """
You are a senior Python software engineer and security-focused code reviewer.

Review the supplied Python source code carefully.

Identify genuine problems in these categories:

1. LOGICAL BUGS
   - Incorrect calculations or business logic.
   - Incorrect conditions and comparisons.
   - Missing or incorrect return values.
   - Incorrect handling of data.

2. RUNTIME ERRORS
   - Possible NoneType errors.
   - Division by zero.
   - Undefined variables or missing imports.
   - Invalid operations and incorrect function arguments.
   - Exceptions that may occur during execution.

3. EDGE CASES
   - Empty input or collections.
   - Missing or unexpected values.
   - Boundary values.
   - Unexpected input types.
   - Large inputs where relevant.

4. SECURITY VULNERABILITIES
   - SQL injection.
   - Command injection.
   - Unsafe deserialization.
   - Hardcoded credentials.
   - Path traversal.
   - Insecure handling of user input.
   - Other genuine security weaknesses.

5. PERFORMANCE
   - Unnecessary repeated operations.
   - Inefficient loops or algorithms.
   - Unnecessary database or API calls.
   - Excessive memory usage.

6. CODE QUALITY
   - Maintainability problems.
   - Unnecessary complexity.
   - Incorrect error handling.
   - Important missing validation.

REVIEW RULES:
- Report only genuine, evidence-based problems.
- Do not invent bugs.
- Examine the actual source code.
- Explain when a suspected problem can occur.
- Use exact, one-based source line numbers.
- If the exact line cannot be identified, use null.
- Explain the actual consequence of each issue.
- Provide a practical correction.
- When a concrete code replacement can be stated safely, include it in the optional replacement_code field as code only (no Markdown fences). Keep it limited to the affected statement or smallest useful block and preserve indentation.
- If a safe exact replacement cannot be provided, set replacement_code to null and explain the correction in suggestion.
- Avoid duplicate findings from Ruff and Bandit.
- Static findings are supporting evidence, not automatically confirmed bugs.
- Do not report harmless style preferences.
- Do not rewrite the entire file.
- Return an empty issues list if no genuine problems exist.

SEVERITY:
- critical: Severe vulnerability or failure with major impact.
- high: Serious bug or security issue.
- medium: Meaningful bug or reliability problem.
- low: Minor maintainability or quality issue.

Return valid JSON using exactly this structure:
{
  "summary": "Short review summary",
  "overall_status": "passed or issues_found",
  "issues": [
    {
      "title": "Short issue title",
      "severity": "critical, high, medium, or low",
      "issue_type": "bug, security, logic, or quality",
      "line_number": 1,
      "description": "Evidence-based explanation",
      "suggestion": "Practical correction",
      "replacement_code": "Exact replacement code or null"
    }
  ]
}

The overall_status must be:
- issues_found when one or more genuine issues exist.
- passed when the issues list is empty.

Return JSON only.
Do not include Markdown code fences or additional text.
"""

    user_input = f"""
Filename: {filename}

Python source code:
{code}

Static analysis findings from Ruff and Bandit:
{json.dumps(static_analysis, indent=2)}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=instructions,
        messages=[
            {
                "role": "user",
                "content": user_input,
            }
        ],
    )

    response_text = "\n".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    ).strip()

    logger.info(
        "Claude review response received. model=%s stop_reason=%s "
        "response_id=%s response_length=%s",
        MODEL,
        response.stop_reason,
        response.id,
        len(response_text),
    )

    if not response_text:
        raise ValueError(
            "Claude returned an empty review response. "
            f"Stop reason: {response.stop_reason}; "
            f"response ID: {response.id}"
        )

    if response.stop_reason == "max_tokens":
        raise ValueError(
            "Claude review response was truncated because it reached "
            "the max_tokens limit. Increase max_tokens or reduce the "
            "review input. "
            f"Response ID: {response.id}"
        )

    result = _extract_json_object(
        response_text=response_text,
        response_id=response.id,
        stop_reason=response.stop_reason,
    )

    if not isinstance(result, dict):
        raise ValueError(
            "Claude review response must be a JSON object. "
            f"Response ID: {response.id}"
        )

    return validate_review_response(
        result=result,
        code=code,
    )
import json
import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def _safe_response_preview(text: str, limit: int = 300) -> str:
    """Return a short log preview with common secret formats redacted."""
    preview = (text or "")[:limit]

    patterns = [
        (
            r"(?i)(api[_ -]?key|token|password|secret)(\s*[:=]\s*)[^,\s\"']+",
            r"\1\2[REDACTED]",
        ),
        (r"sk-ant-[A-Za-z0-9_-]+", "[REDACTED_ANTHROPIC_KEY]"),
        (r"gh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED_GITHUB_TOKEN]"),
    ]

    for pattern, replacement in patterns:
        preview = re.sub(pattern, replacement, preview)

    return preview.replace("\r", " ").replace("\n", " ")


def _clean_model_json_text(text: str) -> str:
    """
    Remove common non-printing formatting characters that can be introduced
    when model output is copied or serialized.

    This deliberately does not attempt to repair arbitrary malformed JSON.
    """
    text = (text or "").replace("\ufeff", "")
    text = text.replace("\u200b", "").replace("\u200c", "")
    text = text.replace("\u200d", "").replace("\u2060", "")
    return text.strip()


def _extract_json_object(response_text: str, response_id: str, stop_reason: str):
    """Extract and decode the first JSON object from Claude's response."""
    cleaned_response = _clean_model_json_text(response_text)

    # Handle a response wrapped in a Markdown code fence.
    if cleaned_response.startswith("```"):
        lines = cleaned_response.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_response = _clean_model_json_text("\n".join(lines))

    json_start = cleaned_response.find("{")
    if json_start == -1:
        raise ValueError(
            "Claude response did not contain a JSON object. "
            f"Stop reason: {stop_reason}; response ID: {response_id}; "
            f"response length: {len(response_text)}"
        )

    json_text = _clean_model_json_text(cleaned_response[json_start:])

    # raw_decode does not skip leading whitespace. json_text starts at "{",
    # but lstrip is retained defensively in case the extraction changes later.
    json_text = json_text.lstrip()

    try:
        result, parsed_end = json.JSONDecoder().raw_decode(json_text)
        return result

    except json.JSONDecodeError as exc:
        prefix = json_text[:40]
        logger.error(
            "Claude JSON character diagnostic: prefix=%r codepoints=%s",
            prefix,
            [f"U+{ord(char):04X}" for char in prefix],
        )

        preview = _safe_response_preview(json_text, limit=300)
        logger.error(
            "Claude review response is not valid JSON. "
            "parser_error=%s position=%s stop_reason=%s "
            "response_id=%s response_preview=%r",
            exc.msg,
            exc.pos,
            stop_reason,
            response_id,
            preview,
        )

        raise ValueError(
            "Claude returned malformed or incomplete JSON. "
            f"Parser error: {exc.msg} at position {exc.pos}; "
            f"stop reason: {stop_reason}; response ID: {response_id}. "
            "Check the backend log for the sanitized preview and "
            "character diagnostic."
        ) from exc


# ============================================================
# Load environment variables
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


# ============================================================
# Anthropic Claude configuration
# ============================================================

API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is missing from backend .env")

client = anthropic.Anthropic(api_key=API_KEY)


# ============================================================
# Allowed AI response values
# ============================================================

ALLOWED_SEVERITIES = {
    "critical",
    "high",
    "medium",
    "low",
}

ALLOWED_ISSUE_TYPES = {
    "bug",
    "security",
    "logic",
    "quality",
}

ALLOWED_STATUSES = {
    "passed",
    "issues_found",
}


# ============================================================
# Validate individual issue
# ============================================================

def validate_issue(issue, issue_index, total_lines):
    """Validate one issue returned by Claude."""
    if not isinstance(issue, dict):
        raise ValueError(f"Issue {issue_index} must be a JSON object.")

    required_fields = [
        "title",
        "severity",
        "issue_type",
        "line_number",
        "description",
        "suggestion",
    ]

    for field in required_fields:
        if field not in issue:
            raise ValueError(
                f"Issue {issue_index} is missing '{field}'."
            )

    for field in ("title", "description", "suggestion"):
        if not isinstance(issue[field], str) or not issue[field].strip():
            raise ValueError(
                f"Issue {issue_index} has an invalid '{field}'."
            )

    replacement_code = issue.get("replacement_code")
    if replacement_code is not None and not isinstance(replacement_code, str):
        raise ValueError(
            f"Issue {issue_index} has an invalid 'replacement_code'."
        )

    severity = issue["severity"]
    if not isinstance(severity, str) or severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"Issue {issue_index} has invalid severity: {severity}"
        )

    issue_type = issue["issue_type"]
    if not isinstance(issue_type, str) or issue_type not in ALLOWED_ISSUE_TYPES:
        raise ValueError(
            f"Issue {issue_index} has invalid issue type: {issue_type}"
        )

    line_number = issue["line_number"]
    if line_number is not None:
        if (
            isinstance(line_number, bool)
            or not isinstance(line_number, int)
            or line_number < 1
            or line_number > total_lines
        ):
            raise ValueError(
                f"Issue {issue_index} has an invalid line number: "
                f"{line_number}"
            )


# ============================================================
# Validate complete AI response
# ============================================================

def validate_review_response(result, code):
    """Validate the complete Claude review response."""
    if not isinstance(result, dict):
        raise ValueError("Invalid AI review response format.")

    required_fields = ["summary", "overall_status", "issues"]
    for field in required_fields:
        if field not in result:
            if field == "issues":
                raise ValueError(
                    "Claude response has no valid issues list."
                )
            raise ValueError(f"Claude response is missing '{field}'.")

    if (
        not isinstance(result["summary"], str)
        or not result["summary"].strip()
    ):
        raise ValueError("Claude response has an invalid summary.")

    status = result["overall_status"]
    if not isinstance(status, str) or status not in ALLOWED_STATUSES:
        raise ValueError(
            "Claude response has an invalid overall_status."
        )

    if not isinstance(result["issues"], list):
        raise ValueError("Claude response has no valid issues list.")

    total_lines = len(code.splitlines())

    for index, issue in enumerate(result["issues"], start=1):
        validate_issue(
            issue=issue,
            issue_index=index,
            total_lines=total_lines,
        )

    expected_status = (
        "issues_found" if result["issues"] else "passed"
    )
    if status != expected_status:
        raise ValueError(
            "Claude overall_status does not match the issues list."
        )

    return result


# ============================================================
# Claude AI Code Review
# ============================================================

def review_python_code(code, filename, static_analysis=None):
    """
    Review Python source code using Claude.

    Detects logical bugs, runtime errors, edge cases, security
    vulnerabilities, performance problems, and code quality issues.
    """
    static_analysis = static_analysis or {}

    instructions = """
You are a senior Python software engineer and security-focused code reviewer.

Review the supplied Python source code carefully.

Identify genuine problems in these categories:

1. LOGICAL BUGS
   - Incorrect calculations or business logic.
   - Incorrect conditions and comparisons.
   - Missing or incorrect return values.
   - Incorrect handling of data.

2. RUNTIME ERRORS
   - Possible NoneType errors.
   - Division by zero.
   - Undefined variables or missing imports.
   - Invalid operations and incorrect function arguments.
   - Exceptions that may occur during execution.

3. EDGE CASES
   - Empty input or collections.
   - Missing or unexpected values.
   - Boundary values.
   - Unexpected input types.
   - Large inputs where relevant.

4. SECURITY VULNERABILITIES
   - SQL injection.
   - Command injection.
   - Unsafe deserialization.
   - Hardcoded credentials.
   - Path traversal.
   - Insecure handling of user input.
   - Other genuine security weaknesses.

5. PERFORMANCE
   - Unnecessary repeated operations.
   - Inefficient loops or algorithms.
   - Unnecessary database or API calls.
   - Excessive memory usage.

6. CODE QUALITY
   - Maintainability problems.
   - Unnecessary complexity.
   - Incorrect error handling.
   - Important missing validation.

REVIEW RULES:
- Report only genuine, evidence-based problems.
- Do not invent bugs.
- Examine the actual source code.
- Explain when a suspected problem can occur.
- Use exact, one-based source line numbers.
- If the exact line cannot be identified, use null.
- Explain the actual consequence of each issue.
- Provide a practical correction.
- When a concrete code replacement can be stated safely, include it in the optional replacement_code field as code only (no Markdown fences). Keep it limited to the affected statement or smallest useful block and preserve indentation.
- If a safe exact replacement cannot be provided, set replacement_code to null and explain the correction in suggestion.
- Avoid duplicate findings from Ruff and Bandit.
- Static findings are supporting evidence, not automatically confirmed bugs.
- Do not report harmless style preferences.
- Do not rewrite the entire file.
- Return an empty issues list if no genuine problems exist.

SEVERITY:
- critical: Severe vulnerability or failure with major impact.
- high: Serious bug or security issue.
- medium: Meaningful bug or reliability problem.
- low: Minor maintainability or quality issue.

Return valid JSON using exactly this structure:
{
  "summary": "Short review summary",
  "overall_status": "passed or issues_found",
  "issues": [
    {
      "title": "Short issue title",
      "severity": "critical, high, medium, or low",
      "issue_type": "bug, security, logic, or quality",
      "line_number": 1,
      "description": "Evidence-based explanation",
      "suggestion": "Practical correction",
      "replacement_code": "Exact replacement code or null"
    }
  ]
}

The overall_status must be:
- issues_found when one or more genuine issues exist.
- passed when the issues list is empty.

Return JSON only.
Do not include Markdown code fences or additional text.
"""

    user_input = f"""
Filename: {filename}

Python source code:
{code}

Static analysis findings from Ruff and Bandit:
{json.dumps(static_analysis, indent=2)}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=instructions,
        messages=[
            {
                "role": "user",
                "content": user_input,
            }
        ],
    )

    response_text = "\n".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    ).strip()

    logger.info(
        "Claude review response received. model=%s stop_reason=%s "
        "response_id=%s response_length=%s",
        MODEL,
        response.stop_reason,
        response.id,
        len(response_text),
    )

    if not response_text:
        raise ValueError(
            "Claude returned an empty review response. "
            f"Stop reason: {response.stop_reason}; "
            f"response ID: {response.id}"
        )

    if response.stop_reason == "max_tokens":
        raise ValueError(
            "Claude review response was truncated because it reached "
            "the max_tokens limit. Increase max_tokens or reduce the "
            "review input. "
            f"Response ID: {response.id}"
        )

    result = _extract_json_object(
        response_text=response_text,
        response_id=response.id,
        stop_reason=response.stop_reason,
    )

    if not isinstance(result, dict):
        raise ValueError(
            "Claude review response must be a JSON object. "
            f"Response ID: {response.id}"
        )

    return validate_review_response(
        result=result,
        code=code,
    )
