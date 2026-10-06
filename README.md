<p align="center">
  <a href="https://github.com/chinese-poetry/chinese-poetry">
      <img src="https://avatars3.githubusercontent.com/u/30764933?s=200&v=4" alt="chinese-poetry">
  </a>
</p>

<h2 align="center">chinese-poetry: 最全中文诗歌古典文集数据库</h2>

<p align="center">
  <a href="https://travis-ci.com/chinese-poetry/chinese-poetry" rel="nofollow">
    <img height="28px" alt="Build Status" src="https://img.shields.io/travis/chinese-poetry/chinese-poetry?style=for-the-badge" style="max-width:100%;">
  </a>
  <a href="https://github.com/chinese-poetry/chinese-poetry/blob/master/LICENSE">
    <img height="28px" alt="License" src="http://img.shields.io/badge/license-mit-blue.svg?style=for-the-badge" style="max-width:100%;">
  </a>
  <a href="https://github.com/chinese-poetry/chinese-poetry/graphs/contributors">
    <img height="28px" alt="Contributors" src="https://img.shields.io/github/contributors/chinese-poetry/chinese-poetry.svg?style=for-the-badge" style="max-width:100%;">
  </a>
  <a href="https://www.patreon.com/jackeygao" rel="nofollow">
    <img height="28px" alt="Patreon" src="https://img.shields.io/endpoint.svg?url=https%3A%2F%2Fshieldsio-patreon.vercel.app%2Fapi%3Fusername%3Djackeygao%26type%3Dpledges&style=for-the-badge" style="max-width:100%;">
  </a>
</p>


最全的中华古典文集数据库，包含 5.5 万首唐诗、26 万首宋诗、2.1 万首宋词和其他古典文集。诗人包括唐宋两朝近 1.4 万古诗人，和两宋时期 1.5 千古词人。数据来源于互联网。

**为什么要做这个仓库?** 古诗是中华民族乃至全世界的瑰宝，我们应该传承下去，虽然有古典文集，但大多数人并没有拥有这些书籍。从某种意义上来说，这些庞大的文集离我们是有一定距离的。而电子版方便拷贝，所以此开源数据库诞生了。此数据库通过 JSON 格式分发，可以让你很方便的开始你的项目。

古诗采集没有记录过程，因为古诗数据庞大，目标网站有限制，采集过程经常中断超过了一个星期。2017 年新加入全宋词，[全宋词爬取过程及数据分析](https://jackeygao.github.io/r/words/crawl-ci.html)。

## 本 Fork 的数据修正

本仓库 fork 自 [chinese-poetry/chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)。原数据爬取自网络，存在大量乱码、缺字与重复。本 fork 以古籍检索为证据做了系统性修正，**JSON 结构与字段保持不变**，可直接替换使用；每一处改动都记录在 [`fix_progress.json`](fix_progress.json) 中（原文、改后、依据出处）。

### 主要修改

| 类别 | 数量 | 说明与示例 |
|------|------|-----------|
| 御定全唐詩 爬取残渣 | 约 600 处 | 原站把生僻字替换成 `z5`、`eR` 之类的 ASCII 编码。以 全唐诗 对勘并经识典古籍核对，整理出 271 个编码的对照表（[`scripts/yuding_codes.tsv`](scripts/yuding_codes.tsv)）后还原，如 `頭上白接z5` → 頭上白接䍦、`翠微zc葉` → 翠微㔩葉（杜甫《丽人行》） |
| `□` 缺字补全 | 194 处（246 字） | 只补至少 2 种独立古籍一致的；原书同样缺字的保持 `□`。如辛弃疾「峡束□江」→「峡束苍江」、周邦彦「□□唤酒」→「名娃唤酒」 |
| 日文假名 / 注音符号乱码 | 164 处 | 如 `け然` → 翛然、`荼コ` → 荼䕷、`ゐ惶` → 恓惶、`蹴リ` → 蹴踘、`银筝不会ㄐ` → 搊 |
| 私用区（PUA）字符 | 46 处 | 显示为空白或方块的私用区字符，如「圈＋PUA」→ 圈䙡（禅宗语）、「泬＋PUA」→ 泬㵳（天空）、杜牧「分明㩳㩳羽林槍」 |
| 西里尔 / 希腊字母乱码 | 约 20 处 | 如 `风月正и娟` → 婵娟、`七Α开颜` → 七秩、`阁门珠路Λ` → 𦌊 |
| GBK 字节错位 / 制表符乱码 | 6 处 | 如 `忒�山苛樱�` → 忒煞娇劣、`┾却` → 拚却 |
| 诗句、词句漏字 / 衍字 | 约 35 处 | 依常体句长检出、经古籍核对。如苏轼「乃使驥騄隨蹇步」、范成大「忘却天涯漂泊地」、和凝「时时微雨洗~~劫~~风光」 |
| 作者名 | 34 处 | `赵必□` / `赵必��` → 赵必𤩪（四库本《覆瓿集》署名） |

另有 68 处看似字数不齐、或与通行本不同的诗句，经古籍核实为原貌（又一体、早期版本异文），**未作修改**。例如白居易《琵琶引》「枫叶荻花秋**索索**」是《全唐诗》与宋代文献的原文，通行的「秋瑟瑟」出自明清选本。

### 修正原则

- **以古籍为证，不凭印象**：主要依据[识典古籍](https://www.shidianguji.com)中的古籍刻本、抄本的文字，辅以搜韵、古文岛、汉典；找不到可靠依据的标记为 `needs_review`，不作猜测。
- **不以通行本改底本**：课本或选本的写法不等于原文。
- **保留原字形**：只改动出错的字，并沿用本库已有的写法（如 搊 而非类推简化的 𫼝）。

### 对使用者的影响

- [`loader/datas.json`](loader/datas.json) **不再导入 `御定全唐詩/`**：它与 `全唐诗/` 中的唐诗是同一部《全唐诗》的两份数据，同时导入会造成约 1.9 万首重复。数据文件仍保留，供对勘使用。
- 仍有约 350 个文件含待复核项（主要是底本原有的 `□` 缺字，以及古籍中也无法确认的乱码），详见 `fix_progress.json` 中 `corrected` 为 `null` 的条目。

### 工具与参与

- [`scripts/check_structure.py`](scripts/check_structure.py)：全库质检（乱码、缺字、诗句与词牌字数异常），只报告不修改。
- [`scripts/twin_fix.py`](scripts/twin_fix.py)：全唐诗 ↔ 御定全唐詩 对勘还原残渣。
- [`scripts/shidian.py`](scripts/shidian.py)：以识典古籍批量检索为证据，生成审核表，人工确认后写回。
- 参与修正请阅读 [`AGENTS.md`](AGENTS.md)（适用于人工与 AI 贡献者）。

## 高频词分析图

<details open>
  <summary><b>宋词受欢迎的词牌名</b></summary>

<div align="center">
<img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/ci_rhythmic_topK.png" alt="两宋喜欢的词牌名">
</div>
</details>

<details>
  <summary><b>宋词高频词</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/ci_words_topK.png" alt="宋词高频词" style="max-width:100%;">
</details>

<details>
  <summary><b>宋词作者作品榜</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/ci_author_topK.png" alt="宋词作者作品榜" style="max-width:100%;">
</details>

<details>
  <summary><b>唐诗高频词</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/tang_text_topK.png" alt="唐诗高频词" style="max-width:100%;">
</details>

<details>
  <summary><b>唐诗作者作品榜</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/tang_author_topK.png" alt="唐诗作者作品榜" style="max-width:100%;">
</details>

<details>
  <summary><b>宋诗高频词</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/song_text_topK.png" alt="宋诗高频词" style="max-width:100%;">
</details>

<details>
  <summary><b>宋诗作者作品榜</b></summary>
  <img src="https://raw.githubusercontent.com/jackeygao/chinese-poetry/master/images/song_author_topK.png" alt="宋诗作者作品榜" style="max-width:100%;">
</details>

## 数据集

- [唐诗宋诗](./全唐诗)
- [全宋词](./宋词)
- [五代·花间集](./五代诗词/huajianji)
- [五代·南唐二主词](./五代诗词/nantang)
- [论语](./论语)
- [诗经](./诗经)
- [幽梦影](./幽梦影)
- [四书五经](./四书五经)
- [蒙学](./蒙学)
- [纳兰性德诗集](./纳兰性德)
- [御定全唐詩](./御定全唐詩)


## 贡献

本项目目的是借助技术来生成格式化(JSON)数据，让开发者更方便快速的构建诗词类应用程序。身单力薄，欢迎更多人来维护，你可以通过以下方法来参与贡献：

- 直接提交 PR 或者通过 issue 讨论来优化完善此数据库，理论上古诗歌体非宗教类都欢迎加入，部分有争议性的数据需要社区投票讨论决定是否加入。关于诗句的纠错在创建 PR 时请标明出处。更多规范请[参考贡献规范文档](https://github.com/chinese-poetry/chinese-poetry/wiki/%E5%8F%82%E4%B8%8E%E8%B4%A1%E7%8C%AE%E8%A7%84%E8%8C%83)。

- 如果你没有办法直接参与完善的过程，你也可以通过 「[爱发电赞助](https://afdian.net/a/chinese-poetry)」  「[Patreon 周期性赞助](https://www.patreon.com/jackeygao)」 的形式来持续帮助并激励我去优化完善此数据库。如果您不喜欢周期性赞助，你也可以通过「[支付宝](https://github.com/jackeyGao/JackeyGao.github.io/blob/master/static/images/alipay.png)」或者「[微信赞赏码](https://github.com/jackeyGao/JackeyGao.github.io/blob/master/static/images/wechat.jpg)」进行一次性赞助(备注留下邮箱)。

- 如有建议或吐槽，欢迎联系我的邮箱 gaojunqi@outlook.com。

无论通过哪种形式贡献最终都会使之变得更好！

### 赞助者

无

### 贡献者

<p align="center">
<img src="https://opencollective.com/chinese-poetry/contributors.svg?width=890&button=false" alt="Contributors">
</p>

## 案例展示

<details>
  <summary>案例展示</summary>
  
- [中文诗歌主页](https://chinese-poetry.github.io)是一个基于浏览器的诗词网站，包含唐诗三百首、宋词三百首等文集。
- [animalize](https://github.com/animalize) **/** [QuanTangshi](https://github.com/animalize/QuanTangshi)  *离线全唐诗 Android*
- [justdark](https://github.com/justdark) **/** [pytorch-poetry-gen](https://github.com/justdark/pytorch-poetry-gen)  *a char-RNN based on pytorch*
- [Clover27](https://github.com/Clover27) **/** [ancient-Chinese-poem-generator](https://github.com/Clover27/ancient-Chinese-poem-generator)  *Ancient-Chinese-Poem-Generator*
- [chinese-poetry](https://github.com/chinese-poetry) **/** [poetry-calendar](http://chinese-poetry.github.io/poetry-calendar/)  *诗词周历*
- [chenyuntc](https://github.com/chenyuntc) **/** [pytorch-book](https://github.com/chenyuntc/pytorch-book/blob/master/chapter9-神经网络写诗(CharRNN)/) *简体唐诗生成(char-RNN)，可生成藏头诗，自定义诗歌意境，前缀等。*
- [okcy1016](https://github.com/okcy1016) **/** [poetry-desktop](https://github.com/okcy1016/poetry-desktop/) *诗词桌面*
- [huangjianke](https://github.com/huangjianke) **/** [weapp-poem](https://github.com/huangjianke/weapp-poem/) *诗词墨客 小程序版*
- [汉字之美](https://hz.xusenlin.com/) *汉字之美是一个方便查询的诗词网站，简洁干净，方便使用。*
- [PaddlePaddle](https://github.com/PaddlePaddle) **/** [PaddleNLP](https://github.com/PaddlePaddle/PaddleNLP#%E4%BA%A4%E4%BA%92%E5%BC%8Fnotebook%E6%95%99%E7%A8%8B) *基于ERNIE-GEN(Transformer)的深度学习诗词生成，可自行修改逻辑来生成多种诗词风格。*
- [Harold-y](https://github.com/Harold-y) **/** [chinese-poetry-db-web](https://github.com/Harold-y/chinese-poetry-db-web) *基于本仓库的MySQL DB整合 + 诗词Web端展示与检索*
  
</details>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=chinese-poetry/chinese-poetry&type=Date)](https://star-history.com/#chinese-poetry/chinese-poetry&Date)

## License

[MIT](https://github.com/chinese-poetry/chinese-poetry/blob/master/LICENSE) 许可证。
