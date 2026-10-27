#!/usr/bin/env python3
"""把一份或多份 Markdown 转成一个带目录、可点击跳转的 HTML 网页。

日常只改 .md（省 token），需要网页时运行本工具生成，转换在本地完成，不消耗 token。

特点：
  - 多份文档合成一页，顶部有切换按钮；每份文档有可展开的目录
  - 文档里用 tools/md_toc.py 生成的目录和锚点（<a id="sec-3"></a>）会原样可用
  - 文档之间的链接（如 [手册](操作手册.md#sec-3)）自动改成页内跳转
  - 命令块带“复制”按钮；表格和长命令在自己的框里横向滚动；支持手机和深色模式
  - 生成后自动核对：每份 md 的每段文字都必须出现在网页里，否则报错

用法：
  python tools/build_html.py docs/操作手册.md docs/常见疑问.md -o 手册.html --title "离线 AI 文件整理手册"
  python tools/build_html.py 说明.md -o 说明.html                 # 单份文档，标题取文档里的一级标题
  python tools/build_html.py a.md b.md -o out.html --labels "第一篇,第二篇"   # 自定义顶部按钮文字

需要安装：markdown-it-py（见 tools/requirements.txt）。
"""

import argparse
import html
import re
import sys
from pathlib import Path

try:
    from markdown_it import MarkdownIt
except ImportError:
    sys.exit("缺少 markdown-it-py。请先运行：python -m pip install -r tools/requirements.txt")

HERE = Path(__file__).resolve().parent
ANCHOR_HTML = re.compile(r'^\s*<a id="([A-Za-z0-9_-]+)"></a>\s*$')
ID_ATTR = re.compile(r'\bid="([A-Za-z0-9_-]+)"')
TOC_BLOCK = re.compile(r"<!-- toc -->(.*?)<!-- /toc -->", re.S)

md = MarkdownIt("commonmark").enable("table")


def short_label(h1, fallback):
    """顶部按钮文字：取一级标题里“·”之后、“：”“（”之前的部分。"""
    t = (h1 or fallback).split("·")[-1]
    t = re.split(r"[：:（(]", t)[0].strip()
    return t or fallback


def render(doc, docs_by_name, multi):
    """渲染一份文档，返回 (正文 html, 自动目录 [(级别, id, 文字)])。"""
    key = doc["key"]
    ns = (lambda i: f"{key}-{i}") if multi else (lambda i: i)  # 多份文档时给 id 加前缀，避免冲突
    tokens = md.parse(doc["text"])

    # 1) 标题上方单独一行的 <a id="x"></a>：把 x 挪到标题上，去掉那个空段落
    out, pending, i = [], None, 0
    while i < len(tokens):
        t = tokens[i]
        if (t.type == "paragraph_open" and i + 2 < len(tokens)
                and tokens[i + 1].type == "inline" and ANCHOR_HTML.match(tokens[i + 1].content)
                and tokens[i + 3:i + 4] and tokens[i + 3].type == "heading_open"):
            pending = ANCHOR_HTML.match(tokens[i + 1].content).group(1)
            i += 3
            continue
        if t.type == "heading_open" and pending:
            t.attrSet("data-anchor", pending)
            pending = None
        out.append(t)
        i += 1
    tokens = out

    # 2) 给所有标题定 id，收集目录；改写链接和自带的 id
    toc, n = [], 0
    for j, t in enumerate(tokens):
        if t.type == "heading_open":
            n += 1
            hid = ns(t.attrGet("data-anchor") or f"h{n}")
            t.attrs.pop("data-anchor", None)
            t.attrSet("id", hid)
            if t.tag in ("h2", "h3"):
                toc.append((int(t.tag[1]), hid, tokens[j + 1].content))
        elif t.type in ("html_block", "html_inline") and multi:
            t.content = ID_ATTR.sub(lambda m: f'id="{ns(m.group(1))}"', t.content)
        if t.type == "inline" and t.children:
            for c in t.children:
                if c.type == "html_inline" and multi:
                    c.content = ID_ATTR.sub(lambda m: f'id="{ns(m.group(1))}"', c.content)
                if c.type != "link_open":
                    continue
                href = c.attrGet("href") or ""
                if href.startswith(("http://", "https://")):
                    c.attrSet("target", "_blank")
                    c.attrSet("rel", "noopener")
                elif href.startswith("#"):
                    c.attrSet("href", "#" + ns(href[1:]))
                else:
                    path, _, frag = href.partition("#")
                    other = docs_by_name.get(Path(path).name)
                    if other:
                        target = (f"{other['key']}-{frag}" if multi else frag) if frag else other["key"]
                        c.attrSet("href", "#" + target)

    body = md.renderer.render(tokens, md.options, {})
    body = body.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")
    body = re.sub(r"<pre><code([^>]*)>", r'<div class="code"><pre><code\1>', body)
    body = body.replace("</code></pre>", "</code></pre></div>")
    # 文档自带目录（md_toc.py 生成）：套上可折叠的样式
    body, has_toc = TOC_BLOCK.subn(
        r'<details class="toc" open><summary>本篇目录</summary>\1</details>', body, count=1)
    return body, ([] if has_toc else toc)


def auto_toc(entries):
    if len(entries) < 3:
        return ""
    items, open_sub = [], False
    for level, hid, text in entries:
        link = f'<a href="#{hid}">{html.escape(text)}</a>'
        if level == 2:
            if open_sub:
                items.append("</ul></li>")
                open_sub = False
            elif items:
                items.append("</li>")
            items.append(f"<li>{link}")
        else:
            if not open_sub:
                items.append("<ul>")
                open_sub = True
            items.append(f"<li>{link}</li>")
    items.append("</ul></li>" if open_sub else "</li>")
    return f'<details class="toc" open><summary>本篇目录</summary><ul>{"".join(items)}</ul></details>'


def visible_text(s):
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", s)))


def verify(docs, page):
    """逐行核对：每份 md 里看得见的文字都必须出现在网页里。"""
    text, missing, total = visible_text(page), [], 0
    for d in docs:
        in_fence = False
        for line in d["text"].splitlines():
            if re.match(r"^\s*(```|~~~)", line):
                in_fence = not in_fence
                continue
            s = line.strip()
            if not in_fence and (re.fullmatch(r"<[^>]+>(\s*</[^>]+>)?", s) or s.startswith("<!--")):
                continue  # 锚点、注释等纯 HTML 行，本来就不显示
            if not in_fence:
                s = s.replace("**", "")
                s = re.sub(r"^(#+|>|[-*+]|\d+\.)\s*", "", s)
                s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
                s = re.sub(r"<(https?://[^>]+)>", r"\1", s).replace("`", "")
            cells = s.strip("|").split("|") if (s.startswith("|") and not in_fence) else [s]
            for c in cells:
                c = re.sub(r"\s+", "", html.unescape(c))
                if not c or set(c) <= set("-|:"):
                    continue
                total += 1
                if c not in text:
                    missing.append((d["path"], c[:60]))
    return total, missing


def main():
    ap = argparse.ArgumentParser(description="把 Markdown 转成带目录、可跳转的 HTML")
    ap.add_argument("files", nargs="+", help="一份或多份 .md，按顺序排列")
    ap.add_argument("-o", "--out", required=True, help="输出的 .html 文件")
    ap.add_argument("--title", help="网页标题，默认取第一份文档的一级标题")
    ap.add_argument("--subtitle", default="", help="标题下的一句说明")
    ap.add_argument("--tags", default="", help="标题下的小标签，用逗号分隔")
    ap.add_argument("--labels", help="顶部按钮文字，用逗号分隔，个数与文档相同")
    ap.add_argument("--foot", default="", help="页面底部的说明文字")
    ap.add_argument("--fragment", action="store_true",
                    help="只输出页面片段（不含 <!doctype>/<html>），用于发布到 claude.ai Artifact")
    args = ap.parse_args()

    docs = []
    for k, f in enumerate(args.files, 1):
        p = Path(f)
        text = p.read_text(encoding="utf-8-sig")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        docs.append({"key": f"doc{k}", "path": p, "text": text, "h1": m.group(1).strip() if m else ""})
    labels = [x.strip() for x in args.labels.split(",")] if args.labels else None
    if labels and len(labels) != len(docs):
        sys.exit(f"--labels 有 {len(labels)} 项，但文档有 {len(docs)} 份")
    multi = len(docs) > 1
    by_name = {d["path"].name: d for d in docs}

    articles, nav = [], []
    for k, d in enumerate(docs):
        body, toc = render(d, by_name, multi)
        label = labels[k] if labels else short_label(d["h1"], d["path"].stem)
        articles.append(
            f'<article id="{d["key"]}" class="doc">'
            f'<p class="src">来源文件 · <code>{html.escape(d["path"].as_posix())}</code></p>'
            f'{auto_toc(toc)}{body}</article>')
        nav.append(f'<a href="#{d["key"]}">{html.escape(label)}</a>')

    title = args.title or docs[0]["h1"] or docs[0]["path"].stem
    tags = "".join(f"<li>{html.escape(t.strip())}</li>" for t in args.tags.split(",") if t.strip())
    page = (HERE / "html_template.html").read_text(encoding="utf-8")
    page = (page.replace("{{TITLE}}", html.escape(title))
            .replace("{{SUBTITLE}}", f"    <p>{html.escape(args.subtitle)}</p>\n" if args.subtitle else "")
            .replace("{{TAGS}}", f'    <ul class="spec">{tags}</ul>\n' if tags else "")
            .replace("{{NAV_BLOCK}}", '<nav class="switch" aria-label="文档"><div class="wrap">'
                     + "".join(nav) + "</div></nav>" if multi else "")
            .replace("{{FOOT}}", f'    <p class="foot">{html.escape(args.foot)}</p>' if args.foot else "")
            .replace("{{ARTICLES}}", "\n".join(articles)))
    if not args.fragment:
        page = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + page.replace("<style>", "<style>\nbody { margin: 0; }", 1)
                .replace('<header class="mast">', '</head>\n<body>\n<header class="mast">', 1)
                + "\n</body>\n</html>\n")

    total, missing = verify(docs, page)
    if missing:
        for path, c in missing[:20]:
            print(f"  [缺失] {path}: {c}")
        sys.exit(f"核对失败：{len(missing)} 段文字没有出现在网页里，未写出文件。")
    Path(args.out).write_text(page, encoding="utf-8")
    print(f"已生成 {args.out}：{len(docs)} 份文档，核对 {total} 段文字，无遗漏。")


if __name__ == "__main__":
    main()
