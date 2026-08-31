import {
  DashboardOutlined,
  DatabaseOutlined,
  HistoryOutlined,
  SettingOutlined,
  SlidersOutlined,
} from '@ant-design/icons'
import { Layout, Menu, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

const items = [
  { key: '/', icon: <DashboardOutlined />, label: '工作台' },
  { key: '/runs', icon: <HistoryOutlined />, label: '运行历史' },
  { key: '/memes', icon: <DatabaseOutlined />, label: '正式梗库' },
  { key: '/strategies', icon: <SlidersOutlined />, label: '策略版本' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
]

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const selected = items.find((item) => item.key !== '/' && location.pathname.startsWith(item.key))?.key ?? '/'
  return (
    <Layout className="app-layout">
      <Layout.Sider width={232} breakpoint="lg" collapsedWidth={0} className="app-sider">
        <div className="brand">
          <div className="brand-mark">凿</div>
          <div>
            <Typography.Title level={4}>凿 agugent</Typography.Title>
            <Typography.Text>中文文案梗工作流</Typography.Text>
          </div>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={items} onClick={({ key }) => navigate(key)} />
      </Layout.Sider>
      <Layout>
        <Layout.Header className="app-header">
          <div>
            <Typography.Text className="eyebrow">AGENT WORKBENCH</Typography.Text>
            <Typography.Title level={3}>状态机控制台</Typography.Title>
          </div>
          <div className="live-chip"><span /> 单任务串行</div>
        </Layout.Header>
        <Layout.Content className="app-content"><Outlet /></Layout.Content>
      </Layout>
    </Layout>
  )
}
