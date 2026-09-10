import type { Metadata } from "next"
import { Outfit, Geist_Mono } from "next/font/google"
import "./globals.css"

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "NexusRAG",
  description: "Multi-document intelligent Q&A system",
  themeColor: "#0d0f16",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${outfit.variable} ${geistMono.variable} min-h-dvh overflow-x-hidden bg-background text-foreground`}>
        {children}
      </body>
    </html>
  )
}
