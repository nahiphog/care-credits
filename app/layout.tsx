import type { Metadata } from "next";
import "./globals.css";
import "./shared.css";

export const metadata: Metadata = {
  title: "Care Credits — Professional Learning",
  description: "Discover professional training and keep a personal, self-reported CPD learning record.",
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
      <body className="antialiased">{children}</body>
    </html>
  );
}
