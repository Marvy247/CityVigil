import Link from "next/link"
import { Shield } from "lucide-react"

export function Footer() {
  return (
    <footer
      className="border-t border-slate-200 py-10 px-8"
      style={{ background: "#f8fafc" }}
    >
      <div className="max-w-6xl mx-auto flex flex-col gap-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-sky-500 to-sky-600 flex items-center justify-center">
              <Shield className="w-4 h-4 text-slate-900" />
            </div>
            <span className="font-bold text-sm tracking-tight text-slate-900">CityVigil</span>
          </Link>

          <nav className="flex items-center gap-6 text-xs text-slate-500">
            <Link href="/dashboard" className="hover:text-slate-900 transition-colors">
              Dashboard
            </Link>
            <a href="#layers" className="hover:text-slate-900 transition-colors">
              Layers
            </a>
            <a href="#about" className="hover:text-slate-900 transition-colors">
              About
            </a>
          </nav>
        </div>

        <p className="text-[11px] leading-relaxed text-slate-500 max-w-4xl">
          Temperature data © FortyGuard. Vulnerability and geography from CDC/ATSDR
          and the US Census Bureau. Cooling-site data from the Maricopa Association
          of Governments Heat Relief Network. Built for FortyGuard Hackathon&apos;26.
          Cooling-site coverage reflects the current season, not any past heat event.
        </p>
      </div>
    </footer>
  )
}
