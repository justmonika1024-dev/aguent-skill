import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { PropsWithChildren } from 'react'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 3_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: 0 },
  },
})

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{ token: { colorPrimary: '#5b6cff', borderRadius: 10, colorBgLayout: '#f3f5f9' } }}
    >
      <QueryClientProvider client={queryClient}>
        <AntApp>{children}</AntApp>
      </QueryClientProvider>
    </ConfigProvider>
  )
}
