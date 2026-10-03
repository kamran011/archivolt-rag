import type { ChatMessage } from "@/hooks/useChat";
import CitationChip from "@/components/chat/CitationChip";
import AbstentionMessage from "@/components/chat/AbstentionMessage";
import ChatAvatar from "@/components/chat/ChatAvatar";

function renderContentWithCitations(
  message: ChatMessage,
  onCitationOpen?: (index: number) => void
) {
  const { content, citations } = message;
  if (!citations || citations.length === 0) return content;

  const parts: (string | React.ReactNode)[] = [];
  const regex = /\[Source (\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(content)) !== null) {
    parts.push(content.slice(lastIndex, match.index));
    const idx = parseInt(match[1], 10);
    const citation = citations.find((c) => c.index === idx);
    if (citation) {
      parts.push(
        <CitationChip
          key={`${message.id}-${match.index}`}
          citation={citation}
          onOpen={() => onCitationOpen?.(citation.index)}
        />
      );
    } else {
      parts.push(match[0]);
    }
    lastIndex = match.index + match[0].length;
  }
  parts.push(content.slice(lastIndex));

  return parts;
}

function ConflictNotice({ message }: { message: ChatMessage }) {
  const conflicts = message.conflicts ?? [];
  if (conflicts.length === 0) return null;
  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
      <p className="font-medium mb-1">Sources disagree</p>
      <ul className="space-y-1">
        {conflicts.map((c, i) => (
          <li key={i}>
            <span className="font-medium">{c.topic}:</span> [Source {c.source_a}] says &ldquo;
            {c.claim_a}&rdquo; but [Source {c.source_b}] says &ldquo;{c.claim_b}&rdquo;.{" "}
            {c.resolved && c.winning_source
              ? `Preferring [Source ${c.winning_source}] (${c.resolution_reason}).`
              : "Could not be resolved automatically - verify with the documents."}
          </li>
        ))}
      </ul>
    </div>
  );
}

function VerificationNotice({ message }: { message: ChatMessage }) {
  if (message.verificationStatus === "unverified") {
    return (
      <p className="mt-2 text-[11px] text-amber-700">
        This answer could not be checked against the sources - please verify it.
      </p>
    );
  }
  if (message.verificationStatus === "partial") {
    return (
      <p className="mt-2 text-[11px] text-text-muted">
        Some statements were removed because the sources did not support them.
      </p>
    );
  }
  return null;
}

function EvidenceLink({
  selected,
  onSelect,
}: {
  selected?: boolean;
  onSelect?: () => void;
}) {
  if (!onSelect) return null;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`mt-1 ml-1 cursor-pointer rounded px-1.5 py-1 text-[11px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-primary ${
        selected ? "text-primary-dark" : "text-text-muted hover:text-primary-dark"
      }`}
    >
      {selected ? "Showing evidence" : "View evidence"}
    </button>
  );
}

export default function MessageBubble({
  message,
  selected,
  onSelect,
  onCitationOpen,
}: {
  message: ChatMessage;
  selected?: boolean;
  onSelect?: () => void;
  onCitationOpen?: (index: number) => void;
}) {
  const isUser = message.role === "user";

  if (message.abstained) {
    return (
      <div className="flex items-start gap-2.5">
        <ChatAvatar size={32} />
        <div>
          <AbstentionMessage content={message.content} />
          <EvidenceLink selected={selected} onSelect={onSelect} />
        </div>
      </div>
    );
  }

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap bg-primary text-white">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2.5">
      <ChatAvatar size={32} />
      <div className="max-w-[75%]">
      <div
        className={`rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap bg-gray-100 text-text ${
          selected ? "ring-2 ring-primary/40" : ""
        }`}
      >
        {renderContentWithCitations(message, onCitationOpen)}
        <ConflictNotice message={message} />
        <VerificationNotice message={message} />
        {message.agent && (
          <p className="mt-2 text-[11px] text-text-muted">
            Deep research: {message.agent.steps.filter((s) => s.action !== "finish").length}{" "}
            search steps
          </p>
        )}
        {message.streaming && !message.content && (
          <span className="inline-flex gap-1 items-center py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce [animation-delay:-0.3s]" />
            <span className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce [animation-delay:-0.15s]" />
            <span className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce" />
          </span>
        )}
      </div>
      {!message.streaming && <EvidenceLink selected={selected} onSelect={onSelect} />}
      </div>
    </div>
  );
}
