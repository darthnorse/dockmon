import { Cpu, MemoryStick, Network } from 'lucide-react'
import { ResponsiveMiniChart } from './ResponsiveMiniChart'

interface StatsChartsProps {
  cpu: (number | null)[]
  mem: (number | null)[]
  net: (number | null)[]
  timestamps: number[]
  timeWindow: number
  cpuValue?: string | undefined
  memValue?: string | undefined
  netValue?: string | undefined
  footer?: string | undefined
}

const CHART_HEIGHT = 120

const CHARTS = [
  { key: 'cpu', label: 'CPU Usage', color: 'cpu', Icon: Cpu, iconClass: 'text-amber-500' },
  { key: 'mem', label: 'Memory Usage', color: 'memory', Icon: MemoryStick, iconClass: 'text-green-500' },
  { key: 'net', label: 'Network I/O', color: 'network', Icon: Network, iconClass: 'text-orange-500' },
] as const

export function StatsCharts({
  cpu, mem, net, timestamps, timeWindow,
  cpuValue, memValue, netValue, footer,
}: StatsChartsProps) {
  const dataMap = { cpu, mem, net } as const
  const valueMap = { cpu: cpuValue, mem: memValue, net: netValue } as const

  return (
    <>
      {CHARTS.map(({ key, label, color, Icon, iconClass }) => {
        const data = dataMap[key]
        const value = valueMap[key]
        return (
          <div key={key} className="bg-surface-2 rounded-lg p-3 border border-border overflow-hidden">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Icon className={`h-4 w-4 ${iconClass}`} />
                <span className="font-medium text-sm">{label}</span>
              </div>
              {value && <span className="text-xs text-muted-foreground">{value}</span>}
            </div>
            {data.length > 0 ? (
              <div className="w-full" style={{ height: CHART_HEIGHT }}>
                <ResponsiveMiniChart
                  data={data}
                  timestamps={timestamps.length > 0 ? timestamps : undefined}
                  color={color}
                  height={CHART_HEIGHT}
                  showAxes
                  timeWindow={timeWindow}
                />
              </div>
            ) : (
              <div className="flex items-center justify-center text-muted-foreground text-xs" style={{ height: CHART_HEIGHT }}>
                No data available
              </div>
            )}
          </div>
        )
      })}
      {footer && (
        <p className="text-xs text-muted-foreground text-center">{footer}</p>
      )}
    </>
  )
}
