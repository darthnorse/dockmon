/**
 * Toggle Switch Component
 * Reusable toggle for settings
 */

interface ToggleSwitchProps {
  id: string
  label: string
  description?: string
  checked: boolean
  onChange: (checked: boolean) => void
}

export function ToggleSwitch({ id, label, description, checked, onChange }: ToggleSwitchProps) {
  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between">
        <div className="flex-1 mr-4">
          <label htmlFor={id} className="text-sm font-medium cursor-pointer">
            {label}
          </label>
          {description && (
            <p className="text-sm text-muted-foreground mt-1">{description}</p>
          )}
        </div>

        <button
          type="button"
          role="switch"
          aria-checked={checked}
          id={id}
          onClick={() => onChange(!checked)}
          className={`
            relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent
            transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2
            ${checked ? 'bg-accent' : 'bg-border'}
          `}
        >
          <span
            className={`
              pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0
              transition duration-200 ease-in-out
              ${checked ? 'translate-x-5' : 'translate-x-0'}
            `}
          />
        </button>
      </div>
    </div>
  )
}
