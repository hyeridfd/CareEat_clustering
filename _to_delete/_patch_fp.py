# -*- coding: utf-8 -*-
import io
p = 'pages/care/FacilityPage.jsx'
s = io.open(p, encoding='utf-8').read()
assert 'MenuExplorer' not in s, '이미 적용됨'

def rep(old, new, count=1):
    global s
    assert old in s, '앵커 없음: ' + old[:60]
    s = s.replace(old, new, count)

rep("import { errMsg } from '../../components/care/CareUI'",
    "import { errMsg } from '../../components/care/CareUI'\nimport { MenuExplorer, MenuDrawer } from '../../components/care/FoodGraph'")

rep("  { key: 'action', label: '개선안', desc: '다음 주 식단을 어떻게 바꾸나' },",
    "  { key: 'action', label: '개선안', desc: '다음 주 식단을 어떻게 바꾸나' },\n  { key: 'food', label: '식품 DB', desc: '메뉴를 재료·영양으로 뜯어보기' },")

# MenuChip 클릭 → 근거 패널
rep("function MenuChip({ it, delta }) {", "function MenuChip({ it, delta, onOpen }) {")
rep('    <li className="rounded-xl ring-1 ring-navy-100 bg-white px-3.5 py-2.5">',
    '    <li className={`rounded-xl ring-1 ring-navy-100 bg-white px-3.5 py-2.5 ${onOpen ? \'cursor-pointer hover:ring-navy-300 hover:bg-navy-50/40\' : \'\'}`}\n'
    '      onClick={onOpen ? () => onOpen(it.title) : undefined}\n'
    '      onKeyDown={onOpen ? (e) => { if (e.key === \'Enter\') onOpen(it.title) } : undefined}\n'
    '      tabIndex={onOpen ? 0 : undefined} role={onOpen ? \'button\' : undefined}>')

rep("function MenuBlock({ m }) {\n  if (!m) return null",
    "function MenuBlock({ m, onOpen }) {\n  if (!m) return null\n"
    "  const open = onOpen ? (title) => onOpen(title, m.kind === 'boost' ? m.nutrient : 'na') : undefined")
rep("<MenuChip key={c.id} it={c} delta={c.delta} />", "<MenuChip key={c.id} it={c} delta={c.delta} onOpen={open} />")
rep("<MenuChip key={it.id} it={it} />", "<MenuChip key={it.id} it={it} onOpen={open} />")
rep("function ActionCard({ x }) {", "function ActionCard({ x, onOpen }) {")
rep("<MenuBlock m={x.menus} />", "<MenuBlock m={x.menus} onOpen={onOpen} />")

rep("  const [actErr, setActErr] = useState('')",
    "  const [actErr, setActErr] = useState('')\n  const [drawer, setDrawer] = useState(null)   // { name, nutrient }")
rep("<ActionCard key={x.id} x={x} />",
    "<ActionCard key={x.id} x={x} onOpen={(name, nutrient) => setDrawer({ name, nutrient })} />")

# 안내 문구: 메뉴를 누르면 근거
rep("                    {act.plans?.length\n",
    "                    <p className=\"mb-3 text-[11px] text-muted\">후보 메뉴를 누르면 재료 구성과 추천 근거(질환 → 영양소 → 재료)를 그래프로 볼 수 있습니다.</p>\n"
    "                    {act.plans?.length\n")

# 식품 DB 탭 + 패널
rep("""          </>
          )}
        </div>
      )}
    </CareLayout>""",
"""          </>
          )}

          {tab === 'food' && (
            <Section title="식품·메뉴 DB"
              sub={`메뉴를 골라 재료별 분량과 영양 기여, 질환별 권장·금기 근거를 확인합니다.${act?.graph ? ` · 요리 ${act.graph.foods}개 · ${act.graph.source === 'neo4j' ? '실시간 연결' : '스냅샷'}` : ''}`}>
              <MenuExplorer diseases={act?.diseases_applied || []} />
            </Section>
          )}
        </div>
      )}
      <MenuDrawer open={!!drawer} name={drawer?.name} nutrient={drawer?.nutrient}
        diseases={act?.diseases_applied || []} onClose={() => setDrawer(null)} />
    </CareLayout>""")

io.open(p, 'w', encoding='utf-8').write(s)
print('FacilityPage 패치 완료')
