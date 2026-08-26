'use client'

import { motion } from "framer-motion"
import { Shield, Wallet, TrendingUp, Zap, CheckCircle, LayoutDashboard } from "lucide-react"

export function DashboardOverview() {
  return (
    <div className="space-y-8">
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className="flex items-start justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Dashboard
          </h1>
          <p className="text-slate-500 mt-1 text-sm">Welcome to your dashboard overview.</p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
          className="lg:col-span-2 relative overflow-hidden rounded-2xl border border-sky-500/20 bg-gradient-to-br from-sky-500/[0.12] via-sky-500/[0.06] to-transparent backdrop-blur-xl p-7"
        >
          <div className="absolute top-0 right-0 w-48 h-48 bg-sky-500/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" aria-hidden="true" />
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-8 h-8 rounded-lg bg-sky-500/10 flex items-center justify-center">
                <Wallet className="w-4 h-4 text-sky-400" />
              </div>
              <p className="text-xs text-sky-400/80 font-semibold uppercase tracking-wider">Total Revenue</p>
            </div>
            <p className="text-5xl font-black text-white mt-2 tracking-tight">
              $12,500
            </p>
            <div className="flex items-center gap-2 mt-4">
              <span className="inline-flex items-center gap-1.5 text-xs text-sky-400/70 font-medium">
                <TrendingUp className="w-3.5 h-3.5" />
                142 transactions
              </span>
              <span className="w-1 h-1 rounded-full bg-sky-500/30" />
              <span className="text-xs text-sky-400/50">All time</span>
            </div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-2xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl p-6 hover:border-sky-500/20 hover:bg-white/[0.06] transition-all duration-300"
        >
          <div className="flex items-center gap-2 mb-4">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">Active</p>
          </div>
          <p className="text-3xl font-black text-white tracking-tight">24</p>
          <p className="text-xs text-slate-600 mt-2">Currently active</p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.25, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-2xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl p-6 hover:border-amber-500/20 hover:bg-white/[0.06] transition-all duration-300"
        >
          <div className="flex items-center gap-2 mb-4">
            <div className="w-2 h-2 rounded-full bg-amber-400" />
            <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">Pending</p>
          </div>
          <p className="text-3xl font-black text-white tracking-tight">7</p>
          <p className="text-xs text-slate-600 mt-2">Awaiting action</p>
        </motion.div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="lg:col-span-2 rounded-2xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl p-6"
        >
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-lg font-bold text-white">Recent Activity</h2>
              <p className="text-xs text-slate-500 mt-0.5">Latest updates</p>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-3 py-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </div>
          </div>

          <div className="space-y-2">
            {[
              { label: "New signup", detail: "John Doe joined", time: "2 min ago", icon: CheckCircle },
              { label: "Payment received", detail: "$500.00 USD", time: "15 min ago", icon: Zap },
              { label: "Settings updated", detail: "Profile configuration", time: "1 hour ago", icon: Shield },
            ].map((item, idx) => (
              <motion.div
                key={item.label}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className="flex items-center justify-between p-4 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04] transition-all duration-200"
              >
                <div className="flex items-center gap-3.5">
                  <div className="w-10 h-10 rounded-xl bg-sky-500/15 border border-sky-500/20 flex items-center justify-center text-xs font-bold shrink-0 backdrop-blur-xl">
                    <item.icon className="w-4 h-4 text-sky-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-200">{item.label}</p>
                    <p className="text-xs text-slate-600 mt-0.5">{item.detail}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-xs text-slate-500">{item.time}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-2xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl p-6"
        >
          <div className="flex items-center gap-2 mb-6">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">System Status</h2>
              <p className="text-xs text-slate-500">All systems operational</p>
            </div>
          </div>

          <div className="space-y-5">
            <div className="relative overflow-hidden rounded-xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/[0.12] to-emerald-500/[0.04] p-5">
              <div className="absolute -top-4 -right-4 w-24 h-24 bg-emerald-500/10 rounded-full blur-2xl" />
              <div className="relative z-10">
                <p className="text-xs text-emerald-400/70 font-semibold uppercase tracking-wider mb-2">Uptime</p>
                <p className="text-5xl font-black text-emerald-400">99.9%</p>
                <p className="text-xs text-emerald-400/60 mt-2">Last 30 days</p>
              </div>
            </div>

            {[
              { label: "API", value: "Operational", color: "text-emerald-400" },
              { label: "Database", value: "Operational", color: "text-emerald-400" },
              { label: "Auth", value: "Operational", color: "text-emerald-400" },
            ].map((item) => (
              <div key={item.label} className="flex items-center justify-between py-2">
                <span className="text-sm text-slate-400">{item.label}</span>
                <span className={`text-sm font-medium ${item.color} flex items-center gap-1.5`}>
                  <span className="w-1.5 h-1.5 rounded-full bg-current" />
                  {item.value}
                </span>
              </div>
            ))}

            <div className="pt-4 border-t border-white/[0.06]">
              <p className="text-xs text-emerald-400 flex items-center gap-2 font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                All systems operational
              </p>
            </div>
          </div>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.55, ease: [0.22, 1, 0.36, 1] }}
        className="rounded-2xl border border-white/[0.08] bg-white/[0.04] backdrop-blur-xl p-6"
      >
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-sky-500/10 flex items-center justify-center">
            <LayoutDashboard className="w-4 h-4 text-sky-400" />
          </div>
          <h2 className="text-lg font-bold text-white">Getting Started</h2>
        </div>
        <p className="text-slate-400 text-sm mb-4">
          This is a template dashboard. Customize it with your own data, charts, and widgets.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[
            { step: 1, title: "Connect your data", desc: "Integrate your APIs and data sources" },
            { step: 2, title: "Add your metrics", desc: "Define KPIs and display them here" },
            { step: 3, title: "Customize the UI", desc: "Adjust colors, layout, and branding" },
          ].map(({ step, title, desc }) => (
            <div
              key={step}
              className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 transition-all hover:border-sky-500/20 hover:bg-white/[0.04]"
            >
              <h3 className="font-semibold text-sm text-slate-300 mb-1">{title}</h3>
              <p className="text-xs text-slate-600">{desc}</p>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  )
}