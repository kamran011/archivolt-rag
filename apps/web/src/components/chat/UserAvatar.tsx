"use client";

import { useCurrentUser } from "@/hooks/useCurrentUser";

export default function UserAvatar({ size = 32 }: { size?: number }) {
  const { initials } = useCurrentUser();
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.34,
        background: "linear-gradient(140deg, #c4b5fd, var(--primary))",
      }}
      aria-hidden
    >
      {initials}
    </div>
  );
}
