export default function AbstentionMessage({ content }: { content: string }) {
  return (
    <div className="max-w-[75%] rounded-2xl rounded-tl-sm px-4 py-3 text-sm bg-amber-50 border border-amber-200 text-amber-900 whitespace-pre-wrap">
      <div className="flex items-center gap-1.5 font-medium mb-1">
        <span>⚠️</span>
        <span>Insufficient evidence</span>
      </div>
      {content}
    </div>
  );
}
