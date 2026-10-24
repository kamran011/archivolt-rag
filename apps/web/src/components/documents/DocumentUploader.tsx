"use client";

import { useRef, useState } from "react";

interface DocumentUploaderProps {
  onUpload: (file: File) => Promise<unknown>;
}

const ACCEPTED = ".pdf,.docx,.md,.markdown,.txt,.html,.htm,.csv,.json";

export default function DocumentUploader({ onUpload }: DocumentUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await onUpload(file);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
          dragging ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <svg className="mx-auto mb-2 h-8 w-8 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M17 8l-5-5-5 5M12 3v12" />
        </svg>
        <p className="text-sm text-gray-600">
          {uploading ? "Uploading…" : "Drag & drop files, or click to browse"}
        </p>
        <p className="text-xs text-gray-500 mt-1">PDF, DOCX, Markdown, TXT, HTML, CSV, JSON</p>
      </div>
      {error && <p role="alert" className="text-red-600 text-xs mt-2">{error}</p>}
    </div>
  );
}
