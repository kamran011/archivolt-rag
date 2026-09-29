import type { DocumentStatus } from "@/lib/types";

const STYLES: Record<DocumentStatus, string> = {
  pending: "bg-gray-100 text-gray-600",
  parsing: "bg-blue-100 text-blue-700",
  chunking: "bg-amber-100 text-amber-700",
  embedding: "bg-purple-100 text-purple-700",
  ready: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

const LABELS: Record<DocumentStatus, string> = {
  pending: "Pending",
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  ready: "Ready",
  failed: "Failed",
};

export default function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
