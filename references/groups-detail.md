# 各组详细配置

---

## 大盘组（运行中）

| 配置 | 值 |
|:--|:--|
| 组名 | 大盘组 |
| 负责人 | 示例人员1 |
| 数据源 | AI Table（钉钉多维表） |
| Base ID | `EXAMPLE_BASE_ID` |
| MCP URL | 见 `groups/dapan.json` → `mcp_url` |
| 配置文件 | `groups/dapan.json` |

**推送**

| 推送 | 脚本 | Cron | 时间 |
|:--|:--|:--|:--|
| 填报提醒 | `push_dapan_reminder.py dapan` | `40 17 * * 1-5` | 17:40 |
| 异常推送 | `push_dapan_anomaly.py dapan` | `15 18 * * 1-5` | 18:15 |
| 人效日报 | `push_dapan_daily.py dapan` | `30 10 * * *` | 10:30 |

**机器人**
- 正式群 Webhook: `access_token=YOUR_DINGTALK_ACCESS_TOKEN`
- Secret: `YOUR_DINGTALK_SECRET`

**数据表**
- 人员名单: `EXAMPLE_TABLE_IDS_ROSTER`（在职/离职/转出）
- 日报录入: `EXAMPLE_TABLE_IDS_DAILY`（表单填写）
- 项目表: `EXAMPLE_TABLE_IDS_PROJECT`（启用/停用，含准确率阈值）

**达标规则**: 完成率 ≥ 100%，或豁免（临时工时>0 或 培训工时>0 + 组长标注）
**请假等比放大**: 半天×2，1小时×8/7，2小时×8/6，3小时×8/5
**连续三天未达标通报**

---

## WIKI 组（暂停中，paused=true）

| 配置 | 值 |
|:--|:--|
| 组名 | WIKI组 |
| 负责人 | 示例人员2 |
| 数据源 | 电子表格（Sheet MCP） |
| 数据文档 nodeId | `EXAMPLE_DATA_NODE_ID`（7月，每月换整个文档，sheet名不变） |
| 人员文档 nodeId | `EXAMPLE_PERSONNEL_NODE_ID`（不换，不同组织） |
| 配置文件 | `groups/wiki.json` |

**MCP（两个，不同组织）**
- 数据文档: 见 `groups/wiki.json` → `sheet_mcp_url`
- 人员文档: 见 `groups/wiki.json` → `personnel_sheet_mcp_url`

**推送**（暂停中）
| 推送 | 脚本 | Cron | 时间 |
|:--|:--|:--|:--|
| 人效日报 | `push_wiki_daily.py` | `30 11 * * *` | 11:30 |

**机器人**
- Webhook: `access_token=YOUR_DINGTALK_ACCESS_TOKEN`
- Secret: `YOUR_DINGTALK_SECRET`

**数据表**（sheet名固定，脚本直接用名字访问，不依赖sheetId）
- 绩效表: sheet 名"绩效"
- 量级登记: sheet 名"量级登记"
- 考勤: sheet 名"考勤"（A=工号，B=姓名，C起一天一列）
- 人员: 人员文档 sheet"人员"（sheetId `EXAMPLE_PERSONNEL_SHEET_ID`，不换）

**考勤映射**

| 值 | 推送 | 看板 |
|:--|:--|:--|
| 早4 | 全勤 | 正常 |
| 事假1/年假1/丧假1/病假1 | 休 🏖️ | +1 |
| 事假上/事假下/年假上/年假下/病假上/病假下 | 半天假（阈值750） | +0.5 |
| 含"转项"/"离职" | 不显示 | 不计入 |

**达标规则**: 绩效用作业量之和 ≥ 1500（读 Q 列），半天假阈值=750
**准确率**: 生产和质检分列，质检有不一致量才显示

**名称映射（量级登记 → 绩效表）**
```
示例任务4 → 示例任务3
示例任务8 → 示例任务7
示例任务9 → 示例任务5
款采集 → 示例任务6
示例任务2 → 示例任务1
```

**每月换表**: 更新 `wiki.json` 中的 `data_node_id` 为新文档 nodeId（sheet名不变）

---

## 违规申诉组（运行中）

| 配置 | 值 |
|:--|:--|
| 组名 | 违规申诉组 |
| 负责人 | 示例人员3 |
| 数据源 | 电子表格（Sheet MCP） |
| 数据文档 nodeId | `EXAMPLE_DATA_NODE_ID` |
| 考勤文档 nodeId | `EXAMPLE_ATTENDANCE_NODE_ID`（与商机组共用，商机已停用） |
| 配置文件 | `groups/weigui.json` |

**MCP**: 见 `groups/weigui.json` → `sheet_mcp_url`

**推送**

| 推送 | 脚本 | Cron | 时间 |
|:--|:--|:--|:--|
| 人效日报 | `push_weigui_daily.py` | `0 11 * * *` | 11:00 |

**机器人**
- Webhook: `access_token=YOUR_DINGTALK_ACCESS_TOKEN`
- Secret: `YOUR_DINGTALK_SECRET`

**数据表**
- 绩效: sheet 名 `2026年X月绩效`（脚本按月份自动识别）
- 人员名单: sheetId `EXAMPLE_DATA_SHEET_IDS_人员名单`（D=姓名, E=工号, F=状态，固定不换）
- 考勤: sheet 名 `2026年X月`（按月份自动识别）

**考勤映射**: 同 WIKI 组（事假1/年假1等=全天，事假上/下等=半天，转项/离职=不显示）

**特殊规则**
- 质检和生产标产从绩效表 I/J 列读，不写死
- 答疑按培训逻辑算绩效（1500×工时÷8），类型保持"答疑"
- 总工时 = S列(项目工时) + K列(培训/答疑作业工时)
- 示例人员12（exclude_employees）：看板完全排除，推送只推量级无准确率
- 姓名列使用 LOOKUP 公式
- 有非工作日排班（周末上班看板记录，推送不管）

**人员配置**
人员名单与任职状态由部署方自行配置，本示例不包含真实人员信息。

---

## 商机组（已停用 inactive，2026-07-01 起）

历史数据保留在看板，看板该日期后不显示，推送彻底取消，cron 已删除。

| 配置 | 值 |
|:--|:--|
| 组名 | 商机组 |
| 负责人 | 示例人员3 |
| 数据文档 nodeId | `EXAMPLE_DATA_NODE_ID` |
| 配置文件 | `groups/shangji.json` |

---

## 天猫榜单组（运行中，仅看板，无推送）

| 配置 | 值 |
|:--|:--|
| 组名 | 天猫榜单 |
| 负责人 | 无（数据问题联系 @示例人员4） |
| 数据源 | 电子表格（Sheet MCP） |
| 周月度汇总文档 nodeId | `EXAMPLE_SUMMARY_NODE_ID` |
| 日常排名文档 nodeId | `EXAMPLE_RANKING_NODE_ID` |
| 配置文件 | `groups/tianmao.json` |

**MCP（两个，不同组织）**
- 汇总文档: 见 `groups/tianmao.json` → `sheet_mcp_url`
- 排名文档: 见 `groups/tianmao.json` → `ranking_mcp_url`

**数据表**
- 周度: sheet 名"天猫榜单&底纹&下拉-周度"（混合表，按B列筛选"天猫榜单"）
- 月度: sheet 名"天猫榜单月度"
- 日常数据: sheet 名 `2026.x`（如 `2026.7`）

**特殊规则**
- 只展示在看板，不做任何推送
- 看板只支持周/月度，不支持日（选日期自动归到所属周）
- 项目维度指标直接读表（CPD=K列, 吞吐=E/D×1500, 准确率=P列）
- 个人准确率排名从日常数据表按人聚合

---

## 测试群机器人（全局共用）

- Webhook: `access_token=YOUR_DINGTALK_ACCESS_TOKEN`
- Secret: `YOUR_DINGTALK_SECRET`

---

## 定时任务汇总

| Cron | 任务 | 脚本 |
|:--|:--|:--|
| `40 17 * * 1-5` | 大盘填报提醒 | `push_dapan_reminder.py dapan` |
| `15 18 * * 1-5` | 大盘异常推送 | `push_dapan_anomaly.py dapan` |
| `30 10 * * *` | 大盘人效日报 | `push_dapan_daily.py dapan` |
| `0 11 * * *` | 违规申诉人效日报 | `push_weigui_daily.py` |
| `0 9,11,13,15,17 * * *` | 看板数据更新（全组合并） | `fetch_dapan_data.py && fetch_wiki_data.py && fetch_weigui_data.py && fetch_tianmao_data.py` |

> WIKI 推送暂停，恢复时另建 cron：`30 11 * * *` → `push_wiki_daily.py`

---

## 看板 URL

`https://example.invalid/YOUR_INTERNAL_URL`

---

## 交接必读

新管理员接手流程见 [SKILL.md](../SKILL.md) 的"新管理员引导"部分。

接手人需要：
1. 确保所有 MCP URL 有效（`groups/*.json` 中保存了所有 URL）
2. 如 MCP 失效，去 https://mcp.dingtalk.com/#/detail?mcpId=9555 (AI Table) 或 mcpId=9704 (Sheet) 重新获取
3. 重建 CloudCLI 定时任务（按上表创建，model 用 `claude-sonnet-4-6`）
4. 确认 HTTP 服务器运行看板（`python3 -m http.server 8081`）
5. 用测试群验证各组推送正常
