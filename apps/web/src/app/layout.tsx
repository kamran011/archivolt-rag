import type { Metadata } from "next";
import { Geist_Mono, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Ragix — AI Knowledge Platform",
  description:
    "Production-grade AI knowledge and evidence platform. Retrieve the right evidence, verify answers, cite sources.",
  metadataBase: new URL("https://archivolt-rag.vercel.app"),
  alternates: {
    canonical: "https://archivolt-rag.vercel.app",
  },
  openGraph: {
    title: "Ragix — AI Knowledge Platform",
    description:
      "Production-grade AI knowledge and evidence platform. Retrieve the right evidence, verify answers, cite sources.",
    url: "https://archivolt-rag.vercel.app",
    siteName: "Ragix",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Ragix — AI Knowledge Platform",
    description:
      "Production-grade AI knowledge and evidence platform. Retrieve the right evidence, verify answers, cite sources.",
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Ragix",
  applicationCategory: "BusinessApplication",
  description:
    "Production-grade AI knowledge and evidence platform. Retrieve the right evidence, verify answers, cite sources.",
  url: "https://archivolt-rag.vercel.app",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  operatingSystem: "Web",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body
        className={`${jakarta.variable} ${geistMono.variable} antialiased`}
      >
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-[9999] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white focus:shadow-lg"
        >
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
