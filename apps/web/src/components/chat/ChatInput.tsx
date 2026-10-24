"use client";

import { useRef, useState } from "react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
  }

  return (
    <div className="flex items-end gap-3.5">
      <div className="flex-1 bg-bg-white border border-border rounded-full px-4 py-3 transition-colors focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 overflow-hidden">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          aria-label="Message input"
          placeholder="Type your message…"
          className="w-full resize-none bg-transparent border-0 outline-none ring-0 focus:outline-none focus:ring-0 focus-visible:outline-none text-sm text-text placeholder:text-text-muted max-h-32 disabled:opacity-50"
          style={{ outline: "none", boxShadow: "none" }}
        />
      </div>
      <button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        aria-label="Send message"
        className="shrink-0 w-11 h-11 rounded-full bg-cta hover:bg-primary-dark disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center text-white cursor-pointer"
        style={{ boxShadow: "0 8px 20px rgba(106, 53, 255, 0.35)" }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 11.5L21 3l-8.5 18-2.3-7.2L3 11.5z" />
        </svg>
      </button>
    </div>
  );
}
