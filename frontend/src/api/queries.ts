export const queryKeys = {
  currentRun: ['runs', 'current'] as const,
  runs: ['runs'] as const,
  run: (runId: string) => ['runs', runId] as const,
  runRecord: (runId: string) => ['runs', runId, 'record'] as const,
  runUsage: (runId: string) => ['runs', runId, 'usage'] as const,
  memes: ['memes'] as const,
  meme: (memeId: string) => ['memes', memeId] as const,
  usage: ['usage'] as const,
  config: ['system', 'config'] as const,
  runtimeParameters: ['system', 'runtime-parameters'] as const,
  strategies: ['strategies'] as const,
}
