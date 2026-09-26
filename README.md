# xa-ops-report

运营团队跨组项目追踪与人效管理工具，包含钉钉数据采集、自动化日报与静态 Web 看板。当前版本为 `3.0.0`。

## 功能

- 汇总大盘组、WIKI 组、违规申诉组和天猫榜单组的运营数据。
- 按各组口径计算 CPD、吞吐、准确率及达标情况。
- 通过钉钉机器人发送填报提醒、异常提醒和人效日报。
- 将采集结果生成 JavaScript 数据文件，供 Web 看板展示。
- 使用独立 JSON 配置管理各组数据源、字段映射、机器人和任务时间。

## 目录

```text
.
├── SKILL.md                 # 技能说明与运营流程
├── package.json             # 包元数据和分发文件清单
├── groups/                  # 各组配置
├── scripts/                 # Python 数据采集与推送脚本
├── dashboard/               # 静态看板及 Chart.js 依赖
└── references/              # 指标口径、表结构、接入和自动化说明
```

## 环境准备

需要 Python 3、可访问相关钉钉文档的账号，以及 `devix-dingtalk-skill` 提供的 Python 模块。当前代码从以下路径加载此依赖：

```text
~/.claude/skills/devix-dingtalk-skill/
```

该外部依赖未包含在仓库中。自动化调度还需要自行配置调度器；原技能文档使用 `devix-automation-skill` / CloudCLI。`package.json` 用于技能包描述，不提供 npm 应用启动命令。

## 配置

仓库中的机器人 access token、签名 secret、MCP 地址和内部资源 ID 已替换为占位符，不能直接连接生产环境。

1. 在本地配置 `groups/*.json` 中对应的 `mcp_url`、`sheet_mcp_url`、`personnel_sheet_mcp_url` 或 `ranking_mcp_url`。
2. 配置 `webhook_url` 和 `webhook_secret`，核对文档、表格和字段 ID 是否与自己的数据源一致。
3. 若使用测试推送，先配置 `scripts/common.py` 中的 `TEST_WEBHOOK` 与 `TEST_SECRET`。
4. 详细字段和业务口径见 [表结构](references/table-structure.md)、[计算规则](references/calculation-rules.md) 和 [新组接入清单](references/onboarding-checklist.md)。

本项目目前直接读取 JSON 配置及代码中的测试配置，没有内置 `.env` 加载。请勿将填入真实凭据的本地修改提交到 GitHub。

默认配置中 WIKI 组为暂停状态，商机组为停用状态，天猫榜单组仅提供看板数据。调整前请检查各脚本对状态字段的处理。

## 生成看板数据

在仓库根目录执行：

```bash
python3 scripts/fetch_dapan_data.py
python3 scripts/fetch_wiki_data.py
python3 scripts/fetch_weigui_data.py
python3 scripts/fetch_tianmao_data.py
```

数据文件会生成到 `dashboard/`。成功采集需要外部依赖、有效授权和对应表格权限；部分暂停组可能跳过更新。原压缩包不包含业务数据文件，也没有独立商机采集脚本。

启动本地看板：

```bash
python3 -m http.server 8081 --bind 127.0.0.1 --directory dashboard
```

在浏览器打开 <http://127.0.0.1:8081/dashboard.html>。看板会加载各组的 `*_data.js` 文件；尚未生成的文件可能出现加载失败或缺少数据。

## 推送

先使用测试群验证，例如：

```bash
python3 scripts/push_dapan_reminder.py dapan --test
python3 scripts/push_dapan_anomaly.py dapan --test
python3 scripts/push_dapan_daily.py dapan --test
python3 scripts/push_weigui_daily.py --test
python3 scripts/push_wiki_daily.py --test
```

这些命令会实际发送消息。去掉 `--test` 后使用组配置中的机器人；暂停状态、工作日判断及数据情况也可能影响是否发送。调度时间与推送规则见 [自动化规则](references/automation-rules.md)。仅上传或打开此项目不会自动创建定时任务。

## 数据与凭据

- 不提交真实机器人密钥、带授权的 MCP 地址或生成的人员绩效数据。
- `.gitignore` 排除了看板生成数据、Python 缓存、常见环境文件和 macOS 元数据。
- 配置和参考文档为脱敏示例：姓名、工号、任职信息、内部资源 ID、内部链接及部门标识已移除或替换。项目名称、阈值和状态仅用于演示配置方式，部署时需自行核对。

## 验证状态

已检查 Python 文件语法和 JSON 格式。未执行连接钉钉、读取业务数据或发送消息的集成验证。

## 许可

原项目未附带许可证。本仓库未新增开源授权；第三方库遵循各自文件中的许可声明。
