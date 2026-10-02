import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path: string) => readFileSync(resolve(root, path), 'utf8');

test('Deskfront keeps the extracted module boundaries present', () => {
  const modules = [
    'docs/deskfront-module-map.md',
    'src/viewer/http.ts',
    'src/viewer/config-routes.ts',
    'src/viewer/match-routes.ts',
    'src/viewer/static-routes.ts',
    'src/viewer/deskfront-routes.ts',
    'src/viewer/page-templates.ts',
    'src/viewer/theme.ts',
    'src/viewer/template-types.ts',
    'src/viewer/home-page.ts',
    'src/viewer/replay-page.ts',
    'src/viewer/game-page.ts',
    'src/viewer/runtime-page.ts',
    'src/deskfront/human_squad_context.py',
    'src/deskfront/human_squad_model.py',
    'src/deskfront/human_squad_orders.py',
    'src/deskfront/human_squad_receipts.py',
    'src/deskfront/human_squad_snapshot.py',
    'src/deskfront/world/stage_contract.py',
    'src/deskfront/world/stage_pipeline.py',
    'src/deskfront/world/growth_visual.gd',
    'src/deskfront/world/growth_staging.gd',
    'src/deskfront/world/growth_mission.gd',
    'src/deskfront/world/growth_retirement.gd',
    'src/deskfront/world/growth_local_ai.gd',
    'src/deskfront/world/stage_source.py',
    'src/deskfront/world/stage_overlay.py',
    'src/deskfront/world/stage_squads.py',
    'src/deskfront/world/stage_unit.py',
    'src/deskfront/world/stage_combat.py',
    'src/deskfront/world/stage_world.py',
    'src/deskfront/tactics_policy.py',
    'src/deskfront/tactics_payload.py',
    'src/deskfront/tactics_coordination.py',
    'src/deskfront/tactics_controller.py',
    'src/deskfront/world/director_contract.py',
    'src/deskfront/world/macro_bridge.py',
  ];
  for (const module of modules) assert.equal(existsSync(resolve(root, module)), true, module);
});

test('compatibility facades delegate to extracted responsibilities', () => {
  const server = read('src/viewer/server.ts');
  assert.match(server, /handleConfigRoute/);
  assert.match(server, /handleMatchRoute/);
  assert.match(server, /handleStaticRoute/);
  assert.match(server, /createDeskfrontOverlayRoutes/);
  assert.match(read('src/viewer/page-templates.ts'), /home-page/);
  assert.match(read('src/viewer/page-templates.ts'), /game-page/);

  const squad = read('src/deskfront/human_squad.py');
  for (const module of ['human_squad_context', 'human_squad_model', 'human_squad_orders', 'human_squad_receipts', 'human_squad_snapshot']) {
    assert.match(squad, new RegExp(module));
  }

  const stage = read('src/deskfront/world/stage.py');
  assert.match(stage, /stage_pipeline/);
  const growth = read('src/deskfront/world/growth.gd');
  assert.match(growth, /GrowthVisual/);
  assert.match(growth, /GrowthStaging/);

  const tactics = read('src/deskfront/tactics.py');
  assert.match(tactics, /tactics_policy/);
  assert.match(tactics, /tactics_payload/);
  const director = read('src/deskfront/world/director.py');
  assert.match(director, /director_contract/);
  assert.match(director, /macro_bridge/);
  const stagePipeline = read('src/deskfront/world/stage_pipeline.py');
  for (const module of ['stage_source', 'stage_overlay', 'stage_squads', 'stage_unit', 'stage_combat', 'stage_world']) {
    assert.match(stagePipeline, new RegExp(module));
  }
});
