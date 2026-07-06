import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Nav from "./Nav";
import Providers from "./Providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "civicscope — ask about Philadelphia legislation",
  description:
    "Ask plain-English questions about Philadelphia City Council legislation. Answers are grounded in the real records with citations, or an honest refusal.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <Providers>
          <Nav />
          <div className="app-body">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
