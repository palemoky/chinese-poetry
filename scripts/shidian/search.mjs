// 识典古籍（shidianguji.com）批量全文检索，结果逐条追加到 JSON Lines，可中断续跑。
//
//   node scripts/shidian/search.mjs <queries.json> <results.jsonl> [--cdp http://127.0.0.1:9333] [--delay 3000] [--limit N]
//
// 请控制访问频率：默认每次请求间隔 3 秒（另加 0~1.5 秒随机抖动）；长期任务用 --limit 限定每次运行的检索数，分多日完成。
//
// 默认启动无头 Chromium；传 --cdp 时连接一个已打开的浏览器（例如你已登录的独立实例）。
// 使用繁体显示（/zh/search），生僻字以常规字形呈现，不会变成类推简化字（如 搊 不会显示为 𫼝）。
// 出错、超时或页面未渲染出结果的检索不记为完成，重跑时自动重试。
import fs from 'node:fs';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const [qfile, out] = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!qfile || !out) {
  console.error('usage: node search.mjs <queries.json> <results.jsonl> [--cdp URL] [--delay ms] [--limit N]');
  process.exit(2);
}
const delay = Number(opt('--delay', 3000));
const limit = Number(opt('--limit', 0));          // 0 = 不限
const cdp = opt('--cdp');

const queries = JSON.parse(fs.readFileSync(qfile, 'utf8'));
const marker = '生成语料表格并进行分析';     // 结果片段的起点，只保存此后的部分
const done = new Set();
if (fs.existsSync(out)) {
  for (const line of fs.readFileSync(out, 'utf8').split('\n')) {
    if (!line) continue;
    const r = JSON.parse(line);
    if (!r.err && r.text?.includes(marker)) done.add(r.q);   // 未渲染出结果的旧记录重新检索
  }
}
let todo = queries.filter(q => !done.has(q));
const remaining = todo.length;
if (limit > 0) todo = todo.slice(0, limit);
console.log(`${queries.length} queries, ${done.size} already done, ${remaining} remaining, running ${todo.length} now`);

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
    // 只保留结果片段部分（页头的分类、筛选项对分析无用），控制缓存体积
    const at = text.indexOf(marker);
    if (at >= 0) text = text.slice(at).slice(0, 12000);
    else if (/找到 0 条|共找到 0/.test(text)) text = marker + '\n(0 results)';
    else err = 'no result list rendered';   // 限流、验证码或加载过慢：留待重试
  } catch (e) {
    err = String(e).slice(0, 200);
  }
  fs.appendFileSync(out, JSON.stringify({ q, text, err }) + '\n');
  if (++n % 20 === 0) console.log(`${n}/${todo.length}`);
  await new Promise(r => setTimeout(r, delay + Math.random() * 1500));
}
if (!page.isClosed()) await page.close();
await browser.close();      // 对 --cdp 只是断开连接，不会关闭你的浏览器
console.log('finished', n);
