# InterviewLens 品牌资源

采用用户选定的 B 款：衬线 IL 字母组合，圆形透镜留白。保留原方案轮廓，用 SVG 路径重绘为正式资产；图标没有字体依赖，也没有不透明的纸色底，网页深浅色均使用暖橙色。

原始方案由内置 image_gen 工具生成，提示方向为：`logo-brand; bespoke IL monogram with circular negative-space lens; terracotta #DF6845, charcoal #211E1A and ivory #F6F1E8; editorial serif; compact favicon; no gradients, shadows or 3D`。正式版本没有重新调用模型修改方案，SVG 是唯一图形源。

| 文件 | 用途 |
| --- | --- |
| [logo.svg](../web/public/brand/logo.svg) | 透明底主图标；网站页头与页脚 |
| [logo.png](../web/public/brand/logo.png) | 1024×1024 透明底 PNG，供其他平台使用 |
| [logo-mono-ink.svg](../web/public/brand/logo-mono-ink.svg) / [logo-mono-paper.svg](../web/public/brand/logo-mono-paper.svg) | 深墨 / 浅纸单色图标 |
| [wordmark-light.svg](../web/public/brand/wordmark-light.svg) / [wordmark-dark.svg](../web/public/brand/wordmark-dark.svg) | GitHub README 的浅色 / 深色组合标识 |
| [favicon.svg](../web/public/favicon.svg) / [favicon.ico](../web/public/favicon.ico) | 标签页与传统浏览器图标，ICO 含 16/32/48px |
| [apple-touch-icon.png](../web/public/apple-touch-icon.png) | 180px Apple 主屏幕图标 |
| [icon-192.png](../web/public/brand/icon-192.png) / [icon-512.png](../web/public/brand/icon-512.png) | 网页 manifest 图标；512px 含 maskable 安全留白 |
| [share-card.png](../web/public/brand/share-card.png) | 1200×630 网站 Open Graph / Twitter 分享图，也可用于 GitHub 仓库 Social preview |

README 用 `<picture>` 自动选择文字的深浅色；网站文字继承现有主题。浏览器图标与主屏幕图标采用深墨底，避免操作系统主题切换造成辨识度下降。Manifest 声明图标和启动入口，不表示支持离线缓存。

SVG 是真实路径；组合标识的英文名称使用系统衬线字体。导出脚本位于 [scripts/build_brand_assets.cjs](../scripts/build_brand_assets.cjs)，使用 Node.js 与 `sharp` 从同一 SVG 生成 PNG、ICO、组合标识、分享图及 manifest。在可解析 `sharp` 的 Node 环境运行：

```powershell
node scripts/build_brand_assets.cjs
```

GitHub 仓库没有独立的项目头像字段；README 标识属于项目本身，个人账号头像不随本项目修改。GitHub 的 Social preview 为单独的仓库设置，可上传上述分享图；网站分享元数据已经引用它。
