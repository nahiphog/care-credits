"""Stable ASGI and legacy import entrypoint for the reconciled application."""
import sys
from services import portal
sys.modules[__name__] = portal
