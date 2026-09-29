from app.domains.tools.base import ToolRegistry
from app.domains.tools.calculator import CalculatorTool
from app.domains.tools.search_tools import DocumentLookupTool, KnowledgeBaseSearchTool


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(KnowledgeBaseSearchTool())
    registry.register(DocumentLookupTool())
    registry.register(CalculatorTool())
    return registry


default_registry = build_default_registry()
