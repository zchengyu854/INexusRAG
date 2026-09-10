"use client"

import { useRef, useEffect } from "react"
import { gsap } from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"
import { MessageCircle, FileText, Cpu, Eye } from "lucide-react"

gsap.registerPlugin(ScrollTrigger)

const features = [
  {
    icon: MessageCircle,
    title: "Conversational Q&A",
    desc: "Ask questions in natural language. Answers are grounded in your documents, not hallucinated.",
    image: "https://picsum.photos/seed/nexus-chat/800/600",
    span: "md:col-span-2",
  },
  {
    icon: FileText,
    title: "Multi-Document Ingestion",
    desc: "PDF, Markdown, TXT. Automatic chunking with semantic boundaries.",
    image: "https://picsum.photos/seed/nexus-docs/600/600",
    span: "",
  },
  {
    icon: Cpu,
    title: "Pluggable LLM",
    desc: "OpenAI, Ollama, any compatible provider. Switch with one click.",
    image: "https://picsum.photos/seed/nexus-llm/600/600",
    span: "",
  },
  {
    icon: Eye,
    title: "Source Attribution",
    desc: "Every answer cites its sources. Trace claims back to exact pages and chunks.",
    image: "https://picsum.photos/seed/nexus-sources/800/600",
    span: "md:col-span-2",
  },
]

export function FeatureBento() {
  const gridRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.utils.toArray<HTMLElement>(".bento-cell").forEach((cell, i) => {
        gsap.fromTo(
          cell,
          { opacity: 0, y: 40, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.6,
            ease: "power3.out",
            scrollTrigger: {
              trigger: cell,
              start: "top 88%",
              toggleActions: "play none none none",
            },
            delay: i * 0.08,
          }
        )
      })
    }, gridRef)

    return () => ctx.revert()
  }, [])

  return (
    <div ref={gridRef}>
      <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.22em] text-foreground/30">
        What you can do
      </p>
      <h2 className="mb-10 max-w-2xl text-3xl font-semibold tracking-tight md:text-4xl">
        One interface for your entire knowledge base
      </h2>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3" style={{ gridAutoFlow: "dense" }}>
        {features.map((f) => (
          <div
            key={f.title}
            className={`bento-cell group relative overflow-hidden rounded-2xl border border-white/[0.06] bg-card transition-all duration-500 hover:border-white/[0.12] hover:shadow-[0_20px_60px_rgba(0,0,0,0.4)] ${f.span}`}
          >
            {/* Image */}
            <div className="aspect-[16/10] w-full overflow-hidden">
              <img
                src={f.image}
                alt=""
                className="h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
                loading="lazy"
              />
            </div>

            {/* Content */}
            <div className="relative space-y-2 p-5">
              <div className="flex items-center gap-2.5">
                <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15">
                  <f.icon className="size-4 text-primary" />
                </div>
                <h3 className="text-sm font-semibold">{f.title}</h3>
              </div>
              <p className="text-sm leading-relaxed text-foreground/50">
                {f.desc}
              </p>
            </div>

            {/* Gradient overlay on image */}
            <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-background/60 to-transparent" />
          </div>
        ))}
      </div>
    </div>
  )
}
