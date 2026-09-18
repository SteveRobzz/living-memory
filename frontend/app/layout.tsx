import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Living Memory",
  description: "RAG retrieves information. Living Memory decides what is still true.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
