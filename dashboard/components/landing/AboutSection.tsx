"use client"

import { useRef } from "react"
import Link from "next/link"
import { motion, useInView } from "framer-motion"
import { ArrowRight } from "lucide-react"

const stats = [
  { label: "17.6M person-hours above 100 °F, one week, one district" },
  { label: "10,177 heat tiles joined to 57 census tracts, none dropped" },
  { label: "Runs offline from a committed cache — no API key needed" },
]

export function AboutSection() {
  const sectionRef = useRef<HTMLDivElement>(null)
  const inView = useInView(sectionRef, { once: true, margin: "-150px" })

  return (
    <section
      id="about"
      ref={sectionRef}
      className="relative overflow-hidden py-32"
      style={{
        background:
          "linear-gradient(160deg, #f8fafc 0%, #ffffff 50%, #f1f5f9 100%)",
      }}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(2,132,199,0.07) 0%, transparent 70%)",
        }}
      />

      <div className="relative z-10 container mx-auto px-8 max-w-6xl">
        <div className="grid lg:grid-cols-2 gap-20 items-center">
          <div>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
              transition={{ duration: 0.6, ease: "easeOut" }}
              className="text-xs font-mono text-sky-400/70 tracking-[0.2em] uppercase mb-6"
            >
              / About
            </motion.p>
            <motion.h2
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 30 }}
              transition={{ duration: 0.7, delay: 0.1, ease: "easeOut" }}
              className="text-4xl md:text-5xl font-light text-slate-900 leading-tight mb-8"
            >
              It decides who
              <br />
              <span className="text-sky-300">gets protected first</span>
            </motion.h2>
            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
              transition={{ duration: 0.7, delay: 0.2, ease: "easeOut" }}
              className="text-slate-600 leading-relaxed mb-10 text-base"
            >
              Extreme heat is not distributed evenly, and neither is protection. CityVigil
              joins hyperlocal temperature intelligence to published vulnerability and real
              cooling-centre hours, then ranks who needs help first — showing both the
              weighted ranking and the unweighted one, because hiding a modelling choice
              inside a headline is how these tools lose trust.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
              transition={{ duration: 0.7, delay: 0.3, ease: "easeOut" }}
              className="flex gap-4 flex-wrap"
            >
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 bg-sky-600 text-white font-semibold text-sm px-6 py-3 rounded-full hover:bg-sky-700 transition-all duration-200"
              >
                Open the dashboard <ArrowRight className="w-4 h-4" />
              </Link>
              <a
                href="#layers"
                className="inline-flex items-center gap-2 border border-slate-300 text-slate-600 text-sm px-6 py-3 rounded-full hover:bg-slate-100 transition-all duration-200"
              >
                See how it works
              </a>
            </motion.div>
          </div>

          <div className="grid grid-cols-1 gap-6">
            {stats.map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, x: 30 }}
                animate={inView ? { opacity: 1, x: 0 } : { opacity: 0, x: 30 }}
                transition={{ duration: 0.7, delay: 0.15 + i * 0.12, ease: "easeOut" }}
                className="flex items-center p-6 rounded-2xl border border-slate-200 bg-slate-50"
              >
                <span className="text-slate-600 text-base font-light">{stat.label}</span>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}