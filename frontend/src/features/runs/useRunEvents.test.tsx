import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { useRunEvents } from './useRunEvents'

class FakeEventSource {
  static instance?: FakeEventSource
  listeners = new Map<string, EventListener>()
  closed = false
  constructor(public url: string) { FakeEventSource.instance = this }
  addEventListener(name:string, listener:EventListener){this.listeners.set(name,listener)}
  removeEventListener(name:string){this.listeners.delete(name)}
  close(){this.closed=true}
  emit(name:string){this.listeners.get(name)?.(new Event(name))}
}

function Probe(){useRunEvents('r1');return null}

it.each(['node.completed','state.changed','stream.reset'])('invalidates REST snapshots on %s', async eventName=>{
  vi.stubGlobal('EventSource',FakeEventSource)
  const client=new QueryClient();const invalidate=vi.spyOn(client,'invalidateQueries').mockResolvedValue()
  const Wrapper=({children}:PropsWithChildren)=><QueryClientProvider client={client}>{children}</QueryClientProvider>
  const view=render(<Probe/>,{wrapper:Wrapper})
  FakeEventSource.instance?.emit(eventName)
  expect(invalidate).toHaveBeenCalledTimes(4)
  expect(FakeEventSource.instance?.url).toContain('/runs/r1/events')
  view.unmount();expect(FakeEventSource.instance?.closed).toBe(true)
  vi.unstubAllGlobals()
})
