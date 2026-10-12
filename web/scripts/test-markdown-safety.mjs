import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import { summaryPlugins } from "../src/lib/summary-markdown.mjs";
const html = renderToStaticMarkup(React.createElement(Markdown,
  {rehypePlugins: summaryPlugins},
  '### 网络 <sub>×2题 / 1篇面经</sub>\n<iframe srcdoc="<script>alert(1)</script>"></iframe>\n<img src="x" onerror="alert(1)">\n<a href="javascript:alert(1)">link</a>'));
assert(!html.includes("iframe"));
assert(!html.includes("onerror"));
assert(!html.includes("javascript:"));
assert(html.includes("<sub>×2题 / 1篇面经</sub>"));
console.log("Markdown safety and count rendering passed");
