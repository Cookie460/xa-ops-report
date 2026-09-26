"""
异常推送 — 通用版
用法: python3 push_anomaly.py <组名> [--test]
"""
import sys, datetime
from common import (load_group, ensure_mcp, send_dingtalk, is_workday,
                    load_active_projects, load_active_employees, load_daily_records,
                    get_cell_name, TEST_WEBHOOK, TEST_SECRET)

if len(sys.argv) < 2:
    print("用法: python3 push_anomaly.py <组名> [--test]")
    sys.exit(1)

group = load_group(sys.argv[1])
test_mode = "--test" in sys.argv
TODAY = datetime.date.today().strftime("%Y-%m-%d")

if not is_workday(TODAY):
    print(f"[{TODAY}] 非工作日，跳过推送")
    sys.exit(0)

ensure_mcp(group)
fids = group["field_ids"]["daily"]
pfields = group["project_fields"]

projects = load_active_projects(group)
active = load_active_employees(group)
today_filled = load_daily_records(group, TODAY)

print(f"启用项目: {projects}")
print(f"在职员工: {len(active)} 人")
print(f"今日已填报: {len(today_filled)} 人")

# 未填报
not_filled = [name for eid, name in active.items() if eid not in today_filled]

# 需豁免确认
need_exempt = []
for emp_id, cells in today_filled.items():
    leave_name = get_cell_name(cells.get(fids["leave"], {}))
    if leave_name == "全天":
        continue

    completion = 0.0
    details = []
    for proj_name, proj_cfg in projects.items():
        pf = pfields.get(proj_name)
        if not pf or proj_cfg["threshold"] == 0:
            continue
        qty = float(cells.get(pf["qty"], 0) or 0)
        completion += qty / proj_cfg["threshold"]
        if qty > 0:
            details.append(f"{proj_name} {int(qty)}")

    if leave_name == "半天":
        completion *= 2
    elif leave_name in ("1小时", "2小时", "3小时"):
        hours_off = int(leave_name[0])
        completion *= 8 / (8 - hours_off)

    has_temp = group.get("has_temp_tasks", False)
    temp = float(cells.get(fids.get("temp_qty", ""), 0) or 0) if has_temp else 0
    train_h = float(cells.get(fids.get("train_hours", ""), 0) or 0)
    is_exempt = get_cell_name(cells.get(fids["exempt"], {})) == "豁免"

    if completion < 1.0 and not is_exempt:
        name = active.get(emp_id, cells.get(fids["emp_name"], emp_id))
        pct = f"{completion*100:.0f}%"
        if temp > 0:
            need_exempt.append(f"{name}（{' + '.join(details)} = {pct} + 临时 {int(temp)}）")
        elif train_h > 0:
            need_exempt.append(f"{name}（{' + '.join(details)} = {pct} + 培训 {train_h}h）")

# 组装消息
lines = [f"⚠️ 今日填报情况（{TODAY}）\n"]
if not_filled:
    lines.append(f"未填报 **{len(not_filled)} 人**：{'、'.join(not_filled)}\n")
if need_exempt:
    lines.append(f"量不足有临时/培训任务，请组长确认是否豁免：{'、'.join(need_exempt)}\n")
if not not_filled and not need_exempt:
    lines.append("全员已填报，无异常！\n")
lines.append("**请组长进多维表标注豁免或补填请假**")

payload = {
    "msgtype": "markdown",
    "markdown": {"title": f"今日填报情况 {TODAY}", "text": "\n".join(lines)},
    "at": {"isAtAll": False},
}

print("\n推送内容预览：")
print("\n".join(lines))

webhook = TEST_WEBHOOK if test_mode else group["webhook_url"]
secret = TEST_SECRET if test_mode else group["webhook_secret"]
result = send_dingtalk(webhook, secret, payload)
mode = "测试群" if test_mode else "正式群"
print(f"\n推送结果({mode}): {result}")
