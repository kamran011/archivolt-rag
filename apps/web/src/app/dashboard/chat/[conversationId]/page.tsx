import ChatInterface from "@/components/chat/ChatInterface";

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  return (
    <div className="h-full">
      <ChatInterface initialConversationId={conversationId} />
    </div>
  );
}
