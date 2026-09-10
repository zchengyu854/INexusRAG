"use client"

import { useRef, useEffect } from "react"
import { gsap } from "gsap"
import { ScrollTrigger } from "gsap/ScrollTrigger"
import { MessageCircle, ArrowDown } from "lucide-react"

gsap.registerPlugin(ScrollTrigger)

interface HeroSectionProps {
  onGoToChat: () => void
  onGoToDocuments: () => void
}

export function HeroSection({ onGoToChat, onGoToDocuments }: HeroSectionProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wordsRef = useRef<HTMLSpanElement[]>([])

  useEffect(() => {
    const ctx = gsap.context(() => {
      // Word-by-word reveal on load
      gsap.fromTo(
        wordsRef.current,
        { opacity: 0, y: 24, rotateX: 40 },
        {
          opacity: 1,
          y: 0,
          rotateX: 0,
          duration: 0.7,
          stagger: 0.06,
          ease: "power3.out",
          delay: 0.15,
        }
      )

      // Badge fade in
      gsap.fromTo(
        ".hero-badge",
        { opacity: 0, scale: 0.9 },
        { opacity: 1, scale: 1, duration: 0.5, ease: "power2.out", delay: 0.6 }
      )

      // CTA buttons
      gsap.fromTo(
        ".hero-cta",
        { opacity: 0, y: 16 },
        { opacity: 1, y: 0, duration: 0.5, ease: "power2.out", stagger: 0.1, delay: 0.85 }
      )

      // Scroll pin — hero fades as user scrolls
      ScrollTrigger.create({
        trigger: containerRef.current,
        start: "top top",
        end: "bottom top",
        pin: true,
        pinSpacing: false,
        onUpdate: (self) => {
          const p = self.progress
          gsap.set(containerRef.current, {
            opacity: 1 - p * 1.5,
            scale: 1 - p * 0.05,
          })
        },
      })
    }, containerRef)

    return () => ctx.revert()
  }, [])

  const words = ["Knowledge,", "Made", "Conversational"]

  return (
    <section
      ref={containerRef}
      className="relative flex h-[100dvh] min-h-[600px] items-center overflow-hidden"
    >
      {/* Ambient glow */}
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(50% 50% at 70% 40%, oklch(0.68 0.19 45 / 0.18), transparent 70%)",
        }}
      />

      <div className="relative z-10 w-full px-4 sm:px-6">
        <div className="mx-auto max-w-6xl">
          <p className="hero-badge mb-6 font-mono text-xs uppercase tracking-[0.25em] text-foreground/40">
            Multi-document RAG · 1024D Embeddings
          </p>

          <h1 className="mb-8 max-w-5xl font-semibold tracking-tighter" style={{ fontSize: "clamp(2.8rem, 6vw, 5.5rem)", lineHeight: "1.05" }}>
            {words.map((word, i) => (
              <span
                key={i}
                ref={(el) => { wordsRef.current[i] = el! }}
                className="mr-[0.3em] inline-block"
                style={{ perspective: "600px" }}
              >
                {word}
              </span>
            ))}
          </h1>

          <p className="mb-12 max-w-lg text-base leading-relaxed text-foreground/55 md:text-lg">
            Upload documents. Ask questions. Get answers grounded in your
            knowledge base, with every claim traced back to its source.
          </p>

          <div className="flex flex-wrap gap-4">
            <button
              onClick={onGoToChat}
              className="hero-cta flex h-12 items-center gap-2.5 rounded-full bg-primary px-7 text-sm font-semibold text-primary-foreground shadow-[0_0_30px_oklch(0.68_0.19_45_/_0.25)] transition-all duration-300 hover:scale-[1.03] hover:shadow-[0_0_40px_oklch(0.68_0.19_45_/_0.35)]"
            >
              <MessageCircle className="size-4" />
              Start exploring
            </button>
            <button
              onClick={onGoToDocuments}
              className="hero-cta flex h-12 items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-6 text-sm font-medium text-foreground/70 backdrop-blur-sm transition-all duration-300 hover:border-white/20 hover:bg-white/[0.08] hover:text-foreground"
            >
              View documentation
            </button>
          </div>
        </div>

        {/* Scroll indicator */}
        <div className="absolute bottom-12 left-1/2 -translate-x-1/2">
          <ArrowDown className="size-5 animate-bounce text-foreground/25" />
        </div>
      </div>
    </section>
  )
}
