"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

function useReveal(): [React.RefObject<HTMLDivElement | null>, boolean] {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { threshold: 0.12 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return [ref, visible];
}

const MARQUEE_ITEMS = [
  "Hybrid retrieval", "Claim verification", "Evidence citation",
  "Structured data", "Reranking", "Adaptive expansion",
  "Conflict detection", "Full observability", "Document versioning",
];

const ACCORDIONS = [
  {
    title: "Upload any document",
    body: "Ragix parses PDF, DOCX, Markdown and TXT files, then chunks and embeds them with structure-aware splitting.",
    color: "#a78bfa",
  },
  {
    title: "Ask in plain English",
    body: "No query syntax. Write naturally. The retrieval layer handles semantic matching, keyword fallback, and query expansion.",
    color: "#34d399",
  },
  {
    title: "Get verified answers",
    body: "Every answer is backed by retrieved chunks. Contradictions are surfaced, and low-confidence answers are flagged instead of guessed.",
    color: "#fbbf24",
  },
  {
    title: "Trace every decision",
    body: "Open the evidence panel to see what was retrieved, how it ranked, and why. Full retrieval debugger for engineering teams.",
    color: "#60a5fa",
  },
];

export default function LandingPage() {
  const [heroRef, heroVisible] = useReveal();
  const [marqueeRef, marqueeVisible] = useReveal();
  const [bentoRef, bentoVisible] = useReveal();
  const [accordionRef, accordionVisible] = useReveal();
  const [ctaRef, ctaVisible] = useReveal();
  const [openAccordion, setOpenAccordion] = useState(0);

  useEffect(() => {
    const prev = document.body.style.background;
    document.body.style.background = "#06040f";
    return () => { document.body.style.background = prev; };
  }, []);

  return (
    <div style={{ background: "#06040f", minHeight: "100%", overflowX: "hidden", fontFamily: "var(--font-jakarta), system-ui, sans-serif" }}>

      {/* Ambient background glow */}
      <div aria-hidden style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
        <div style={{ position: "absolute", top: "5%", left: "50%", transform: "translateX(-50%)", width: "900px", height: "700px", background: "radial-gradient(ellipse, rgba(106,53,255,0.15) 0%, transparent 68%)", filter: "blur(80px)" }} />
        <div style={{ position: "absolute", bottom: "10%", right: "5%", width: "500px", height: "500px", background: "radial-gradient(ellipse, rgba(167,139,250,0.06) 0%, transparent 70%)", filter: "blur(60px)" }} />
      </div>

      {/* Floating glass nav */}
      <header style={{ position: "fixed", top: "20px", left: "50%", transform: "translateX(-50%)", zIndex: 100, width: "calc(100% - 48px)", maxWidth: "900px" }}>
        <nav style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(6,4,15,0.7)", backdropFilter: "blur(24px)", WebkitBackdropFilter: "blur(24px)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "9999px", padding: "12px 20px 12px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden>
              <rect width="32" height="32" rx="7" fill="#0d0a1f" />
              <rect x="6" y="18" width="8" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.55" />
              <rect x="6" y="21.5" width="6" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.4" />
              <rect x="6" y="25" width="4" height="1.6" rx="0.8" fill="#c4b5fd" opacity="0.25" />
              <polygon points="20,7 24,18.5 21.2,18.5 24,28 16,18.5 19,18.5" fill="#a78bfa" />
              <circle cx="12.5" cy="11.5" r="2.8" fill="none" stroke="#a78bfa" strokeWidth="1.5" />
              <line x1="14.5" y1="13.5" x2="17" y2="16" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <span style={{ color: "#fff", fontWeight: 700, fontSize: "15px", letterSpacing: "-0.3px" }}>Ragix</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Link href="/auth/login" style={{ color: "rgba(255,255,255,0.55)", fontSize: "13px", fontWeight: 500, padding: "8px 16px", borderRadius: "9999px", textDecoration: "none", transition: "color 0.2s" }}>
              Sign in
            </Link>
            <Link href="/auth/signup" style={{ background: "#6a35ff", color: "#fff", fontSize: "13px", fontWeight: 600, padding: "9px 20px", borderRadius: "9999px", textDecoration: "none", boxShadow: "0 8px 24px rgba(106,53,255,0.35)" }}>
              Get started free
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section id="main-content" style={{ position: "relative", zIndex: 1, maxWidth: "1100px", margin: "0 auto", padding: "200px 24px 140px", textAlign: "center" }}>
        <div
          ref={heroRef} className="rag-reveal"
          style={{ transition: "opacity 0.9s cubic-bezier(0.16,1,0.3,1), transform 0.9s cubic-bezier(0.16,1,0.3,1)", opacity: heroVisible ? 1 : 0, transform: heroVisible ? "none" : "translateY(36px)" }}
        >

          <h1 style={{ fontSize: "clamp(3rem, 5.5vw, 5.5rem)", fontWeight: 800, color: "#fff", lineHeight: 1.06, letterSpacing: "-2.5px", maxWidth: "900px", margin: "0 auto 28px" }}>
            AI answers your team<br />
            <span style={{ background: "linear-gradient(135deg, #c4b5fd 0%, #a78bfa 40%, #6a35ff 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              can trust
            </span>
          </h1>

          <p style={{ fontSize: "18px", color: "rgba(255,255,255,0.5)", lineHeight: 1.75, maxWidth: "540px", margin: "0 auto 52px" }}>
            Upload documents, ask questions, get verified answers with cited sources. When the evidence is thin, Ragix says so instead of guessing.
          </p>

          <div style={{ display: "flex", gap: "14px", justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/auth/signup" style={{ background: "#6a35ff", color: "#fff", fontWeight: 700, fontSize: "15px", padding: "15px 36px", borderRadius: "14px", textDecoration: "none", boxShadow: "0 20px 56px rgba(106,53,255,0.45)", letterSpacing: "-0.2px" }}>
              Start for free
            </Link>
            <Link href="/auth/login" style={{ background: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.8)", fontWeight: 600, fontSize: "15px", padding: "15px 36px", borderRadius: "14px", textDecoration: "none", border: "1px solid rgba(255,255,255,0.1)" }}>
              Sign in to workspace
            </Link>
          </div>
        </div>
      </section>

      {/* Marquee strip */}
      <div
        ref={marqueeRef} className="rag-reveal"
        style={{ borderTop: "1px solid rgba(255,255,255,0.05)", borderBottom: "1px solid rgba(255,255,255,0.05)", padding: "20px 0", overflow: "hidden", position: "relative", zIndex: 1, transition: "opacity 0.7s", opacity: marqueeVisible ? 1 : 0 }}
      >
        <style>{`
          @keyframes rag-marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
          .rag-marquee { display: flex; gap: 0; animation: rag-marquee 28s linear infinite; width: max-content; }
          @media (prefers-reduced-motion: reduce) { .rag-marquee { animation: none; } .rag-reveal { opacity: 1 !important; transform: none !important; transition: none !important; } }
        `}</style>
        <div className="rag-marquee">
          {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((item, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "0", padding: "0 32px" }}>
              <span style={{ color: "rgba(255,255,255,0.5)", fontSize: "12px", fontWeight: 600, letterSpacing: "1.2px", textTransform: "uppercase", whiteSpace: "nowrap" }}>{item}</span>
              <span style={{ color: "rgba(106,53,255,0.5)", fontSize: "20px", marginLeft: "32px" }}>·</span>
            </div>
          ))}
        </div>
      </div>

      {/* Bento grid */}
      <section style={{ maxWidth: "1100px", margin: "0 auto", padding: "120px 24px 80px", position: "relative", zIndex: 1 }}>
        <div ref={bentoRef} className="rag-reveal" style={{ transition: "opacity 0.8s, transform 0.8s cubic-bezier(0.16,1,0.3,1)", opacity: bentoVisible ? 1 : 0, transform: bentoVisible ? "none" : "translateY(28px)" }}>
          <h2 style={{ fontSize: "clamp(2rem, 3.5vw, 3.2rem)", fontWeight: 800, color: "#fff", letterSpacing: "-1.5px", marginBottom: "12px" }}>
            How Ragix answers
          </h2>
          <p style={{ color: "rgba(255,255,255,0.38)", fontSize: "16px", marginBottom: "48px", maxWidth: "460px" }}>
            Ragix retrieves the evidence, verifies each claim against it, and shows its work.
          </p>

          {/* 4-col bento: c1 col-span-2 row-span-2 | c2 col-span-2 row-span-1 | c3 col-span-2 row-span-1 */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gridAutoRows: "220px", gap: "14px", gridAutoFlow: "dense" }}>

            {/* c1 — big card */}
            <div style={{ gridColumn: "span 2", gridRow: "span 2", background: "linear-gradient(145deg, #100c24 0%, #1a1140 100%)", borderRadius: "22px", border: "1px solid rgba(106,53,255,0.22)", padding: "36px", display: "flex", flexDirection: "column", justifyContent: "space-between", overflow: "hidden", position: "relative", cursor: "default", transition: "border-color 0.3s", }}>
              <div aria-hidden style={{ position: "absolute", bottom: "-60px", right: "-60px", width: "300px", height: "300px", background: "radial-gradient(circle, rgba(106,53,255,0.2) 0%, transparent 65%)", borderRadius: "50%" }} />
              <div style={{ width: "48px", height: "48px", borderRadius: "14px", background: "rgba(106,53,255,0.18)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="22" height="22" fill="none" stroke="#a78bfa" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden>
                  <circle cx="11" cy="11" r="8" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35" />
                </svg>
              </div>
              <div style={{ position: "relative" }}>
                <h3 style={{ color: "#fff", fontSize: "22px", fontWeight: 700, letterSpacing: "-0.5px", marginBottom: "12px" }}>Hybrid retrieval</h3>
                <p style={{ color: "rgba(255,255,255,0.45)", fontSize: "14.5px", lineHeight: 1.7 }}>
                  Semantic and keyword search combined with a cross-encoder re-ranker, so the most relevant chunks rank first.
                </p>
                <div style={{ display: "flex", gap: "8px", marginTop: "24px", flexWrap: "wrap" }}>
                  {["BM25 + dense", "Re-ranking", "Expansion ladder"].map((tag) => (
                    <span key={tag} style={{ background: "rgba(106,53,255,0.15)", border: "1px solid rgba(106,53,255,0.25)", borderRadius: "9999px", padding: "4px 12px", fontSize: "11px", color: "#c4b5fd", fontWeight: 600, letterSpacing: "0.2px" }}>{tag}</span>
                  ))}
                </div>
              </div>
            </div>

            {/* c2 — claim verification */}
            <div style={{ gridColumn: "span 2", gridRow: "span 1", background: "#0c0a1c", borderRadius: "20px", border: "1px solid rgba(52,211,153,0.18)", padding: "28px 32px", display: "flex", gap: "22px", alignItems: "center", overflow: "hidden", position: "relative" }}>
              <div style={{ width: "44px", height: "44px", borderRadius: "13px", background: "rgba(52,211,153,0.12)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <svg width="20" height="20" fill="none" stroke="#34d399" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 style={{ color: "#fff", fontSize: "17px", fontWeight: 700, letterSpacing: "-0.3px", marginBottom: "6px" }}>Claim verification</h3>
                <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "13px", lineHeight: 1.65 }}>Every answer is checked against source material. Conflicting evidence is surfaced automatically.</p>
              </div>
            </div>

            {/* c3 — observability */}
            <div style={{ gridColumn: "span 2", gridRow: "span 1", background: "#0c0a1c", borderRadius: "20px", border: "1px solid rgba(245,158,11,0.18)", padding: "28px 32px", display: "flex", gap: "22px", alignItems: "center", overflow: "hidden" }}>
              <div style={{ width: "44px", height: "44px", borderRadius: "13px", background: "rgba(245,158,11,0.1)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <svg width="20" height="20" fill="none" stroke="#fbbf24" strokeWidth="1.8" viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <div>
                <h3 style={{ color: "#fff", fontSize: "17px", fontWeight: 700, letterSpacing: "-0.3px", marginBottom: "6px" }}>Full observability</h3>
                <p style={{ color: "rgba(255,255,255,0.4)", fontSize: "13px", lineHeight: 1.65 }}>Trace every retrieval step: what was fetched, how it ranked, and why the model answered or abstained.</p>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Horizontal accordion — How it works */}
      <section style={{ maxWidth: "1100px", margin: "0 auto", padding: "40px 24px 120px", position: "relative", zIndex: 1 }}>
        <div ref={accordionRef} className="rag-reveal" style={{ transition: "opacity 0.8s, transform 0.8s cubic-bezier(0.16,1,0.3,1)", opacity: accordionVisible ? 1 : 0, transform: accordionVisible ? "none" : "translateY(28px)" }}>
          <h2 style={{ fontSize: "clamp(1.8rem, 3vw, 2.8rem)", fontWeight: 800, color: "#fff", letterSpacing: "-1.2px", marginBottom: "48px" }}>
            From upload to answer<br />in four steps
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
            {ACCORDIONS.map((item, i) => (
              <div
                key={i}
                style={{ borderRadius: "14px", border: `1px solid ${openAccordion === i ? item.color + "30" : "rgba(255,255,255,0.06)"}`, background: openAccordion === i ? "rgba(255,255,255,0.04)" : "transparent", transition: "all 0.3s" }}
              >
                <h3 style={{ margin: 0 }}>
                  <button
                    type="button"
                    id={`accordion-trigger-${i}`}
                    aria-expanded={openAccordion === i}
                    aria-controls={`accordion-panel-${i}`}
                    onClick={() => setOpenAccordion(i)}
                    style={{ display: "flex", width: "100%", alignItems: "center", justifyContent: "space-between", gap: "16px", padding: "24px 28px", background: "none", border: "none", borderRadius: "14px", color: "inherit", font: "inherit", textAlign: "left", cursor: "pointer" }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: "16px" }}>
                      <span style={{ width: "28px", height: "28px", borderRadius: "50%", background: openAccordion === i ? item.color + "20" : "rgba(255,255,255,0.06)", border: `1px solid ${openAccordion === i ? item.color + "40" : "rgba(255,255,255,0.1)"}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", fontWeight: 700, color: openAccordion === i ? item.color : "rgba(255,255,255,0.55)", flexShrink: 0, transition: "all 0.3s" }}>
                        {i + 1}
                      </span>
                      <span style={{ color: openAccordion === i ? "#fff" : "rgba(255,255,255,0.6)", fontSize: "16px", fontWeight: 600, letterSpacing: "-0.2px", transition: "color 0.3s" }}>{item.title}</span>
                    </span>
                    <svg width="16" height="16" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="2" viewBox="0 0 24 24" style={{ transform: openAccordion === i ? "rotate(180deg)" : "none", transition: "transform 0.3s", flexShrink: 0 }} aria-hidden>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                </h3>
                <div
                  id={`accordion-panel-${i}`}
                  role="region"
                  aria-labelledby={`accordion-trigger-${i}`}
                  style={{ maxHeight: openAccordion === i ? "220px" : "0", visibility: openAccordion === i ? "visible" : "hidden", overflow: "hidden", transition: "max-height 0.4s cubic-bezier(0.16,1,0.3,1)" }}
                >
                  <p style={{ color: "rgba(255,255,255,0.6)", fontSize: "14px", lineHeight: 1.7, margin: 0, padding: "0 28px 24px 72px" }}>{item.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{ maxWidth: "1100px", margin: "0 auto", padding: "0 24px 160px", position: "relative", zIndex: 1 }}>
        <div
          ref={ctaRef} className="rag-reveal"
          style={{ background: "linear-gradient(135deg, #6a35ff 0%, #4a1fcf 100%)", borderRadius: "28px", padding: "80px 48px", textAlign: "center", position: "relative", overflow: "hidden", transition: "opacity 0.9s, transform 0.9s cubic-bezier(0.16,1,0.3,1)", opacity: ctaVisible ? 1 : 0, transform: ctaVisible ? "none" : "translateY(40px) scale(0.97)" }}
        >
          <div aria-hidden style={{ position: "absolute", top: "-80px", right: "-80px", width: "360px", height: "360px", background: "rgba(255,255,255,0.07)", borderRadius: "50%" }} />
          <div aria-hidden style={{ position: "absolute", bottom: "-100px", left: "-60px", width: "320px", height: "320px", background: "rgba(255,255,255,0.04)", borderRadius: "50%" }} />
          <h2 style={{ fontSize: "clamp(2rem, 3.5vw, 3.2rem)", fontWeight: 800, color: "#fff", letterSpacing: "-1.5px", marginBottom: "16px", position: "relative" }}>
            Try Ragix on<br />your own documents
          </h2>
          <p style={{ color: "rgba(255,255,255,0.65)", fontSize: "16px", marginBottom: "44px", position: "relative" }}>
            Create a workspace and upload your first document.
          </p>
          <div style={{ display: "flex", gap: "14px", justifyContent: "center", flexWrap: "wrap", position: "relative" }}>
            <Link href="/auth/signup" style={{ background: "#fff", color: "#4a1fcf", fontWeight: 700, fontSize: "15px", padding: "15px 36px", borderRadius: "13px", textDecoration: "none", letterSpacing: "-0.2px" }}>
              Get started free
            </Link>
            <Link href="/auth/login" style={{ background: "rgba(255,255,255,0.12)", color: "#fff", fontWeight: 600, fontSize: "15px", padding: "15px 36px", borderRadius: "13px", textDecoration: "none", border: "1px solid rgba(255,255,255,0.2)" }}>
              Sign in
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: "1px solid rgba(255,255,255,0.05)", padding: "32px 24px", textAlign: "center", position: "relative", zIndex: 1 }}>
        <p style={{ color: "rgba(255,255,255,0.45)", fontSize: "13px" }}>
          &copy; {new Date().getFullYear()} Ragix
        </p>
      </footer>
    </div>
  );
}
