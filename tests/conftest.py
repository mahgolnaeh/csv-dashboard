"""
Shared pytest configuration and fixtures.

Sets OPENROUTER_API_KEY before any test module is imported so that
Settings() (which reads it at module-level) does not raise ValidationError
in CI or when no .env file is present.
"""

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-ci")
