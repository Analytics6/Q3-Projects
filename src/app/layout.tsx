import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Finwell | Banking support, clearly answered",
  description: "A source-grounded support assistant for cards and loans.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
