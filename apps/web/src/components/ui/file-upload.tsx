"use client";

import { useRef, useState, useCallback } from "react";

const ACCEPTED_TYPES = [
  { ext: "pdf", label: "PDF" },
  { ext: "docx", label: "DOCX" },
  { ext: "md", label: "MD" },
  { ext: "txt", label: "TXT" },
  { ext: "html", label: "HTML" },
  { ext: "csv", label: "CSV" },
  { ext: "json", label: "JSON" },
];

const ACCEPT = ".pdf,.docx,.md,.markdown,.txt,.html,.htm,.csv,.json";

function getFileExt(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileTypeIcon({ ext }: { ext: string }) {
  const colorMap: Record<string, string> = {
    pdf: "bg-red-100 text-red-700",
    docx: "bg-blue-100 text-blue-700",
    doc: "bg-blue-100 text-blue-700",
    md: "bg-purple-100 text-purple-700",
    markdown: "bg-purple-100 text-purple-700",
    txt: "bg-gray-100 text-gray-600",
    html: "bg-orange-100 text-orange-700",
    htm: "bg-orange-100 text-orange-700",
    csv: "bg-green-100 text-green-700",
    json: "bg-yellow-100 text-yellow-700",
  };
  const cls = colorMap[ext] ?? "bg-gray-100 text-gray-600";
  return (
    <span
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold uppercase ${cls}`}
    >
      {ext.slice(0, 3)}
    </span>
  );
}

interface QueuedFile {
  id: string;
  file: File;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

export interface FileUploadProps {
  onUpload: (file: File) => Promise<unknown>;
  multiple?: boolean;
  showFileList?: boolean;
  className?: string;
}

export function FileUpload({
  onUpload,
  multiple = true,
  showFileList = true,
  className,
}: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);
  const [isDragOver, setIsDragOver] = useState(false);
  const [queue, setQueue] = useState<QueuedFile[]>([]);

  const processFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      const entries: QueuedFile[] = files.map((f) => ({
        id: `${f.name}-${f.size}-${Date.now()}-${Math.random()}`,
        file: f,
        status: "pending",
      }));

      if (showFileList) {
        setQueue((prev) => [...prev, ...entries]);
      }

      for (const entry of entries) {
        if (showFileList) {
          setQueue((prev) =>
            prev.map((q) =>
              q.id === entry.id ? { ...q, status: "uploading" } : q,
            ),
          );
        }
        try {
          await onUpload(entry.file);
          if (showFileList) {
            setQueue((prev) =>
              prev.map((q) =>
                q.id === entry.id ? { ...q, status: "done" } : q,
              ),
            );
          }
        } catch (e) {
          if (showFileList) {
            setQueue((prev) =>
              prev.map((q) =>
                q.id === entry.id
                  ? {
                      ...q,
                      status: "error",
                      error:
                        e instanceof Error ? e.message : "Upload failed",
                    }
                  : q,
              ),
            );
          }
        }
      }

      if (inputRef.current) inputRef.current.value = "";
    },
    [onUpload, showFileList],
  );

  return (
    <div className={className}>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload documents, click or drag and drop"
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepthRef.current += 1;
          if (dragDepthRef.current === 1) setIsDragOver(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
        }}
        onDragLeave={() => {
          dragDepthRef.current -= 1;
          if (dragDepthRef.current <= 0) {
            dragDepthRef.current = 0;
            setIsDragOver(false);
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragDepthRef.current = 0;
          setIsDragOver(false);
          const files = Array.from(e.dataTransfer.files);
          processFiles(files);
        }}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        className={`relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed p-8 text-center transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${isDragOver ? "border-primary bg-primary/5 scale-[1.01]" : "border-gray-300 bg-white hover:border-gray-400 hover:bg-gray-50/50"}`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple={multiple}
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => processFiles(Array.from(e.target.files ?? []))}
        />

        <div
          className={`pointer-events-none mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl transition-all duration-200 ${isDragOver ? "bg-primary/10 text-primary scale-110" : "bg-gray-100 text-gray-400"}`}
        >
          <svg
            className="h-7 w-7"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6}
            viewBox="0 0 24 24"
            aria-hidden
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
            />
          </svg>
        </div>

        <p className="text-sm font-medium text-gray-900">
          {isDragOver ? "Drop to upload" : "Drag & drop files here"}
        </p>
        <p className="mt-1 text-xs text-gray-500">or click to browse</p>

        <div className="mt-4 flex flex-wrap justify-center gap-1.5">
          {ACCEPTED_TYPES.map((t) => (
            <span
              key={t.ext}
              className="rounded-md bg-gray-100 px-2 py-0.5 text-[10px] font-medium uppercase text-gray-500"
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>

      {showFileList && queue.length > 0 && (
        <ul className="mt-3 space-y-2">
          {queue.map((item) => {
            const ext = getFileExt(item.file.name);
            return (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded-xl border border-gray-100 bg-white px-3 py-2.5"
              >
                <FileTypeIcon ext={ext} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-gray-900">
                    {item.file.name}
                  </p>
                  <p className="text-xs text-gray-400">
                    {formatBytes(item.file.size)}
                  </p>
                </div>
                <div className="shrink-0">
                  {item.status === "uploading" && (
                    <span className="flex items-center gap-1.5 text-xs text-gray-400">
                      <svg
                        className="h-3.5 w-3.5 animate-spin"
                        fill="none"
                        viewBox="0 0 24 24"
                        aria-hidden
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        />
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                        />
                      </svg>
                      Uploading
                    </span>
                  )}
                  {item.status === "done" && (
                    <span className="flex items-center gap-1 text-xs text-green-600">
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                        viewBox="0 0 24 24"
                        aria-hidden
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                      Done
                    </span>
                  )}
                  {item.status === "error" && (
                    <span
                      title={item.error}
                      className="flex items-center gap-1 text-xs text-red-600"
                    >
                      <svg
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                        viewBox="0 0 24 24"
                        aria-hidden
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                      Failed
                    </span>
                  )}
                  {item.status === "pending" && (
                    <span className="text-xs text-gray-300">Queued</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default FileUpload;
