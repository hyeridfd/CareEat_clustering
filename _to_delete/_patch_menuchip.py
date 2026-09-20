# -*- coding: utf-8 -*-
import io
p = 'pages/care/FacilityPage.jsx'
s = io.open(p, encoding='utf-8').read()
assert 'salt_score' in s, '이미 적용됨'

old_start = s.index('function MenuChip({ it }) {')
old_end = s.index('function MenuBlock({ m }) {')
new = r"""function MenuChip({ it, delta }) {
  const metric =
    it.amount != null ? `${it.amount}${it.unit || ''}`
      : it.sodium_mg != null ? `나트륨 ${it.sodium_mg}mg`
        : ''
  const warn = []
  if (it.sodium_underestimated) warn.push(`나트륨 과소 (${it.sodium_underestimated.slice(0, 2).join(' · ')} 자료 없음)`)
  if (it.amount_outlier) warn.push('레시피 분량 확인 필요')
  if (it.broth_missing) warn.push('국물 미등록 — 중량은 건더기뿐')
  return (
    <li className="rounded-xl ring-1 ring-navy-100 bg-white px-3.5 py-2.5">
      <div className="flex items-center gap-1.5">
        {it.meal_cat && <span className="badge bg-navy-50 text-navy-700">{it.meal_cat}</span>}
        <span className="text-sm font-bold text-navy-900 truncate">{it.title}</span>
        {metric && <span className="ml-auto shrink-0 text-[11px] font-bold tabular-nums text-navy-900">{metric}</span>}
      </div>
      <p className="mt-1 text-[11px] tabular-nums text-muted">
        1인분 {it.serving_g}g
        {it.energy_kcal != null && ` · ${it.energy_kcal}kcal`}
        {it.amount != null && it.sodium_mg != null && ` · 나트륨 ${it.sodium_mg}mg`}
      </p>
      {delta && (
        <p className="mt-1 text-[11px] tabular-nums">
          <span className={delta.sodium_mg <= 0 ? 'text-navy-700' : 'text-rose-700'}>
            나트륨 {delta.sodium_mg > 0 ? '+' : ''}{delta.sodium_mg}mg
          </span>
          <span className="mx-1 text-slate-300">|</span>
          <span className={delta.protein_g >= 0 ? 'text-navy-700' : 'text-amber-700'}>
            단백질 {delta.protein_g > 0 ? '+' : ''}{delta.protein_g}g
          </span>
          <span className="mx-1 text-slate-300">|</span>
          <span className="text-muted">{delta.energy_kcal > 0 ? '+' : ''}{delta.energy_kcal}kcal</span>
        </p>
      )}
      {it.key_ingredients?.length > 0 && (
        <p className="mt-1 text-[11px] text-muted truncate">{it.key_ingredients.join(' · ')}</p>
      )}
      {it.salty_ingredients?.length > 0 && (
        <p className="mt-1 text-[11px] text-muted truncate">간이 센 재료 {it.salty_ingredients.join(' · ')}</p>
      )}
      {it.caution_ingredients?.length > 0 && (
        <p className="mt-0.5 text-[11px] text-amber-700 truncate">
          확인 필요: {it.caution_ingredients.slice(0, 3).join(' · ')}
        </p>
      )}
      {warn.map((w, i) => <p key={i} className="mt-0.5 text-[11px] text-rose-700 truncate">※ {w}</p>)}
    </li>
  )
}

"""
s = s[:old_start] + new + s[old_end:]

# 교체 후보에 delta 전달 + 현재 메뉴 값 표시
old = """              {s.note
                ? <p className="mt-1 text-[11px] text-amber-700">{s.note}</p>
                : <ul className="mt-1.5 grid sm:grid-cols-2 gap-1.5">{s.candidates.map((c) => <MenuChip key={c.id} it={c} />)}</ul>}"""
new = """              {s.current_nutrition && (
                <p className="mt-0.5 text-[11px] tabular-nums text-muted">
                  현재 1인분 {s.current_nutrition.serving_g}g · {s.current_nutrition.energy_kcal}kcal ·
                  단백질 {s.current_nutrition.protein_g}g · 나트륨 {s.current_nutrition.sodium_mg}mg
                </p>
              )}
              {s.note
                ? <p className="mt-1 text-[11px] text-amber-700">{s.note}</p>
                : <ul className="mt-1.5 grid sm:grid-cols-2 gap-1.5">{s.candidates.map((c) => <MenuChip key={c.id} it={c} delta={c.delta} />)}</ul>}"""
assert old in s
s = s.replace(old, new)

io.open(p, 'w', encoding='utf-8').write(s)
print('MenuChip 1인분 표시로 교체 완료:', len(s), 'bytes')
