from app.domains.documents.connectors.base import KnowledgeConnector
from app.domains.documents.connectors.upload_connector import UploadConnector


def get_knowledge_connector(name: str = "upload") -> KnowledgeConnector:
    key = name.lower()
    if key == "upload":
        return UploadConnector()
    # "website", "s3", "drive", "dropbox" and "sharepoint" land in V4 -
    # registered here once their connectors exist.
    raise ValueError(f"Unknown knowledge connector '{name}' (expected upload)")
