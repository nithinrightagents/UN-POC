"""API routers for all EKAP capabilities."""

from api.routers.assessments import build_assessments_router
from api.routers.benchmarks import build_benchmarks_router
from api.routers.completions import build_completions_router
from api.routers.cycles import build_cycles_router
from api.routers.discrepancy import build_discrepancy_router
from api.routers.export import build_export_router
from api.routers.human import build_human_router
from api.routers.msq import build_msq_router
from api.routers.prefills import build_prefills_router
from api.routers.publication import build_publication_router
from api.routers.reference import build_reference_router
from api.routers.review import build_review_router
from api.routers.system import build_system_router
from api.routers.telemetry import build_telemetry_router
from api.routers.verify import build_verify_router

__all__ = [
    "build_assessments_router",
    "build_benchmarks_router",
    "build_completions_router",
    "build_cycles_router",
    "build_discrepancy_router",
    "build_export_router",
    "build_human_router",
    "build_msq_router",
    "build_prefills_router",
    "build_publication_router",
    "build_reference_router",
    "build_review_router",
    "build_system_router",
    "build_telemetry_router",
    "build_verify_router",
]
