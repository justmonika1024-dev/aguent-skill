import asyncio
import sys
from httpx import ASGITransport, AsyncClient
from app.main import app

async def one(c, mode, seed=None):
    r = await c.post('/api/v1/runs', json={'mode': mode, 'admission_mode': 'HUMAN', 'seed_text': seed, 'continuous_enabled': False})
    rid = r.json()['run_id']; print('CREATE', mode, rid, flush=True)
    while True:
        s = (await c.get(f'/api/v1/runs/{rid}')).json()
        if s['state'] in ('WAITING_HUMAN_EVALUATION', 'FAILED', 'WAITING_HUMAN_INTERVENTION'): break
        await asyncio.sleep(.05)
    print('GATE', mode, s['state'], s['current_node'], flush=True)
    if s['state'] != 'WAITING_HUMAN_EVALUATION': return False
    await c.post(f'/api/v1/runs/{rid}/evaluation', json={'expected_run_version': s['run_version'], 'branch_id': s['active_branch_id'], 'processing_chain': {'score': 5}, 'candidate_set': {'score': 5}, 'final_result': {'score': 5}, 'admission_decision': 'ADMIT'})
    while True:
        s = (await c.get(f'/api/v1/runs/{rid}')).json()
        if s['state'] in ('COMPLETED', 'FAILED', 'WAITING_HUMAN_INTERVENTION'): break
        await asyncio.sleep(.05)
    nodes = await c.get(f'/api/v1/runs/{rid}/nodes')
    node_items = nodes.json()
    selected = {item['node_key']: item['output'] for item in node_items if item['node_key'] in ('N12', 'N14', 'N15', 'N20')}
    print('END', mode, s['state'], s['current_node'], 'nodes', len(node_items), 'final_artifacts', selected, flush=True)
    return s['state'] == 'COMPLETED' and len(node_items) == 21

async def main():
    modes = sys.argv[1:] or ['MANUAL_SEED', 'AUTO_DISCOVERY']
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        results = []
        for mode in modes:
            seed = '你说的对，但是原神是一款开放世界冒险游戏' if mode == 'MANUAL_SEED' else None
            results.append(await one(c, mode, seed))
        print('RESULT', *results, flush=True)
        raise SystemExit(0 if all(results) else 1)

if __name__ == '__main__': asyncio.run(main())
