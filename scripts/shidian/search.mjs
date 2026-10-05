// 识典古籍（shidianguji.com）批量全文检索，结果逐条追加到 JSON Lines，可中断续跑。
//
//   node scripts/shidian/search.mjs <queries.json> <results.jsonl> [--cdp http://127.0.0.1:9333] [--delay 1200]
//
// 默认启动无头 Chromium；传 --cdp 时连接一个已打开的浏览器（例如你已登录的独立实例）。
// 使用繁体显示（/zh/search），生僻字以常规字形呈现，不会变成类推简化字（如 搊 不会显示为 𫼝）。
// 出错或超时的检索不记为完成，重跑时自动重试。
import fs from 'node:fs';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const [qfile, out] = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!qfile || !out) {
  console.error('usage: node search.mjs <queries.json> <results.jsonl> [--cdp URL] [--delay ms]');
  process.exit(2);
}
const delay = Number(opt('--delay', 1200));
const cdp = opt('--cdp');

const queries = JSON.parse(fs.readFileSync(qfile, 'utf8'));
const done = new Set();
if (fs.existsSync(out)) {
  for (const line of fs.readFileSync(out, 'utf8').split('\n')) {
    if (!line) continue;
    const r = JSON.parse(line);
    if (!r.err && r.text) done.add(r.q);
  }
}
const todo = queries.filter(q => !done.has(q));
console.log(`${queries.length} queries, ${done.size} already done, ${todo.length} to go`);

const browser = cdp ? await chromium.connectOverCDP(cdp) : await chromium.launch();
const context = cdp ? browser.contexts()[0] : await browser.newContext({ locale: 'zh-CN' });
let page = await context.newPage();
let n = 0;
for (const q of todo) {
  let text = '', err = null;
  try {
    if (page.isClosed()) page = await context.newPage();
    await page.goto('https://www.shidianguji.com/zh/search/' + encodeURIComponent(q),
                    { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(() => /共找到 \d|找到|Found \d/.test(document.body.innerText), null,
                               { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(800);
    text = await page.evaluate(() => document.body.innerText);
  } catch (e) {
    err = String(e).slice(0, 200);
  }
  fs.appendFileSync(out, JSON.stringify({ q, text, err }) + '\n');
  if (++n % 20 === 0) console.log(`${n}/${todo.length}`);
  await new Promise(r => setTimeout(r, delay));
}
if (!page.isClosed()) await page.close();
await browser.close();      // 对 --cdp 只是断开连接，不会关闭你的浏览器
console.log('finished', n);
