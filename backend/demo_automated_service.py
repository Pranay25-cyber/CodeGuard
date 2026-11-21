from app.services.automated_test_service import run_automated_tests


fixed_code = """
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""


test_code = """
from fixed_code import divide
import pytest


def test_normal_division():
    assert divide(10, 2) == 5


def test_division_by_zero():
    with pytest.raises(ValueError):
        divide(10, 0)


def test_negative_numbers():
    assert divide(-10, 2) == -5
"""


result = run_automated_tests(
    fixed_code=fixed_code,
    test_code=test_code
)

print("\\nAUTOMATED TEST RESULT")
print("----------------------")
print("Status:", result["status"])
print("Output:", result["test_output"])
print("Errors:", result["error_output"])