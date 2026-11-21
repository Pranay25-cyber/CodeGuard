import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is missing from backend/.env")

client = anthropic.Anthropic(api_key=API_KEY)


def parse_claude_json(response_text: str) -> dict:
    """Extract and parse one JSON object from the Claude response."""
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError("Claude returned an empty response.")

    cleaned_response = response_text.strip()

    if cleaned_response.startswith("```"):
        lines = cleaned_response.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned_response = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned_response):
        if character != "{":
            continue
        try:
            result, _ = decoder.raw_decode(cleaned_response[index:])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    raise ValueError(
        "Claude did not return a valid JSON object. "
        f"Response length: {len(response_text)} characters."
    )


def generate_code_fix(
    code: str,
    filename: str,
    review_result: dict,
    test_code: str = "",
    validation_errors: dict | None = None,
    original_code: str | None = None,
):
    """
    Generate or correct a complete Python file.

    On correction attempts, `code` is the latest generated version,
    `original_code` is the developer's original file, and
    `validation_errors` contains the latest static-analysis report.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Source code cannot be empty.")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("Filename is required.")
    if not isinstance(review_result, dict):
        raise ValueError("Review result must be a dictionary.")
    if not isinstance(test_code, str):
        raise ValueError("Automated test code must be a string.")

    issues = review_result.get("issues")
    if not isinstance(issues, list) or not issues:
        raise ValueError("No valid review findings were provided.")

    source_code = original_code if isinstance(original_code, str) else code
    is_correction = bool(validation_errors)

    system_instructions = """
You are an expert Python code repair agent.

Return a complete corrected Python file as a JSON object.

Rules:
1. Fix the reported code-review findings and every supplied static-validation error.
2. On a correction request, use the latest generated code as the starting point.
3. Preserve the original program's intended behavior and public interfaces.
4. Make the smallest necessary changes.
5. Do not remove features or invent unrelated changes.
6. Do not weaken, bypass, disable, or silence Ruff or Bandit rules.
7. Do not add noqa comments merely to hide reported issues.
8. Do not add test files or require automated tests.
9. Do not execute demonstration code at module import time.
10. Return the complete corrected Python file, not a patch or partial snippet.
11. Return exactly one valid JSON object and no Markdown fences.
12. Escape special characters correctly inside JSON strings.

Return this JSON structure:
{
  "status": "success",
  "filename": "example.py",
  "changes_summary": "Explain what was fixed",
  "fixed_code": "Complete corrected Python code"
}
"""

    validation_text = (
        json.dumps(validation_errors, indent=2, ensure_ascii=False)
        if validation_errors
        else "No previous static-validation report. This is the initial fix."
    )

    user_prompt = f"""
Filename: {filename}

Developer's original Python file:
<original_source>
{source_code}
</original_source>

Latest code to work on:
<current_source>
{code}
</current_source>

AI code review findings:
<review_findings>
{json.dumps(review_result, indent=2, ensure_ascii=False)}
</review_findings>

Latest static-validation report:
<static_validation_errors>
{validation_text}
</static_validation_errors>

Correction request: {is_correction}

Instructions:
- Correct all listed review findings and static-validation errors.
- Pay particular attention to each Ruff rule code, message, and line number.
- Fix the underlying code; do not suppress the diagnostics.
- Keep the original behavior wherever possible.
- Automated tests are optional and are not required for this task.
- Return the complete corrected file in the required JSON structure.
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system_instructions,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception:
        logger.exception("Claude code-fix request failed for %s", filename)
        raise

    response_text = "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    stop_reason = response.stop_reason

    logger.info(
        "Claude fix response received: model=%s, stop_reason=%s, text_length=%s",
        MODEL,
        stop_reason,
        len(response_text),
    )

    if stop_reason == "max_tokens":
        raise ValueError(
            "Claude response was truncated because the token limit was reached."
        )
    if not response_text:
        raise ValueError(
            f"Claude returned no text content. Stop reason: {stop_reason}"
        )

    try:
        result = parse_claude_json(response_text)
    except ValueError as exc:
        logger.exception("Failed to parse Claude JSON response for %s", filename)
        raise ValueError(
            "Claude returned an invalid JSON response. "
            f"Stop reason: {stop_reason}. "
            f"Response length: {len(response_text)}."
        ) from exc

    if result.get("status") != "success":
        raise ValueError("AI fix generation was not successful.")
    if result.get("filename") != filename:
        raise ValueError("AI returned an unexpected filename.")

    changes_summary = result.get("changes_summary")
    fixed_code = result.get("fixed_code")

    if not isinstance(changes_summary, str) or not changes_summary.strip():
        raise ValueError("AI returned an invalid changes summary.")
    if not isinstance(fixed_code, str) or not fixed_code.strip():
        raise ValueError("Claude returned empty or invalid fixed code.")
    if fixed_code == code:
        raise ValueError("Claude returned unchanged code. No correction was generated.")

    logger.info("Claude code fix generated successfully for %s", filename)

    return {
        "status": "success",
        "filename": filename,
        "changes_summary": changes_summary,
        "fixed_code": fixed_code,
    }
