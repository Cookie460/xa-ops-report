"""
人效日报 — 通用版
用法: python3 push_daily_report.py <组名> [--test]
"""
import sys, datetime
from common import (load_group, ensure_mcp, send_dingtalk, is_workday, find_prev_workday,
                    load_active_projects, load_active_employees, load_daily_records,
                    get_cell_name, TEST_WEBHOOK, TEST_SECRET)

if len(sys.argv) < 2:
    print("用法: python3 push_daily_report.py <组名> [--test]")
    sys.exit(1)

group = load_group(sys.argv[1])
test_mode = "--test" in sys.argv

today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")

if not is_workday(today_str):
    print(f"[{today_str}] 非工作日，跳过推送")
    sys.exit(0)

ensure_mcp(group)
fids = group["field_ids"]["daily"]
pfields = group["project_fields"]

report_date = find_prev_workday(today)
print(f"今天: {today_str}，汇报日期: {report_date}")

# 获取前三个工作日（含 report_date）
def get_prev_n_workdays(date_str, n):
    dates = [date_str]
    d = datetime.date.fromisoformat(date_str)
    for _ in range(n - 1):
        result = find_prev_workday(d)
        dates.append(result)
        d = datetime.date.fromisoformat(result)
    return dates

prev3_dates = get_prev_n_workdays(report_date, 3)
print(f"连续检查日期: {prev3_dates}")

projects = load_active_projects(group)
active_project_names = [p for p in projects if p in pfields]
active = load_active_employees(group)
day_filled = load_daily_records(group, report_date)

# 读前三天数据（用于连续不达标检查）
filled_by_date = {report_date: day_filled}
for d in prev3_dates[1:]:
    filled_by_date[d] = load_daily_records(group, d)

print(f"启用项目: {projects}")
print(f"在职员工: {len(active)} 人")
print(f"{report_date} 已填报: {len(day_filled)} 人")

# 逐人计算
rows = []
has_not_met = False
has_low_acc = False

for emp_id, emp_name in sorted(active.items(), key=lambda x: x[1]):
    cells = day_filled.get(emp_id)
    if not cells:
        rows.append((emp_name, "未填报", {p: "—" for p in active_project_names}, ""))
        has_not_met = True
        continue

    leave_name = get_cell_name(cells.get(fids["leave"], {}))
    is_exempt = get_cell_name(cells.get(fids["exempt"], {})) == "豁免"
    temp_hours = float(cells.get(fids["temp_hours"], 0) or 0)
    train_hours = float(cells.get(fids.get("train_hours", ""), 0) or 0)

    # 达标判断
    if leave_name == "全天":
        status_str = "休 🏖️"
    else:
        completion = 0.0
        for proj_name, proj_cfg in projects.items():
            pf = pfields.get(proj_name)
            if not pf or proj_cfg["threshold"] == 0:
                continue
            qty = float(cells.get(pf["qty"], 0) or 0)
            completion += qty / proj_cfg["threshold"]
        # 请假等比放大
        if leave_name == "半天":
            completion *= 2  # 8/(8-4)
        elif leave_name in ("1小时", "2小时", "3小时"):
            hours_off = int(leave_name[0])
            completion *= 8 / (8 - hours_off)
        if completion >= 1.0:
            status_str = "达标 ✅"
        elif (temp_hours > 0 or train_hours > 0) and is_exempt:
            status_str = "达标 ✅"
        else:
            if temp_hours > 0 or train_hours > 0:
                status_str = "未达标"  # 有临时/培训但未豁免
            else:
                status_str = "未达标"
            has_not_met = True

    # 各项目准确率
    proj_acc = {}
    for proj_name in active_project_names:
        pf = pfields.get(proj_name)
        if not pf:
            continue
        if leave_name == "全天":
            proj_acc[proj_name] = "—"
            continue
        qc_count = float(cells.get(pf["qc"], 0) or 0)
        diff_count = float(cells.get(pf["diff"], 0) or 0)
        if qc_count == 0:
            proj_acc[proj_name] = "—"
        else:
            acc = (1 - diff_count / qc_count) * 100
            acc_thr = projects.get(proj_name, {}).get("acc_threshold", 0.95) * 100
            if acc < acc_thr:
                has_low_acc = True
                proj_acc[proj_name] = f"{acc:.1f}% ❗"
            else:
                proj_acc[proj_name] = f"{acc:.1f}%"

    rows.append((emp_name, status_str, proj_acc, leave_name))

# 组装消息
date_display = report_date[5:].replace("-", "月") + "日"
lines = []
lines.append(f"@所有人 早上好！我来汇报工作情况啦 ☀️\n")
lines.append(f"### 📊 {date_display} {group['group_name']}人效日报\n")

acc_headers = [f"{p}准确率" for p in active_project_names]
header = "| 姓名 | 实际作业量 | " + " | ".join(acc_headers) + " |"
separator = "|:---:|:---:|" + ":---:|" * len(acc_headers)
lines.append(header)
lines.append(separator)

for name, status, proj_acc, leave in rows:
    if "休" in status:
        acc_cells = " | ".join(["—"] * len(active_project_names))
        lines.append(f"| {name} | 休 🏖️ | {acc_cells} |")
    else:
        acc_cells = " | ".join(proj_acc.get(p, "—") for p in active_project_names)
        lines.append(f"| {name} | {status} | {acc_cells} |")

lines.append("\n")
if not has_not_met and not has_low_acc:
    lines.append("太棒啦，我们真厉害！全员达标 🎉🎉🎉")
else:
    lines.append("还有小伙伴没达标哦，加油呀 💪")

# 连续三天量级或准确率不达标检查
def check_emp_status_for_date(emp_id, emp_name, date, day_records):
    cells = day_records.get(emp_id)
    if not cells:
        return {"qty_fail": False, "acc_fail": False}
    leave_name = get_cell_name(cells.get(fids["leave"], {}))
    if leave_name == "全天":
        return {"qty_fail": False, "acc_fail": False}  # 请假不算不达标
    is_exempt = get_cell_name(cells.get(fids["exempt"], {})) == "豁免"
    train_hours = float(cells.get(fids.get("train_hours", ""), 0) or 0)
    temp_hours = float(cells.get(fids.get("temp_hours", ""), 0) or 0)

    completion = 0.0
    for proj_name, proj_cfg in projects.items():
        pf = pfields.get(proj_name)
        if not pf or proj_cfg["threshold"] == 0: continue
        qty = float(cells.get(pf["qty"], 0) or 0)
        completion += qty / proj_cfg["threshold"]
    if leave_name == "半天":
        completion *= 2
    elif leave_name in ("1小时", "2小时", "3小时"):
        completion *= 8 / (8 - int(leave_name[0]))

    qty_fail = completion < 1.0 and not is_exempt and not (temp_hours > 0 or train_hours > 0)

    acc_fail = False
    for proj_name in active_project_names:
        pf = pfields.get(proj_name)
        if not pf: continue
        qc = float(cells.get(pf["qc"], 0) or 0)
        diff = float(cells.get(pf["diff"], 0) or 0)
        if qc > 0:
            acc = (1 - diff / qc) * 100
            thr = projects.get(proj_name, {}).get("acc_threshold", 0.95) * 100
            if acc < thr:
                acc_fail = True
    return {"qty_fail": qty_fail, "acc_fail": acc_fail}

alerts = []
for emp_id, emp_name in sorted(active.items(), key=lambda x: x[1]):
    qty_streak = all(check_emp_status_for_date(emp_id, emp_name, d, filled_by_date[d])["qty_fail"] for d in prev3_dates)
    acc_streak = all(check_emp_status_for_date(emp_id, emp_name, d, filled_by_date[d])["acc_fail"] for d in prev3_dates)
    if qty_streak and acc_streak:
        alerts.append(f"⚠️ {emp_name}同学连续三天量级及准确率均未达标，请组长关注")
    elif qty_streak:
        alerts.append(f"⚠️ {emp_name}同学连续三天量级未达标，请组长关注")
    elif acc_streak:
        alerts.append(f"⚠️ {emp_name}同学连续三天准确率未达标，请组长关注")

if alerts:
    lines.append("\n---")
    lines.extend(alerts)

payload = {
    "msgtype": "markdown",
    "markdown": {"title": f"{date_display} 人效日报", "text": "\n".join(lines)},
    "at": {"isAtAll": True},
}

print("\n推送内容预览：")
print("\n".join(lines))

webhook = TEST_WEBHOOK if test_mode else group["webhook_url"]
secret = TEST_SECRET if test_mode else group["webhook_secret"]
result = send_dingtalk(webhook, secret, payload)
mode = "测试群" if test_mode else "正式群"
print(f"\n推送结果({mode}): {result}")
