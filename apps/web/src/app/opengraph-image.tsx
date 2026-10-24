import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Ragix — AI Knowledge Platform";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#0d0a1f",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "sans-serif",
          gap: 24,
        }}
      >
        {/* Logo mark */}
        <svg width="80" height="80" viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="7" fill="#1a1530" />
          <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55" />
          <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4" />
          <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25" />
          <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa" />
          <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5" />
          <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
        </svg>

        {/* Wordmark */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <span style={{ color: "#ffffff", fontSize: 72, fontWeight: 700, letterSpacing: "-2px" }}>
            Ragix
          </span>
          <span style={{ color: "#a78bfa", fontSize: 28, fontWeight: 400, letterSpacing: "0px" }}>
            AI Knowledge Platform
          </span>
        </div>

        {/* Tagline */}
        <span
          style={{
            color: "#718096",
            fontSize: 20,
            fontWeight: 400,
            marginTop: 8,
            maxWidth: 700,
            textAlign: "center",
          }}
        >
          Retrieve the right evidence · Verify answers · Cite sources
        </span>
      </div>
    ),
    { ...size }
  );
}
