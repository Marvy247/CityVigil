"use client"

import { useRef } from "react"
import { motion, useScroll, useTransform } from "framer-motion"
import { Clock, ClipboardCheck, Split, Users } from "lucide-react"

const features = [
  {
    num: "01",
    icon: Users,
    title: "Real people, not mock data",
    desc: "1,009 Maricopa census tracts from CDC/ATSDR social vulnerability, Census geography and workplace-keyed job counts. Every indicator traces to a published row, with SHA-256 provenance for every file.",
  },
  {
    num: "02",
    icon: Clock,
    title: "Coverage measured by the hour",
    desc: "A cooling centre that closes at 17:00 protects nobody at 19:00. Real opening hours turn a map of pins into a map of protection, and the network loses 76% of its capacity between 15:00 and 19:00.",
  },
  {
    num: "03",
    icon: Split,
    title: "Separates the free fix from the costly one",
    desc: "Only 14 of 57 tracts have a walkable site even at full capacity — that needs buildings. But 9 tracts, 33,954 residents, lose cooling purely to closing times. That needs a schedule change.",
  },
  {
    num: "04",
    icon: ClipboardCheck,
    title: "Tested against real deaths, honestly",
    desc: "Ranked against 2023 recorded heat mortality across 92 ZIPs. Every ranking beats chance (AUC 0.68–0.82), but plain heat exposure scores highest at 0.824 against our weighted model's 0.754 — so we report the weighting as unproven rather than claim a win.",
  },
]

export function FeaturesSection() {
  const containerRef = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"],
  })

  const headerY = useTransform(scrollYProgress, [0, 0.1], [30, 0])
  const headerOp = useTransform(scrollYProgress, [0, 0.1], [0, 1])

  const y0 = useTransform(scrollYProgress, [0.04, 0.18], [45, 0])
  const op0 = useTransform(scrollYProgress, [0.04, 0.18], [0, 1])

  const y1 = useTransform(scrollYProgress, [0.22, 0.36], [45, 0])
  const op1 = useTransform(scrollYProgress, [0.22, 0.36], [0, 1])

  const y2 = useTransform(scrollYProgress, [0.42, 0.56], [45, 0])
  const op2 = useTransform(scrollYProgress, [0.42, 0.56], [0, 1])

  const y3 = useTransform(scrollYProgress, [0.62, 0.76], [45, 0])
  const op3 = useTransform(scrollYProgress, [0.62, 0.76], [0, 1])

  const itemStyles = [
    { y: y0, opacity: op0 },
    { y: y1, opacity: op1 },
    { y: y2, opacity: op2 },
    { y: y3, opacity: op3 },
  ]

  return (
    <div ref={containerRef} id="features" className="relative h-[450vh] bg-[#ffffff]">
      <div className="sticky top-0 h-screen flex flex-col justify-center px-8 md:px-16 lg:px-24 overflow-hidden">
        <div className="max-w-5xl w-full mx-auto">
          <motion.div style={{ y: headerY, opacity: headerOp }} className="mb-12">
            <p className="text-xs font-mono text-sky-400/70 tracking-[0.2em] uppercase mb-5">
              / Platform Capabilities
            </p>
            <h2 className="text-5xl md:text-6xl font-light text-slate-900 tracking-tight">
              Core Features
            </h2>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {features.map((feature, i) => (
              <motion.div
                key={feature.num}
                style={itemStyles[i]}
                className="group relative"
              >
                <div className="flex items-start gap-6 p-8 rounded-2xl border border-slate-200 hover:border-sky-500/30 bg-slate-50 hover:bg-slate-50 transition-all duration-500">
                  <div className="shrink-0">
                    <span className="text-xs font-mono text-slate-400 block mb-4">{feature.num}</span>
                    <div className="w-12 h-12 rounded-xl bg-sky-500/10 flex items-center justify-center group-hover:bg-sky-500/20 transition-colors duration-300">
                      <feature.icon className="w-5 h-5 text-sky-400" />
                    </div>
                  </div>
                  <div>
                    <h3 className="text-xl font-light text-slate-900 mb-3">{feature.title}</h3>
                    <p className="text-slate-600 text-sm leading-relaxed">{feature.desc}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}