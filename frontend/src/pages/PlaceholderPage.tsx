import { Empty } from 'antd'

export function PlaceholderPage({ description }: { description: string }) {
  return <div className="surface"><Empty description={description} /></div>
}
