import { Routes, Route, Navigate } from 'react-router-dom'
import ScrollToTop from './lib/ScrollToTop'
import useAuthStore from './lib/authStore'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import AdminPage from './pages/AdminPage'
import BasicSurveyPage from './pages/surveys/BasicSurveyPage'
import NutritionSurveyPage from './pages/surveys/NutritionSurveyPage'
import SatisfactionSurveyPage from './pages/surveys/SatisfactionSurveyPage'
import BluefoodSurveyPage from './pages/surveys/BluefoodSurveyPage'
import StaffLoginPage from './pages/care/StaffLoginPage'
import CarePage from './pages/care/CarePage'
import ResidentCarePage from './pages/care/ResidentCarePage'
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
      <Route path="/login" element={<LoginPage />} />
      <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
      <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
      <Route path="/survey/basic" element={<PrivateRoute><BasicSurveyPage /></PrivateRoute>} />
      <Route path="/survey/nutrition" element={<PrivateRoute><NutritionSurveyPage /></PrivateRoute>} />
      <Route path="/survey/satisfaction" element={<PrivateRoute><SatisfactionSurveyPage /></PrivateRoute>} />
      <Route path="/survey/bluefood" element={<PrivateRoute><BluefoodSurveyPage /></PrivateRoute>} />
      <Route path="/staff-login" element={<StaffLoginPage />} />
      <Route path="/care" element={<StaffRoute><CarePage /></StaffRoute>} />
      <Route path="/care/:elderlyId" element={<StaffRoute><ResidentCarePage /></StaffRoute>} />
      <Route path="/report/:token" element={<GuardianReportPage />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
    </>
  )
}