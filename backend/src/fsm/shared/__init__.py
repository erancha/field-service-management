"""Shared kernel: the only package the bounded contexts may import from outside themselves.

Holds infrastructure primitives every context's adapters need (the declarative ORM base,
Google OAuth endpoint URIs). Kept deliberately tiny — anything with behaviour belongs in a
context or in platform, and the import-linter layers contract places this package at the
bottom of the stack so it can never import upward.
"""
