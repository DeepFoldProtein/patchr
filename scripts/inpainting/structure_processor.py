"""Backward-compatibility shim.

All logic has been moved to the ``processor`` subpackage.
"""
from .processor import StructureProcessor  # noqa: F401

__all__ = ["StructureProcessor"]
