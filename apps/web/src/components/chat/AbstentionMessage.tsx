export default function AbstentionMessage({ content }: { content: string }) {
  return (
    <div className="max-w-[75%] rounded-2xl px-4 py-3 text-sm bg-amber-50 border border-amber-200 text-amber-900 whitespace-pre-wrap">
      <div className="flex items-center gap-1.5 font-medium mb-1">
        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 4.3L2.6 18a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 4.3a2 2 0 00-3.4 0z" />
        </svg>
        <span>Insufficient evidence</span>
      </div>
      {content}
    </div>
  );
}
