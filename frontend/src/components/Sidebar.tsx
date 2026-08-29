import {
  BarChart3,
  Beaker,
  Database,
  FlaskConical,
  HelpCircle,
  Play,
  Tags,
} from 'lucide-react'

const items = [
  { label: 'Корпусы', icon: Database },
  { label: 'Разметка', icon: Tags },
  { label: 'Измерения', icon: BarChart3 },
  { label: 'Гипотезы', icon: FlaskConical },
  { label: 'Запуски', icon: Play },
]

type SidebarProps = {
  active: string
  onChange: (value: string) => void
}

export function Sidebar({ active, onChange }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Основная навигация">
      <div className="brand">
        <Beaker aria-hidden="true" />
        <span>Prometheus</span>
      </div>
      <nav>
        {items.map(({ label, icon: Icon }) => (
          <button
            aria-label={label}
            className={active === label ? 'nav-item active' : 'nav-item'}
            key={label}
            onClick={() => onChange(label)}
            type="button"
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <button className="nav-item" type="button">
          <HelpCircle aria-hidden="true" />
          <span>Справка</span>
        </button>
      </div>
    </aside>
  )
}
