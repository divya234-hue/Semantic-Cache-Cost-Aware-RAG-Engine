import type { LucideIcon } from 'lucide-react'

interface MetricCardProps {
  label: string
  value: string
  description: string
  icon: LucideIcon
}

export function MetricCard({ label, value, description, icon: Icon }: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className="metric-card__top">
        <span className="metric-card__label">{label}</span>
        <span className="metric-card__icon" aria-hidden="true">
          <Icon size={18} />
        </span>
      </div>
      <strong className="metric-card__value">{value}</strong>
      <span className="metric-card__description">{description}</span>
    </article>
  )
}
