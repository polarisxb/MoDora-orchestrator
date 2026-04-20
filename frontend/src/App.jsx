import { Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from '@/components/ui/Toast'
import { TopNav } from '@/components/TopNav'
import { Footer } from '@/components/Footer'
import { Chat } from '@/pages/Chat'
import { Dashboard } from '@/pages/Dashboard'
import { DocEdit } from '@/pages/DocEdit'
import { Extract } from '@/pages/Extract'
import { TableFill } from '@/pages/TableFill'
import { Library } from '@/pages/Library'
import { Workspace } from '@/pages/Workspace'

export default function App() {
  return (
    <ToastProvider>
      <div className="relative z-10 min-h-screen flex flex-col">
        <TopNav />
        <main className="flex-1 scroll-thin">
          <Routes>
            <Route path="/" element={<Navigate to="/workspace" replace />} />
            <Route path="/workspace" element={<Workspace />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/doc-edit" element={<DocEdit />} />
            <Route path="/extract" element={<Extract />} />
            <Route path="/table-fill" element={<TableFill />} />
            <Route path="/library" element={<Library />} />
          </Routes>
        </main>
        <Footer />
      </div>
    </ToastProvider>
  )
}
