# Wedding Invitation H5 + Self-hosted Analytics

纯原生 H5 婚礼邀请函（8 页竖滑 + 12 种互动）与自研轻量访客埋点系统：Python stdlib 微服务 + SQLite + ip2region 离线归属地 + ECharts 本地看板，零前端框架、零第三方统计服务依赖，数据不出自有服务器。

## 组成

### 1. 邀请函 H5（`site/`）

8 页竖向滑动的婚礼邀请函，纯 HTML/CSS/JS 实现：

| 页面 | 互动 |
|------|------|
| 封面 | 摇铃铛彩蛋（DeviceMotion + 点击）、BGM 开关 |
| 时间地点 | 一键导航 |
| 故事 / 相册 | 竖滑翻页 |
| 拾光相册 | 照片点开浏览 |
| 弹幕 | 横向滚动弹幕 |
| 祝福树 | 留言祝福 |
| 接喜糖 / 拼图 | 小游戏（打开 → 开始 → 提交漏斗） |
| 结尾 | 放天灯、RSVP 回执 |

### 2. 埋点系统（`server/`）

- `track_server.py`：Python 标准库 HTTP 微服务（`127.0.0.1:8899`，systemd 托管）
- SQLite 单文件存储，`events` 表：`ts / sid / event / payload / ip_hash(SHA256+salt) / province / device / ua`
- **隐私边界**：IP 不落明文（仅哈希去重），归属地仅到省级；`TRACK_TOKEN` / `TRACK_IP_SALT` 通过 systemd 环境变量注入，不写入代码
- 归属地查询：ip2region v4 离线 xdb（11MB），纯 Python 源码接入，无外部请求
- nginx 仅一条 `location /wedding-track/` 反代，与主站业务完全隔离

### 3. 数据看板（`report/` + `tools/`）

- `report/wedding-track-report.html`：单文件数据看板（ECharts 已内联，约 1MB，离线双击即可打开）
  - KPI 卡（UV / PV / 互动次数 / 互动率 / 走完全程率）
  - 8 页触达漏斗、24 小时访问分布、访客地域条形图、设备分布、互动事件排行、最近 300 条事件流
- `tools/gen_track_report.py`：看板生成器 —— SSH 拉取服务器 stats + 明细，注入模板生成看板；内置 Node 语法自检与运行时错误显示兜底

## 使用

```bash
cd tools
cp track_config.example.py track_config.py   # 填入 SSH 别名与 stats URL（已被 .gitignore 排除）
python gen_track_report.py                   # 生成 ../wedding-track-report.html
```

## 线上数据快照（截至 2026-09-28）

- 访客 116 UV / 691 PV，覆盖 18 个地区（含荷兰、越南）
- 触达漏斗：封面 → 结尾完成率约 48%
- 互动 761 次：放天灯 341、照片类 313、摇铃铛 48

## License

MIT
