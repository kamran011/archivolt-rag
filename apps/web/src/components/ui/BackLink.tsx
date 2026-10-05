import Link from "next/link";

/**
 * Back-navigation link used above a page/form title. A real SVG chevron (not
 * an ASCII arrow), a padded hit area that still optically lines up with the
 * title below it (negative margin offsets the padding), and its own bottom
 * margin so callers don't need to hand-tune spacing to the title that follows.
 */
export default function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="-ml-2 mb-4 inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-900"
    >
      <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
      {label}
    </Link>
  );
}
