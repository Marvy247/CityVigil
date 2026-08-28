'use client'

import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts'
import { Card } from '@/components/ui/card'
import { getSupply, type SupplyResponse } from '@/lib/cityvigil'

const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
const DANGER_HOUR = 19

function hourLabel(h: number): string {
  if (h === 12) return '12pm'
  if (h === 0) return '12am'
  if (h < 12) return `${h}am`
  return `${h - 12}pm`
}

interface ChartDataPoint {
  hour: number
  label: string
  count: number
  isDanger: boolean
}

export function SupplyChart() {
  const [data, setData] = useState<ChartDataPoint[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const res = await getSupply()
        if (!mounted) return
        const points: ChartDataPoint[] = HOURS.map((h) => ({
          hour: h,
          label: hourLabel(h),
          count: res.open_by_hour[String(h)] ?? 0,
          isDanger: h >= DANGER_HOUR,
        }))
        setData(points)
        setError(null)
      } catch {
        if (!mounted) return
        setError('Supply data unavailable — run python3 scripts/fetch_data.py')
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  if (error) {
    return (
      <Card className="border-amber-200 bg-amber-50 p-4">
        <p className="text-xs text-amber-800">{error}</p>
      </Card>
    )
  }

  const peakOpen = data?.find((d) => d.hour === 15)?.count ?? 0
  const at19 = data?.find((d) => d.hour === 19)?.count ?? 0
  const at20 = data?.find((d) => d.hour === 20)?.count ?? 0

  const chartData = data ?? HOURS.map((h) => ({
    hour: h,
    label: hourLabel(h),
    count: 0,
    isDanger: h >= DANGER_HOUR,
  }))

  const maxCount = Math.max(...chartData.map((d) => d.count), 1)

  return (
    <Card className="border-slate-200 bg-white shadow-sm p-4">
      <h2 className="text-sm font-semibold text-slate-900 mb-1">
        When is cooling actually available? (Wednesday)
      </h2>
      <p className="text-xs text-slate-500 mb-4">
        Provision peaks at 15:00 and collapses through the evening — exactly when it is
        still dangerously hot outside.
      </p>

      <div className="h-[220px] relative">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 10, right: 60, left: 10, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              type="number"
              domain={[0, Math.max(maxCount * 1.15, maxCount + 10)]}
              tick={false}
              axisLine={false}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={50}
              tick={{ fontSize: 11, fill: '#64748b' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
              }}
              labelFormatter={(_, payload) => {
                const entry = payload[0]?.payload as ChartDataPoint | undefined
                return entry ? `${hourLabel(entry.hour)}` : ''
              }}
              formatter={(value: unknown) =>
                typeof value === 'number' ? [`${value} sites open`, ''] : ['', '']
              }
            />
            <ReferenceLine
              y={DANGER_HOUR}
              stroke="#d97706"
              strokeDasharray="5 5"
              strokeWidth={2}
              label={{
                value: '7pm — still above 100°F',
                position: 'top',
                fill: '#d97706',
                fontSize: 10,
                fontWeight: 600,
                offset: -4,
              }}
            />
            <Bar
              dataKey="count"
              radius={[0, 4, 4, 0]}
              maxBarSize={24}
              barSize={20}
            >
              {chartData.map((entry, index) => (
                <Cell key={index} fill={entry.isDanger ? '#f97316' : '#0ea5e9'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>

        <div className="absolute bottom-0 left-0 right-0 px-2 pb-1">
          <p className="text-[10px] text-slate-500 text-center">
            {peakOpen} at peak → {at19} by 7pm → {at20} by 8pm
          </p>
        </div>
      </div>
    </Card>
  )
}

export function SupplyChartSkeleton() {
  return (
    <Card className="border-slate-200 bg-white shadow-sm p-4">
      <div className="h-5 w-1/3 bg-slate-200 animate-pulse rounded mb-1" />
      <div className="h-4 w-1/2 bg-slate-200 animate-pulse rounded mb-4" />
      <div className="h-[220px]">
        <div className="flex items-end justify-between h-full gap-1 px-2">
          {HOURS.map((h) => (
            <div
              key={h}
              className="flex-1 max-w-[32px] bg-slate-200 animate-pulse rounded-t"
              style={{ height: '50%' }}
            />
          ))}
        </div>
      </div>
    </Card>
  )
}