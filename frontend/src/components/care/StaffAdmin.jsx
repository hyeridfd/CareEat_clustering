import { useEffect, useState } from 'react'
import api from '../../lib/api'
import { errMsg } from './CareUI'

// 관리자: 요양원 담당자 계정 발급·관리
export default function StaffAdmin({ nursingHomes = [] }) {
  const [rows, setRows] = useState([])
  const [form, setForm] = useState({ id: '', nursing_home_id: '', name: '', password: '', role: 'staff' })
  const [msg, setMsg] = useState(null)

  const load = () => api.get('/admin/staff').then((r) => setRows(r.data)).catch((e) => setMsg({ kind: 'error', text: errMsg(e) }))
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!form.nursing_home_id && nursingHomes[0]) setForm((f) => ({ ...f, nursing_home_id: nursingHomes[0].id }))
  }, [nursingHomes])

  const create = async (e) => {
    e.preventDefault(); setMsg(null)
    try {
      await api.post('/admin/staff', form)
      setMsg({ kind: 'ok', text: `${form.id} 계정을 만들었습니다. 비밀번호를 담당자에게 안전하게 전달하세요.` })
      setForm({ ...form, id: '', name: '', password: '' })
      load()
    } catch (err) { setMsg({ kind: 'error', text: errMsg(err) }) }
  }
  const toggle = async (s) => { await api.put(`/admin/staff/${s.id}`, { is_active: !s.is_active }); load() }
  const reset = async (s) => {
    const pw = window.prompt(`${s.id} 새 비밀번호 (8자 이상)`)
    if (!pw) return
    try { await api.put(`/admin/staff/${s.id}`, { password: pw }); setMsg({ kind: 'ok', text: '비밀번호를 변경했습니다.' }) }
    catch (err) { setMsg({ kind: 'error', text: errMsg(err) }) }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={create} className="grid md:grid-cols-6 gap-2">
        <select className="form-select md:col-span-2" value={form.nursing_home_id} onChange={(e) => setForm({ ...form, nursing_home_id: e.target.value })}>
          {nursingHomes.map((n) => <option key={n.id} value={n.id}>{n.name} ({n.id})</option>)}
        </select>
        <input className="form-input" placeholder="담당자 ID" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} required />
        <input className="form-input" placeholder="이름" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="form-input" type="password" placeholder="비밀번호 8자+" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        <button className="btn-primary text-sm">계정 발급</button>
      </form>
      {msg && <p className={`text-sm rounded-lg px-3 py-2 ${msg.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-800'}`}>{msg.text}</p>}
      <table className="w-full text-sm">
        <thead><tr className="bg-gray-50 text-xs text-gray-500 text-left"><th className="px-3 py-2">ID</th><th className="px-3 py-2">요양원</th><th className="px-3 py-2">이름</th><th className="px-3 py-2">상태</th><th className="px-3 py-2"></th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-4 text-gray-400">발급된 계정이 없습니다.</td></tr>}
          {rows.map((s) => (
            <tr key={s.id} className="border-t border-gray-100">
              <td className="px-3 py-2 font-medium">{s.id}</td>
              <td className="px-3 py-2">{s.nursing_home_id}</td>
              <td className="px-3 py-2">{s.name}</td>
              <td className="px-3 py-2">{s.is_active ? <span className="badge-complete">사용</span> : <span className="badge-incomplete">중지</span>}</td>
              <td className="px-3 py-2 text-right space-x-3">
                <button onClick={() => reset(s)} className="text-xs text-blue-600">비밀번호 변경</button>
                <button onClick={() => toggle(s)} className="text-xs text-gray-500">{s.is_active ? '중지' : '재사용'}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
