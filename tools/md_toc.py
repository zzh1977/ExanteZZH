#!/usr/bin/env python3
"""给 Markdown 文档加固定锚点和可点击的目录。

做两件事：
  1. 在每个二级、三级标题上方加一行固定锚点，如 <a id="sec-3"></a>。
     锚点一旦生成就不再变：以后改标题文字、调整顺序，旧链接照样能跳转。
  2. 在 <!-- toc --> 和 <!-- /toc --> 之间生成目录（没有这两行就放在第一个二级标题前）。
     每次运行都按当前标题重新生成目录，增删章节后再跑一次即可。

用法：
  python tools/md_toc.py docs/操作手册.md docs/常见疑问.md      # 更新这些文件
  python tools/md_toc.py docs/*.md --check                       # 只检查，目录过期时返回 1
  python tools/md_toc.py 文档.md --depth 2                        # 目录只列二级标题

只用 Python 标准库，不需要安装任何包。
"""

import argparse
import re
import sys
from pathlib import Path

TOC_START = "<!-- toc -->"
TOC_END = "<!-- /toc -->"
ANCHOR_RE = re.compile(r'^<a id="([A-Za-z0-9_-]+)"></a>\s*$')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def strip_toc(lines):
    """去掉旧目录块，返回 (去掉后的行, 目录原来所在的位置或 None)。"""
    if TOC_START not in [l.strip() for l in lines]:
        return lines, None
    start = [l.strip() for l in lines].index(TOC_START)
    end = next((i for i in range(start, len(lines)) if lines[i].strip() == TOC_END), None)
    if end is None:
        sys.exit(f"找到了 {TOC_START} 但没有配对的 {TOC_END}，请检查文件。")
    after = end + 1
    if after < len(lines) and not lines[after].strip():
        after += 1  # 目录后面那一个空行由本工具生成，一起去掉
    return lines[:start] + lines[after:], start


def process(text, depth, prefix, min_entries):
    lines = text.splitlines()
    lines, toc_pos = strip_toc(lines)

    # 找出所有标题（跳过代码块），记下已有的锚点
    in_fence = False
    heads = []  # (行号, 级别, 标题文字)
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m and 2 <= len(m.group(1)) <= depth:
            heads.append((i, len(m.group(1)), m.group(2)))
    if len(heads) < min_entries:
        return "\n".join(lines) + "\n", 0

    def anchor_above(i):
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        m = ANCHOR_RE.match(lines[j]) if j >= 0 else None
        return m.group(1) if m else None

    used = {m.group(1) for l in lines for m in [ANCHOR_RE.match(l)] if m}
    nums = [int(x.rsplit("-", 1)[1]) for x in used
            if x.startswith(prefix + "-") and x.rsplit("-", 1)[1].isdigit()]
    next_num = max(nums, default=0) + 1

    entries, inserts = [], {}
    for i, level, title in heads:
        aid = anchor_above(i)
        if aid is None:
            aid = f"{prefix}-{next_num}"
            next_num += 1
            inserts[i] = aid
        entries.append((level, LINK_RE.sub(r"\1", title), aid))

    out = []
    for i, line in enumerate(lines):
        if i in inserts:
            out.append(f'<a id="{inserts[i]}"></a>')
        out.append(line)

    # 目录位置：原来的位置；没有就放在第一个二级标题（或它的锚点）前
    if toc_pos is None:
        toc_pos = heads[0][0] + sum(1 for k in inserts if k <= heads[0][0])  # 第一个标题在 out 中的位置
        j = toc_pos - 1
        while j >= 0 and not out[j].strip():
            j -= 1
        if j >= 0 and ANCHOR_RE.match(out[j]):
            toc_pos = j
    else:
        toc_pos += sum(1 for k in inserts if k < toc_pos)
    top = min(e[0] for e in entries)
    toc = [TOC_START, "**目录**", ""]
    toc += [f"{'  ' * (lvl - top)}- [{t}](#{a})" for lvl, t, a in entries]
    toc += [TOC_END, ""]
    if toc_pos > 0 and out[toc_pos - 1].strip():
        toc.insert(0, "")
    out[toc_pos:toc_pos] = toc
    return "\n".join(out).rstrip("\n") + "\n", len(entries)


def main():
    ap = argparse.ArgumentParser(description="给 Markdown 加固定锚点和目录")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--depth", type=int, default=3, choices=[2, 3, 4], help="目录列到几级标题，默认 3")
    ap.add_argument("--prefix", default="sec", help="锚点前缀，默认 sec，生成 sec-1、sec-2 …")
    ap.add_argument("--min", type=int, default=3, dest="min_entries",
                    help="标题少于这个数就不加目录，默认 3")
    ap.add_argument("--check", action="store_true", help="只检查不修改；有文件需要更新时返回 1")
    args = ap.parse_args()

    stale = 0
    for f in args.files:
        p = Path(f)
        old = p.read_text(encoding="utf-8-sig")
        new, n = process(old, args.depth, args.prefix, args.min_entries)
        if new == old:
            print(f"无需更新  {p}")
            continue
        stale += 1
        if args.check:
            print(f"需要更新  {p}")
        else:
            p.write_text(new, encoding="utf-8")
            print(f"已更新    {p}（目录 {n} 项）")
    if args.check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
