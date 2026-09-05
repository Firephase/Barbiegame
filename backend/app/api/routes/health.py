"""Health and capability reporting."""
from __future__ import annotations

from fastapi import APIRouter

from ...config import settings
from ...core.registry import registry
from ...providers import CAPABILITIES
from ...services.citations import STYLE_LABELS
from ...services.charts import FORMS
from ...services.export import FORMATS
from ...services.modes import describe_modes

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/providers")
def providers() -> dict:
    """What this deployment can actually do right now, and why not, where not.

    This is the screen a user checks when an answer says a capability was
    unavailable — every adapter reports its own reason.
    """
    health_map = registry.health(CAPABILITIES)
    #: The configured selection for each capability — ``active`` must reflect what
    #: the app will actually use, not merely what could be used.
    specs = {
        "llm": settings.llm_provider,
        "web_search": settings.web_search_providers,
        "academic_search": settings.academic_providers,
        "url_extract": settings.extractor_provider,
        "video_transcript": settings.video_provider,
        "passage_index": settings.index_provider,
        "blob_storage": settings.storage_provider,
    }
    summary = {}
    for capability, entries in health_map.items():
        chosen = [p.name for p in registry.resolve(capability, specs.get(capability))]
        summary[capability] = {
            "available": bool(chosen),
            "active": chosen[0] if chosen else None,
            "selected": chosen,
            "providers": entries,
        }
    return {
        "capabilities": summary,
        "configuration": {
            "llm_provider": settings.llm_provider,
            "web_search_providers": settings.web_search_providers,
            "academic_providers": settings.academic_providers,
            "respect_robots_txt": settings.respect_robots_txt,
            "default_max_sources": settings.default_max_sources,
        },
        "degraded": [cap for cap, info in summary.items() if not info["available"]],
    }


@router.get("/capabilities")
def capabilities() -> dict:
    """Everything the UI needs to render its option lists."""
    return {
        "modes": describe_modes(),
        "citation_styles": [{"id": k, "label": v} for k, v in STYLE_LABELS.items()],
        "export_formats": list(FORMATS),
        "chart_forms": list(FORMS),
        "explanation_levels": [
            {"id": "beginner", "label": "Explain it like I'm learning it for the first time"},
            {"id": "student", "label": "Student"},
            {"id": "researcher", "label": "Researcher"},
            {"id": "expert", "label": "Expert"},
        ],
        "depths": ["brief", "standard", "thorough"],
        "source_types": [
            "journal_article", "preprint", "book", "news", "government", "institutional",
            "documentation", "dataset", "video", "web_page", "uploaded_document",
        ],
    }
