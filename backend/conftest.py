"""
Root conftest.py to set up Python path for pytest.

This runs before test collection, ensuring imports work correctly.
"""
import sys
import os

# Add backend directory to Python path FIRST
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Pre-import modules that might conflict with test directory names
# This ensures Python's module cache has the correct entries BEFORE
# pytest tries to import test modules from directories with similar names
import alerts
import deployment
