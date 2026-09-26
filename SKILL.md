---
name: xa-ops-report
description: >
  运营团队跨组项目追踪与人效管理技能。支持多组接入（当前：大盘组、WIKI组、违规申诉组、天猫榜单组）。
  包含自动化推送和 Web 项目追踪看板。
  当用户提到人效、CPD、吞吐、准确率、达标、填报提醒、异常推送、
  项目追踪、看板、新组接入、大盘组、WIKI组、违规申诉组、天猫榜单 时使用此技能。
version: 3.0.0
x-source: aone-open
metadata:
  author: xa-ops
  dependencies:
    - devix-dingtalk-skill
    - devix-automation-skill
---

# 运营团队 · 跨组项目追踪与人效管理

## 新管理员引导

**当用户说"我是新任管理员"或类似表达时，执行以下引导流程：**

### 第 1 步：获取 MCP 授权

向用户发送以下链接，引导逐个获取（用能访问对应文档的钉钉账号登录）：

| 组 | MCP 类型 | 获取链接 | 需要几个 |
|:--|:--|:--|:--|
| 大盘组 | AI Table | https://mcp.dingtalk.com/#/detail?mcpId=9555 | 1 个 |
| WIKI/违规/天猫 | 电子表格 | https://mcp.dingtalk.com/#/detail?mcpId=9704 | 可能需要多个组织各获取一次 |

用户提供地址后：
1. 调用 `setup(url)` 验证连接
2. 更新 `groups/*.json` 中对应的 `mcp_url` / `sheet_mcp_url` / `ranking_mcp_url`
3. 尝试读取各组数据验证权限

### 第 2 步：重建定时任务

按下方定时任务表，用 CloudCLI 逐条创建（model 用 `claude-sonnet-4-6`）：

| Cron | 任务 | 脚本 |
|:--|:--|:--|
| `40 17 * * 1-5` | 大盘填报提醒 | `push_dapan_reminder.py dapan` |
| `15 18 * * 1-5` | 大盘异常推送 | `push_dapan_anomaly.py dapan` |
| `30 10 * * *` | 大盘人效日报 | `push_dapan_daily.py dapan` |
| `0 11 * * *` | 违规申诉人效日报 | `push_weigui_daily.py` |
| `0 9,11,13,15,17 * * *` | 看板数据更新（全组） | `fetch_dapan_data.py && fetch_wiki_data.py && fetch_weigui_data.py && fetch_tianmao_data.py` |

> WIKI 组推送暂停（paused=true），恢复时另建 cron：`30 11 * * *` → `push_wiki_daily.py`

### 第 3 步：启动看板

```bash
cd xa_ops_report/dashboard && python3 -m http.server 8081
```

通过沙箱端口映射获取公网地址。

### 第 4 步：验证

在测试群验证各组推送：
```
"在测试群跑一下大盘组推送"
"在测试群跑一下违规组推送"
"刷新看板"
```

---

## 概述

本技能管理运营团队各组的自动化人效推送和项目追踪看板。**每组独立配置**，通过 `groups/` 目录下的 JSON 文件管理所有变量。

---

## 测试环境

所有测试统一使用测试群机器人，**严禁用正式群测试**：
- Webhook: `https://oapi.dingtalk.com/robot/send?access_token=YOUR_DINGTALK_ACCESS_TOKEN`
- Secret: `YOUR_DINGTALK_SECRET`

---

## 已接入的组

| 组 | 配置文件 | 数据源 | 状态 |
|:--|:--|:--|:--|
| 大盘组 | `groups/dapan.json` | AI Table（钉钉多维表） | ✅ 运行中 |
| WIKI 组 | `groups/wiki.json` | 电子表格（Sheet） | ⏸️ 暂停（paused） |
| 违规申诉组 | `groups/weigui.json` | 电子表格（Sheet） | ✅ 运行中 |
| 商机组 | `groups/shangji.json` | 电子表格（Sheet） | ❌ 已停用（inactive） |
| 天猫榜单 | `groups/tianmao.json` | 电子表格（Sheet） | ✅ 仅看板 |

---

## 脚本说明

| 脚本 | 用途 |
|:--|:--|
| `push_dapan_reminder.py dapan` | 大盘组 17:40 填报提醒 |
| `push_dapan_anomaly.py dapan` | 大盘组 18:15 异常推送 |
| `push_dapan_daily.py dapan` | 大盘组 10:30 人效日报 |
| `push_wiki_daily.py` | WIKI 组 11:30 人效日报（暂停中） |
| `push_weigui_daily.py` | 违规申诉组 11:00 人效日报 |
| `fetch_dapan_data.py` | 大盘组看板数据更新 |
| `fetch_wiki_data.py` | WIKI 组看板数据更新（暂停中） |
| `fetch_weigui_data.py` | 违规申诉组看板数据更新 |
| `fetch_tianmao_data.py` | 天猫榜单看板数据更新 |

---

## 节假日判断

所有推送统一使用 timor.tech API（type 0/3 = 工作日），API 不可用时降级为周一至周五。

---

## 组状态管理

| 操作 | 方法 |
|:--|:--|
| 暂停某组 | `xxx.json` 加 `"paused": true`，推送和看板 fetch 自动跳过 |
| 停用某组 | `xxx.json` 加 `"inactive": true` + `"inactive_from": "YYYY-MM-DD"`，看板该日期后不显示 |
| 恢复暂停 | `"paused": false`，创建对应 cron |

---

## 参考文档

| 文档 | 内容 |
|:--|:--|
| [calculation-rules.md](references/calculation-rules.md) | 指标计算口径（CPD/吞吐/准确率/达标） |
| [automation-rules.md](references/automation-rules.md) | 推送规则和时序 |
| [table-structure.md](references/table-structure.md) | 各组数据表列定义 |
| [groups-detail.md](references/groups-detail.md) | 各组详细配置（webhook/nodeId/sheetId） |
| [onboarding-checklist.md](references/onboarding-checklist.md) | 新组接入清单 |
| [dashboard-spec.md](references/dashboard-spec.md) | 看板前端规格 |

---

## MCP 授权管理

MCP 授权会不定期过期。过期后自动化报错"跨组织限制"。

**获取链接：**
- AI Table MCP: https://mcp.dingtalk.com/#/detail?mcpId=9555
- 电子表格 MCP: https://mcp.dingtalk.com/#/detail?mcpId=9704

**各组 MCP 配置位置：**

| 组 | JSON 字段 | 说明 |
|:--|:--|:--|
| 大盘组 | `dapan.json → mcp_url` | AI Table |
| WIKI组 | `wiki.json → sheet_mcp_url` + `personnel_sheet_mcp_url` | 数据和人员在不同组织 |
| 违规组 | `weigui.json → sheet_mcp_url` | |
| 天猫榜单 | `tianmao.json → sheet_mcp_url` + `ranking_mcp_url` | 汇总和排名在不同组织 |

**过期处理：** 重新获取地址 → 告诉 agent "更新 MCP，新地址是 xxx" → 自动更新配置

---

## 常见问题

| 现象 | 原因 | 解决 |
|:--|:--|:--|
| 所有自动化都失败 | MCP 过期 或 Token 额度用尽 | 重新获取 MCP / 检查额度 |
| 违规组推送失败 | 考勤未填 或 出现未知词 | 让组长补填，手动重新触发 |
| 看板数据没更新 | cron 未运行 | 手动触发或检查 cron 状态 |
| 推送内容有误 | 绩效表填写错误 | 让组长检查当天数据 |
| WIKI 组不推送 | paused=true | 确认新规则后改 false 并创建 cron |
