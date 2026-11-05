import os

# Tests use their own secret so they never depend on (or leak) the real .env value.
os.environ.setdefault(
    "SECRET_KEY",
    "test-secret-key-for-pytest-only-0123456789abcdef"
)