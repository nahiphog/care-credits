"""Compatibility import for existing workers and tests."""
import sys
from models import schema
sys.modules[__name__] = schema
