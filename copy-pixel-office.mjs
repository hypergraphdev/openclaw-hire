import { copyFileSync, mkdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';

const src = '/Users/wuxing/code/OpenClaw-bot-review/lib/pixel-office';
const dst = '/Users/wuxing/code/openclaw-hire/frontend/src/pixel-office';

const files = [
  'colorize.ts', 'floorTiles.ts', 'wallTiles.ts', 'notificationSound.ts',
  'engine/renderer.ts', 'engine/characters.ts', 'engine/officeState.ts', 'engine/matrixEffect.ts',
  'layout/furnitureCatalog.ts', 'layout/layoutSerializer.ts',
  'sprites/spriteData.ts', 'sprites/catSprites.ts', 'sprites/pngLoader.ts', 'sprites/tilesetSprites.ts',
  'bugs/config.ts', 'bugs/bugSystem.ts', 'bugs/pheromoneField.ts', 'bugs/renderer.ts',
  'editor/editorActions.ts', 'editor/editorState.ts',
];

let copied = 0;
for (const f of files) {
  const srcPath = join(src, f);
  const dstPath = join(dst, f);
  if (existsSync(dstPath)) {
    console.log('  SKIP:', f);
    continue;
  }
  mkdirSync(dirname(dstPath), { recursive: true });
  copyFileSync(srcPath, dstPath);
  console.log('  COPY:', f);
  copied++;
}
console.log(`Done: ${copied} files copied`);
