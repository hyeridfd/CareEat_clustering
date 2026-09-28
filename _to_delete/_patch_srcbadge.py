# -*- coding: utf-8 -*-
import io
p = 'pages/care/FacilityPage.jsx'
s = io.open(p, encoding='utf-8').read()
assert "act.graph.source" not in s, '이미 적용됨'

old = """                      <span className={`badge ${act.graph ? 'bg-navy-50 text-navy-700' : 'bg-slate-100 text-slate-500'}`}>
                        식품 DB {act.graph ? `요리 ${act.graph.foods}개` : '미연결'}
                      </span>"""
new = """                      <span className={`badge ${act.graph ? 'bg-navy-50 text-navy-700' : 'bg-slate-100 text-slate-500'}`}>
                        식품 DB {act.graph ? `요리 ${act.graph.foods}개` : '미연결'}
                      </span>
                      {act.graph && (
                        <span className={`badge ${act.graph.source === 'neo4j' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-900'}`}
                          title={act.graph.source === 'neo4j'
                            ? `Neo4j에서 직접 읽음${act.graph.age_sec != null ? ` · ${Math.round(act.graph.age_sec / 60)}분 전 갱신` : ''}`
                            : act.graph.note || '저장된 스냅샷으로 동작 중입니다'}>
                          {act.graph.source === 'neo4j' ? '실시간 연결' : '스냅샷'}
                        </span>
                      )}"""
assert old in s
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(s)
print('출처 배지 추가 완료')
