"""Disposable calculator fixture for portability testing."""


def add(left: int, right: int) -> int:
    return left + right


def multiply(left: int, right: int) -> int:
    return left * right


def cube(value: int) -> int:
    return value * value * value


def negate(value: int) -> int:
    return -value
