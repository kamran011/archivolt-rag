import Link from "next/link";

export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Dashboard</h1>
      <p className="text-gray-500 text-sm mb-8">
        Welcome to Archivolt — your AI knowledge platform.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {[
          { label: "Knowledge Bases", value: "—", href: "/dashboard/knowledge-bases" },
          { label: "Documents", value: "—", href: "/dashboard/knowledge-bases" },
          { label: "Conversations", value: "—", href: "/dashboard/chat" },
        ].map((stat) => (
          <a
            key={stat.label}
            href={stat.href}
            className="bg-white rounded-xl border border-gray-200 p-5 hover:border-blue-300 transition-colors"
          >
            <p className="text-sm text-gray-500">{stat.label}</p>
            <p className="text-2xl font-semibold text-gray-900 mt-1">{stat.value}</p>
          </a>
        ))}
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
