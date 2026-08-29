'use client'

import { Suspense } from 'react'

import { DashboardLayout } from '@/components/dashboard-layout'
import { CityVigilDashboard } from '@/components/cityvigil/CityVigilDashboard'
import { CityVigilLogo, CityVigilWordmark } from '@/components/cityvigil/CityVigilLogo'

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-dashboard">
          <div className="animate-pulse text-slate-500">Loading CityVigil…</div>
        </div>
      }
    >
      <DashboardLayout
        brandName="CityVigil"
        logo={<CityVigilLogo size={36} />}
        userName="Heat Operations"
        userEmail="ops@cityvigil.local"
      >
        <CityVigilDashboard />
      </DashboardLayout>
    </Suspense>
  )
}
