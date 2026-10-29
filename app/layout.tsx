import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Care Credits — APC Renewal Dashboard",
  description: "Track CPD points, monitor compliance, and prepare for APC renewal.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased"><a className="skip-link" href="#main-content">Skip to content</a>{children}</body>
    </html>
  );
}
