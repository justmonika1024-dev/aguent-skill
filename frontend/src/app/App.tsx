import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { DashboardPage } from '../pages/DashboardPage'
import { EvaluationPage } from '../pages/EvaluationPage'
import { MemeDetailPage } from '../pages/MemeDetailPage'
import { MemesPage } from '../pages/MemesPage'
import { RunDetailPage } from '../pages/RunDetailPage'
import { RunsPage } from '../pages/RunsPage'
import { SettingsPage } from '../pages/SettingsPage'
import { StrategiesPage } from '../pages/StrategiesPage'
import { AppShell } from './AppShell'
import { AppProviders } from './providers'

export function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
            <Route path="runs/:runId/evaluation" element={<EvaluationPage />} />
            <Route path="memes" element={<MemesPage />} />
            <Route path="memes/:memeId" element={<MemeDetailPage />} />
            <Route path="strategies" element={<StrategiesPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProviders>
  )
}
