import type { Metadata, Viewport } from "next"
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
  description: "多文档智能问答系统",
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f7f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0d0f16" },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={`${outfit.variable} ${geistMono.variable} min-h-dvh overflow-hidden bg-background text-foreground`}>
        {children}
      </body>
    </html>
  )
}
