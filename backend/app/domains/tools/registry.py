from app.domains.tools.base import ToolRegistry
from app.domains.tools.calculator import CalculatorTool
from app.domains.tools.external_api import ExternalApiTool
from app.domains.tools.search_tools import DocumentLookupTool, KnowledgeBaseSearchTool
from app.domains.tools.structured_query import StructuredQueryTool
from app.domains.tools.web_search import WebSearchTool


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(KnowledgeBaseSearchTool())
    registry.register(DocumentLookupTool())
    registry.register(StructuredQueryTool())
    registry.register(WebSearchTool())
    registry.register(ExternalApiTool())
    registry.register(CalculatorTool())
    return registry


default_registry = build_default_registry()
