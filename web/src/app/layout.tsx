import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: { default: "Range", template: "%s · Range" },
  description:
    "A calm, read-only personal trading terminal: TTM power-range zones, portfolio at a glance, and Kes, an agent that explains and never trades.",
};

// Applies the saved colour-safe preference before first paint (no flash).
const colorSafeBoot = `try{if(localStorage.getItem("range.colorsafe")==="1")document.documentElement.dataset.colorsafe="true"}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geist.variable} ${geistMono.variable} ${instrumentSerif.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: colorSafeBoot }} />
      </head>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
