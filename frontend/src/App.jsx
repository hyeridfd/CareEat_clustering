import { Navigate, Route, Routes } from 'react-router-dom'
import ScrollToTop from './lib/ScrollToTop'
import useAuthStore from './lib/authStore'
import LandingPage from './pages/LandingPage'
import SignupPage from './pages/SignupPage'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import AdminPage from './pages/AdminPage'
import BasicSurveyPage from './pages/surveys/BasicSurveyPage'
import NutritionSurveyPage from './pages/surveys/NutritionSurveyPage'
import SatisfactionSurveyPage from './pages/surveys/SatisfactionSurveyPage'
import BluefoodSurveyPage from './pages/surveys/BluefoodSurveyPage'
import StaffLoginPage from './pages/care/StaffLoginPage'
import CarePage from './pages/care/CarePage'
import RecordsPage from './pages/care/RecordsPage'
import SolutionsPage from './pages/care/SolutionsPage'
import CommunicationPage from './pages/care/CommunicationPage'
import SettingsPage from './pages/care/SettingsPage'
import ResidentCarePage from './pages/care/ResidentCarePage'
import ResidentReportPage from './pages/care/ResidentReportPage'
import GuardianReportPage from './pages/care/GuardianReportPage'

function PrivateRoute({ children }) {
  const token = useAuthStore((s) => s.token)
  return token ? children : <Navigate to="/login" replace />
}

function AdminRoute({ children }) {
  const { token, isAdmin } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/dashboard" replace />
  return children
}

function StaffRoute({ children }) {
  const { token, user } = useAuthStore()
  if (!token || user?.role !== 'staff') return <Navigate to="/staff-login" replace />
  return children
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        {/* 공개 */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/report/:token" element={<GuardianReportPage />} />

        {/* 조사원 설문 */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
        <Route path="/survey/basic" element={<PrivateRoute><BasicSurveyPage /></PrivateRoute>} />
        <Route path="/survey/nutrition" element={<PrivateRoute><NutritionSurveyPage /></PrivateRoute>} />
        <Route path="/survey/satisfaction" element={<PrivateRoute><SatisfactionSurveyPage /></PrivateRoute>} />
        <Route path="/survey/bluefood" element={<PrivateRoute><BluefoodSurveyPage /></PrivateRoute>} />

        {/* 요양시설 담당자 */}
        <Route path="/staff-login" element={<StaffLoginPage />} />
        <Route path="/care" element={<StaffRoute><CarePage /></StaffRoute>} />
        <Route path="/care/records" element={<StaffRoute><RecordsPage /></StaffRoute>} />
        <Route path="/care/solutions" element={<StaffRoute><SolutionsPage /></StaffRoute>} />
        <Route path="/care/connect" element={<StaffRoute><CommunicationPage /></StaffRoute>} />
        <Route path="/care/settings" element={<StaffRoute><SettingsPage /></StaffRoute>} />
        <Route path="/care/residents/:elderlyId" element={<StaffRoute><ResidentCarePage /></StaffRoute>} />
        <Route path="/care/residents/:elderlyId/report" element={<StaffRoute><ResidentReportPage /></StaffRoute>} />

        {/* 운영 관리자 */}
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
