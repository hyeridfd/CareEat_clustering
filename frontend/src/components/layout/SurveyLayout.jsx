export default function SurveyLayout({ title, icon, page, totalPages, onPrev, onNext, onDashboard, nextLabel, children, sidebarItems, onPageJump }) {
  const hasSidebar = sidebarItems && sidebarItems.length > 0

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 헤더 */}
      <header className="bg-white shadow-sm px-4 py-3 flex items-center gap-3 sticky top-0 z-20">
        <button onClick={onDashboard} className="text-gray-400 hover:text-gray-700 text-xl">←</button>
        <div className="flex-1">
          <h1 className="text-base font-bold text-gray-900">{icon} {title}</h1>
          <p className="text-xs text-gray-400">페이지 {page} / {totalPages}</p>
        </div>
      </header>

      {/* 진행 바 */}
      <div className="progress-bar sticky top-[53px] z-10">
        <div className="progress-fill" style={{ width: `${(page / totalPages) * 100}%` }} />
      </div>

      <div className={`flex ${hasSidebar ? 'max-w-5xl' : 'max-w-2xl'} mx-auto`}>

        {/* 사이드바 (기초 조사표 전용) */}
        {hasSidebar && (
          <aside className="hidden md:block w-48 shrink-0 pt-4 pr-3">
            <div className="sticky top-20 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
              <div className="bg-gradient-to-r from-blue-600 to-blue-500 px-3 py-2.5">
                <p className="text-xs font-semibold text-white">페이지 이동</p>
              </div>
              <nav className="p-1.5 space-y-0.5">
                {sidebarItems.map((item) => {
                  const isActive = page === item.page
                  const isDone = item.page < page
                  return (
                    <button
                      key={item.page}
                      type="button"
                      onClick={() => onPageJump && onPageJump(item.page)}
                      className={`w-full text-left px-2.5 py-2 rounded-lg text-xs font-medium transition-all flex items-center gap-2 ${
                        isActive
                          ? 'bg-blue-600 text-white shadow-sm'
                          : isDone
                          ? 'text-green-700 hover:bg-green-50'
                          : 'text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs shrink-0 font-bold ${
                        isActive ? 'bg-white/20 text-white' : isDone ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                      }`}>
                        {isDone ? '✓' : item.page}
                      </span>
                      <span className="leading-tight">{item.label}</span>
                    </button>
                  )
                })}
              </nav>
            </div>
          </aside>
        )}

        {/* 메인 콘텐츠 */}
        <div className="flex-1 min-w-0 p-4">
          {/* 모바일용 가로 탭 (사이드바 있는 경우만) */}
          {hasSidebar && (
            <div className="md:hidden overflow-x-auto mb-3 -mx-1 px-1">
              <div className="flex gap-1.5 pb-1" style={{ width: 'max-content' }}>
                {sidebarItems.map((item) => {
                  const isActive = page === item.page
                  const isDone = item.page < page
                  return (
                    <button
                      key={item.page}
                      type="button"
                      onClick={() => onPageJump && onPageJump(item.page)}
                      className={`px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all border ${
                        isActive
                          ? 'bg-blue-600 text-white border-blue-600'
                          : isDone
                          ? 'bg-green-50 text-green-700 border-green-200'
                          : 'bg-white text-gray-600 border-gray-200'
                      }`}
                    >
                      {isDone ? '✓' : item.page}. {item.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 페이지 내용 */}
          <div className="card mb-4">
            {children}
          </div>

          {/* 네비게이션 */}
          <div className="flex gap-3">
            <button onClick={onDashboard} className="btn-secondary px-4">🏠</button>
            {page > 1 && (
              <button onClick={onPrev} className="btn-secondary flex-1">← 이전</button>
            )}
            <button onClick={onNext} className="btn-primary flex-1">
              {nextLabel || (page < totalPages ? '다음 →' : '✅ 제출')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}