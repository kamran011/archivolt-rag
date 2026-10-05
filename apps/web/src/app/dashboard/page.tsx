import Link from "next/link";

export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Dashboard</h1>
      <p className="text-gray-500 text-sm mb-8">
        Welcome to Groundtruth — your AI knowledge platform.
      </p>

      <div className="rounded-2xl border border-border bg-bg-white shadow-glow p-5 mb-6">
        <div className="grid grid-cols-1 divide-y divide-gray-100 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          {[
            { label: "Knowledge Bases", value: "—", href: "/dashboard/knowledge-bases" },
            { label: "Documents", value: "—", href: "/dashboard/knowledge-bases" },
            { label: "Conversations", value: "—", href: "/dashboard/chat" },
          ].map((stat) => (
            <a
              key={stat.label}
              href={stat.href}
              className="rounded-xl p-4 transition-colors hover:bg-gray-50 sm:first:pl-0 sm:last:pr-0"
            >
              <p className="text-sm text-gray-500">{stat.label}</p>
              <p className="text-2xl font-semibold text-gray-900 mt-1">{stat.value}</p>
            </a>
          ))}
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
        <h2 className="font-medium text-blue-900 mb-1">Get started</h2>
        <ol className="list-decimal list-inside text-sm text-blue-800 space-y-1">
          <li>
            <Link href="/dashboard/knowledge-bases/new" className="underline">
              Create a knowledge base
            </Link>
          </li>
          <li>Upload documents (PDF, DOCX, Markdown, TXT)</li>
          <li>
            <a href="/dashboard/chat" className="underline">
              Start chatting
            </a>{" "}
            with your documents
          </li>
        </ol>
      </div>
    </div>
  );
}
