"""Programmatic REST API for EKAP (spec 007).

This package provides the JSON REST surface described in contracts/rest-api.md.
It is included as an APIRouter on the existing portal FastAPI application rather
than mounted as a sub-application, preserving the shared application lifespan,
and introduces no new dependencies.
"""
