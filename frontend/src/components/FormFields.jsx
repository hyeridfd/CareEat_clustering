// 공통 폼 컴포넌트 모음

export function RadioGroup({ label, options, value, onChange, horizontal = false }) {
  return (
    <div className="mb-4">
      <label className="question-label">{label}</label>
      <div className={`flex ${horizontal ? 'flex-wrap gap-4' : 'flex-col gap-2'}`}>
        {options.map((opt) => {
          const val = typeof opt === 'object' ? opt.value : opt
          const lbl = typeof opt === 'object' ? opt.label : opt
          return (
            <label key={val} className="radio-option text-sm">
              <input
                type="radio"
                name={label}
                value={val}
                checked={value === val}
                onChange={() => onChange(val)}
                className="accent-blue-600"
              />
              {lbl}
            </label>
          )
        })}
      </div>
    </div>
  )
}

export function SelectField({ label, options, value, onChange }) {
  return (
    <div className="mb-4">
      <label className="question-label">{label}</label>
      <select className="form-select" value={value || ''} onChange={e => onChange(e.target.value)}>
        <option value="">선택해주세요</option>
        {options.map(opt => {
          const val = typeof opt === 'object' ? opt.value : opt
          const lbl = typeof opt === 'object' ? opt.label : opt
          return <option key={val} value={val}>{lbl}</option>
        })}
      </select>
    </div>
  )
}

export function NumberField({ label, value, onChange, min = 0, max, step = 1, unit = '' }) {
  return (
    <div className="mb-4">
      <label className="question-label">{label}{unit && <span className="text-gray-400 ml-1">({unit})</span>}</label>
      <input
        type="number"
        className="form-input"
        value={value ?? ''}
        min={min}
        max={max}
        step={step}
        onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </div>
  )
}

export function CheckboxGroup({ label, options, value = [], onChange, etcValue = '', onEtcChange }) {
  const toggle = (opt) => {
    const next = value.includes(opt)
      ? value.filter(v => v !== opt)
      : [...value, opt]
    onChange(next)
  }
  const hasEtc = options.includes('기타')
  const etcChecked = value.includes('기타')

  return (
    <div className="mb-4">
      {label && <label className="question-label">{label}</label>}
      <div className="grid grid-cols-2 gap-2">
        {options.map(opt => (
          <label key={opt} className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={value.includes(opt)}
              onChange={() => toggle(opt)}
              className="accent-blue-600 w-4 h-4"
            />
            {opt}
          </label>
        ))}
      </div>
      {/* 기타 직접 입력 */}
      {hasEtc && etcChecked && onEtcChange && (
        <div className="mt-2">
          <input
            type="text"
            className="form-input text-sm"
            placeholder="기타 내용을 직접 입력해주세요"
            value={etcValue || ''}
            onChange={e => onEtcChange(e.target.value)}
          />
        </div>
      )}
    </div>
  )
}

export function ScaleRating({ label, min = 1, max = 5, value, onChange, labels = [] }) {
  return (
    <div className="mb-4">
      <label className="question-label">{label}</label>
      <div className="flex gap-2 flex-wrap">
        {Array.from({ length: max - min + 1 }, (_, i) => i + min).map(n => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`w-10 h-10 rounded-full text-sm font-medium border-2 transition-colors
              ${value === n
                ? 'bg-blue-600 border-blue-600 text-white'
                : 'bg-white border-gray-300 text-gray-600 hover:border-blue-400'
              }`}
          >
            {n}
          </button>
        ))}
      </div>
      {labels.length > 0 && (
        <div className="flex justify-between text-xs text-gray-400 mt-1 px-1">
          <span>{labels[0]}</span>
          <span>{labels[labels.length - 1]}</span>
        </div>
      )}
    </div>
  )
}

export function InfoBox({ children, type = 'info' }) {
  const colors = {
    info: 'bg-blue-50 border-blue-200 text-blue-800',
    success: 'bg-green-50 border-green-200 text-green-800',
    warning: 'bg-yellow-50 border-yellow-200 text-yellow-800',
  }
  return (
    <div className={`border rounded-lg p-3 text-sm mb-4 ${colors[type]}`}>
      {children}
    </div>
  )
}

export function Divider({ label }) {
  return (
    <div className="flex items-center gap-3 my-5">
      <div className="flex-1 border-t border-gray-200" />
      {label && <span className="text-xs text-gray-400 whitespace-nowrap">{label}</span>}
      <div className="flex-1 border-t border-gray-200" />
    </div>
  )
}