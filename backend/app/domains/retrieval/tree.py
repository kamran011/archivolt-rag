"""
Document trees: a heading-hierarchy outline of a document, stored inside the
existing `documents.parsing_metadata` JSON (no dedicated table).

Each node records which chunk indices belong to it, so tree navigation can
select sections and then load the real source chunks. Summaries, when
present, are navigation aids only — they are never returned as evidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domains.ingestion.schemas import ChunkData


class TreeNode(BaseModel):
    node_id: str
    title: str
    level: int
    chunk_indices: list[int] = Field(default_factory=list)
    summary: str | None = None
    children: list[TreeNode] = Field(default_factory=list)


TreeNode.model_rebuild()


def build_tree(chunks: list[ChunkData]) -> list[TreeNode]:
    """Builds a forest of TreeNodes from each chunk's heading_hierarchy.
    Chunks without a hierarchy are attached to a synthetic root node."""
    roots: list[TreeNode] = []
    index: dict[tuple[str, ...], TreeNode] = {}
    counter = 0

    def get_or_create(path: tuple[str, ...]) -> TreeNode:
        nonlocal counter
        if path in index:
            return index[path]
        parent = get_or_create(path[:-1]) if len(path) > 1 else None
        counter += 1
        node = TreeNode(node_id=f"n{counter}", title=path[-1], level=len(path))
        index[path] = node
        (parent.children if parent else roots).append(node)
        return node

    for chunk in chunks:
        hierarchy = chunk.metadata.get("heading_hierarchy") or []
        path = tuple(hierarchy) if hierarchy else ("(document)",)
        get_or_create(path).chunk_indices.append(chunk.chunk_index)

    return roots


def iter_nodes(nodes: list[TreeNode]):
    for node in nodes:
        yield node
        yield from iter_nodes(node.children)


def subtree_chunk_indices(node: TreeNode) -> list[int]:
    indices = list(node.chunk_indices)
    for child in node.children:
        indices.extend(subtree_chunk_indices(child))
    return indices


def tree_to_json(nodes: list[TreeNode]) -> list[dict[str, Any]]:
    return [n.model_dump() for n in nodes]


def tree_from_json(data: list[dict[str, Any]] | None) -> list[TreeNode]:
    if not data:
        return []
    return [TreeNode.model_validate(d) for d in data]


def render_outline(doc_label: str, nodes: list[TreeNode], doc_key: str) -> str:
    """Compact outline the LLM navigates. Node refs are '<doc_key>:<node_id>'."""
    lines = [f"Document: {doc_label}"]
    for node in iter_nodes(nodes):
        indent = "  " * (node.level - 1)
        line = f"{indent}[{doc_key}:{node.node_id}] {node.title}"
        if node.summary:
            line += f" — {node.summary}"
        lines.append(line)
    return "\n".join(lines)
