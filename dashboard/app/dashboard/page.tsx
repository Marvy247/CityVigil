'use client'

import { Suspense } from 'react'
import { Shield } from 'lucide-react'

import { DashboardLayout } from '@/components/dashboard-layout'
import { CityVigilDashboard } from '@/components/cityvigil/CityVigilDashboard'

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-dashboard">
          <div className="animate-pulse text-slate-400">Loading CityVigil…</div>
        </div>
      }
    >
      <DashboardLayout
        brandName="CityVigil"
        logo={<Shield className="h-5 w-5 text-sky-400" aria-hidden />}
        userName="Heat Operations"
        userEmail="ops@cityvigil.local"
      >
        <CityVigilDashboard />
      </DashboardLayout>
    </Suspense>
  )
}
