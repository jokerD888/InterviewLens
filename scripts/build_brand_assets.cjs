// Export production assets from the selected B monogram. No image-generation
// credentials are needed. Requires sharp (also available in the Codex runtime).
const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require('sharp');

const root = path.resolve(__dirname, '..');
const publicDir = path.join(root, 'web/public');
const brand = path.join(publicDir, 'brand');
const orange = '#DF6845';
const ink = '#211E1A';
const paper = '#F6F1E8';
const svg = (width, height, body) => `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${body}</svg>\n`;

async function main() {
  const master = await fs.readFile(path.join(brand, 'logo.svg'), 'utf8');
  const mark = master.match(/<g id="mark">([\s\S]*?)<\/g>/)[1];
  const symbol = (color, transform = '') => `<g fill="${color}"${transform ? ` transform="${transform}"` : ''}>${mark}</g>`;
  const png = (source, size) => sharp(Buffer.from(source)).resize(size, size).png().toBuffer();
  const write = (relative, contents) => fs.writeFile(path.join(publicDir, relative), contents);

  await write('brand/logo-mono-ink.svg', svg(128, 128, symbol(ink)));
  await write('brand/logo-mono-paper.svg', svg(128, 128, symbol(paper)));
  await write('brand/logo.png', await png(svg(128, 128, symbol(orange)), 1024));
  for (const [theme, color] of [['light', ink], ['dark', paper]]) {
    await write(`brand/wordmark-${theme}.svg`, svg(720, 180,
      symbol(orange, 'translate(12 12) scale(1.2)') +
      `<text x="190" y="121" fill="${color}" font-family="Georgia, 'Times New Roman', serif" font-size="74" font-weight="700" letter-spacing="-3">InterviewLens</text>`));
  }

  const favicon = svg(128, 128, `<rect width="128" height="128" rx="26" fill="${ink}"/>` + symbol(orange, 'translate(8 8) scale(.875)'));
  await write('favicon.svg', favicon);
  await write('favicon-32.png', await png(favicon, 32));
  // A larger safe margin keeps the complete monogram inside a maskable icon.
  const tile = svg(128, 128, `<rect width="128" height="128" fill="${ink}"/>` + symbol(orange, 'translate(22 22) scale(.65625)'));
  for (const [name, size] of [['apple-touch-icon.png', 180], ['brand/icon-192.png', 192], ['brand/icon-512.png', 512]]) {
    await write(name, await png(tile, size));
  }

  // ICO supports PNG frames; include the usual 16/32/48 pixel sizes.
  const sizes = [16, 32, 48];
  const frames = await Promise.all(sizes.map(size => png(favicon, size)));
  const header = Buffer.alloc(6 + 16 * frames.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(frames.length, 4);
  let offset = header.length;
  frames.forEach((frame, i) => {
    const entry = 6 + i * 16;
    header[entry] = sizes[i]; header[entry + 1] = sizes[i];
    header.writeUInt16LE(1, entry + 4); header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(frame.length, entry + 8); header.writeUInt32LE(offset, entry + 12);
    offset += frame.length;
  });
  await write('favicon.ico', Buffer.concat([header, ...frames]));

  const shareCard = svg(1200, 630,
    `<rect width="1200" height="630" fill="${paper}"/>` +
    `<path d="M64 72H1136M64 558H1136" stroke="${ink}" stroke-opacity=".25"/>` +
    symbol(orange, 'translate(88 166) scale(2.1)') +
    `<text x="408" y="295" fill="${ink}" font-family="Georgia, 'Times New Roman', serif" font-size="86" font-weight="700" letter-spacing="-3">InterviewLens</text>` +
    `<text x="414" y="361" fill="${ink}" font-family="'Microsoft YaHei', 'Noto Serif SC', sans-serif" font-size="32">面经档案馆</text>` +
    `<text x="414" y="420" fill="${ink}" font-family="Arial, sans-serif" font-size="17" letter-spacing="2">INTERVIEW EXPERIENCES · SEMANTIC SEARCH</text>`);
  await write('brand/share-card.png', await sharp(Buffer.from(shareCard)).png().toBuffer());
  await write('site.webmanifest', JSON.stringify({
    name: 'InterviewLens — 面经档案馆', short_name: 'InterviewLens', lang: 'zh-CN',
    start_url: '/', scope: '/', display: 'standalone',
    background_color: paper, theme_color: ink,
    icons: [
      { src: '/brand/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/brand/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
    ],
  }, null, 2) + '\n');
  console.log('Exported IL B logo, wordmarks, favicons, app icons, manifest and share card.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
