#!/usr/bin/env python3
"""把 trials.json 内嵌进网站模板，生成可直接发布的 index.html。"""
import sys
tpl, data, out = sys.argv[1:4]
html = open(tpl, encoding="utf-8").read()
js = open(data, encoding="utf-8").read().replace("</", "<\\/")
tag = '<script id="trials-data" type="application/json">' + js + "</script>\n"
marker = "\n<script>\n"
assert html.count(marker) == 1, "template marker not found"
open(out, "w", encoding="utf-8").write(html.replace(marker, "\n" + tag + "<script>\n"))
