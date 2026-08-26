"use client"

import { useEffect, useRef } from "react"

const layers = [
  {
    num: "01",
    title: "How hot is it?",
    subtitle: "tcm — snapshot temperature",
    tag: "Live",
    tagStyle: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    live: true,
    dim: false,
    desc: "Per-tile min, mean and max at 100 m resolution. Central Phoenix read 35.3–36.7 °C across 10,177 tiles. Verified Celsius, despite the API docs calling it Fahrenheit.",
  },
  {
    num: "02",
    title: "When does it peak?",
    subtitle: "time_of_measure — hour of peak",
    tag: "Live",
    tagStyle: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    live: true,
    dim: false,
    desc: "The hour each tile peaks — what schedules cooling-centre hours. Returns 16–17 for Phoenix. The docs call it UTC; measurement says local, and getting that wrong moves every recommendation by seven hours.",
  },
  {
    num: "03",
    title: "How long is it dangerous?",
    subtitle: "exceedance — hours past threshold",
    tag: "Live",
    tagStyle: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    live: true,
    dim: false,
    desc: "A count of hours above 100 °F — 80.6 to 91.9 over one week. Multiply by the residents exposed and you have person-hours in the API's own units, not an invented index.",
  },
  {
    num: "04",
    title: "Is there any relief?",
    subtitle: "persistence — longest unbroken run",
    tag: "Live",
    tagStyle: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    live: true,
    dim: false,
    desc: "The longest continuous dangerous stretch: 6.8–8.3 hours. Two blocks can log identical totals while one cools overnight and the other never does. Heat mortality tracks the second.",
  },
]

export function LayersSection() {
  const sectionRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view")
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.12 }
    )

    const items = sectionRef.current?.querySelectorAll(".reveal-item")
    items?.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <section id="layers" className="bg-slate-50 py-24 md:py-32">
      <style>{`
        .reveal-item {
          opacity: 0;
          transform: translateY(24px);
          transition: opacity 0.6s ease-out, transform 0.6s ease-out;
        }
        .reveal-item.in-view {
          opacity: 1;
          transform: translateY(0);
        }
        .reveal-item:nth-child(2) { transition-delay: 0.08s; }
        .reveal-item:nth-child(3) { transition-delay: 0.16s; }
        .reveal-item:nth-child(4) { transition-delay: 0.24s; }
      `}</style>

      <div ref={sectionRef} className="container mx-auto px-8 max-w-5xl">
        <div className="reveal-item mb-16">
          <p className="text-xs font-mono text-sky-400/70 tracking-[0.2em] uppercase mb-5">
            / Platform Tiers
          </p>
          <h2 className="text-5xl md:text-6xl font-light text-slate-900 tracking-tight">
            Three Layers
          </h2>
        </div>

        <div className="divide-y divide-white/[0.08]">
          {layers.map((layer) => (
            <div
              key={layer.num}
              className={`reveal-item group py-10 flex items-start gap-8 transition-opacity duration-300 ${
                layer.dim ? "opacity-60 hover:opacity-100" : ""
              }`}
            >
              <span className="text-xs font-mono text-sky-400 mt-1.5 w-8 shrink-0">
                {layer.num}
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap mb-2">
                  <h3 className="text-2xl md:text-3xl font-light text-slate-900">
                    {layer.title}
                  </h3>
                  <span
                    className={`inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1 rounded-full border ${layer.tagStyle}`}
                  >
                    {layer.live && (
                      <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                    )}
                    {layer.tag}
                  </span>
                </div>
                <p className="text-slate-500 text-sm font-medium tracking-wide mb-3">
                  {layer.subtitle}
                </p>
                <p className="text-slate-600 text-sm leading-relaxed max-w-2xl">
                  {layer.desc}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}