"""
WIKI组人效日报推送
每日 11:00 触发，推送前一个工作日的量级达标 + 准确率
用法: python3 push_wiki_daily.py [--test]
"""
import sys, json, datetime, math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))

from scripts.dingtalk_doc import setup as mcp_setup
from scripts.dingtalk_sheet import get_range
from common import load_group, send_dingtalk, is_workday, find_prev_workday, TEST_WEBHOOK, TEST_SECRET

EXCEL_EPOCH = datetime.datetime(1899, 12, 30)


def serial_to_date(v):
    if v is None or v == "":
        return None
    try:
        return (EXCEL_EPOCH + datetime.timedelta(days=int(float(v)))).strftime("%Y-%m-%d")
    except:
        return None


def load_personnel_active(group, date_str):
    """返回指定日期在职的工号集合"""
    node_id = group["personnel_node_id"]
    sheet_id = group["personnel_sheet_id"]
    result = get_range(node_id, sheet_id=sheet_id, range="A1:G60")
    vals = result.get("values") or result.get("data", {}).get("values", [])
    active = {}
    for row in vals[1:]:
        if not row[0]:
            continue
        emp_id = str(row[0]).strip()
        name = str(row[1]).strip()
        # Remove zero-width spaces and other invisible chars
        name = ''.join(c for c in name if c.isprintable() and ord(c) > 31 and not (0x200B <= ord(c) <= 0x200F))
        name = name.strip()
        status = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        leave_date_raw = row[6] if len(row) > 6 else None
        leave_date = serial_to_date(leave_date_raw)
        if name == group.get("leader", ""):
            continue
        if status == "在职" or (leave_date and leave_date > date_str):
            active[emp_id] = name
    return active


def load_perf_for_date(group, date_str):
    """读取指定日期的绩效表数据，按人汇总。sheet名固定，直接用名字访问（每月换文档，ID会变）"""
    node_id = group["data_node_id"]
    sheet_id = "绩效"

    r1 = get_range(node_id, sheet_id=sheet_id, range="D2:L2200")
    part1 = r1.get("values") or r1.get("data", {}).get("values", [])
    r2 = get_range(node_id, sheet_id=sheet_id, range="N2:U2200")
    part2 = r2.get("values") or r2.get("data", {}).get("values", [])

    excluded = set(group.get("exclude_from_metrics", []))
    person_records = {}  # {name: {perf_total, projects: {proj: {qc, diff}}}}

    def safe_float(v):
        try:
            return float(v) if v else 0
        except:
            return 0

    for i, r in enumerate(part1):
        d = serial_to_date(r[0] if r else None)
        if d != date_str:
            continue
        r2r = part2[i] if i < len(part2) else []
        name = str(r[2] or "").strip() if len(r) > 2 else ""
        name = ''.join(c for c in name if c.isprintable() and ord(c) > 31 and not (0x200B <= ord(c) <= 0x200F))
        task_group = str(r[6] or "").strip() if len(r) > 6 else ""
        task_type = str(r[7] or "").strip() if len(r) > 7 else ""
        threshold = safe_float(r[8] if len(r) > 8 else 0)
        hours = safe_float(r2r[0] if r2r else 0)
        qty = safe_float(r2r[1] if len(r2r) > 1 else 0)
        qc = safe_float(r2r[6] if len(r2r) > 6 else 0)
        diff_raw = r2r[7] if len(r2r) > 7 else None
        diff_is_empty = diff_raw is None or str(diff_raw).strip() == ""
        diff = safe_float(diff_raw)

        if not name:
            continue

        if name not in person_records:
            person_records[name] = {"perf_total": 0, "projects": {}}

        # 直接读表里已算好的绩效用作业量（Q列，r2r[3]），四舍五入取整
        perf_score_raw = safe_float(r2r[3] if len(r2r) > 3 else 0)
        score = round(perf_score_raw) if perf_score_raw > 0 else 0

        person_records[name]["perf_total"] += score

        # 准确率 — 只收集生产和质检且不在exclude列表的
        if task_group in excluded:
            continue
        if task_type not in ("生产", "质检"):
            continue
        if task_type == "生产" and qc > 0:
            key = f"{task_group}|{task_type}"
            if key not in person_records[name]["projects"]:
                person_records[name]["projects"][key] = {
                    "qc": 0, "diff": 0,
                    "label": f"{task_group[:6]}(生产)准确率",
                    "acc_threshold": safe_float(r2r[5] if len(r2r)>5 else 0) or 0.95,
                }
            person_records[name]["projects"][key]["qc"] += qc
            person_records[name]["projects"][key]["diff"] += diff
        elif task_type == "质检" and qc > 0 and not diff_is_empty:
            # 情况1：被抽检量和不一致量都有值 → 显示质检准确率
            key = f"{task_group}|{task_type}"
            if key not in person_records[name]["projects"]:
                person_records[name]["projects"][key] = {
                    "qc": 0, "diff": 0,
                    "label": f"{task_group[:6]}(质检)准确率",
                    "acc_threshold": safe_float(r2r[5] if len(r2r)>5 else 0) or 0.95,
                }
            person_records[name]["projects"][key]["qc"] += qc
            person_records[name]["projects"][key]["diff"] += diff
        # 情况2：质检 qc>0 但 diff 为空 → 不显示

    return person_records


def build_push_message(group, report_date, person_records, active_employees, full_leave_ids=None, half_leave_ids=None, not_show_ids=None):
    if full_leave_ids is None: full_leave_ids = set()
    if half_leave_ids is None: half_leave_ids = set()
    if not_show_ids is None: not_show_ids = set()

    # 过滤掉转项/离职
    show_employees = {k: v for k, v in active_employees.items() if k not in not_show_ids}
    date_display = report_date[5:].replace("-", "月") + "日"

    # Collect active project keys with QC data
    projects_with_qc = set()
    for name in show_employees.values():
        if name in person_records:
            for key in person_records[name]["projects"]:
                projects_with_qc.add(key)

    proj_acc_thr = {}
    for name in show_employees.values():
        if name in person_records:
            for key, pdata in person_records[name]["projects"].items():
                if key not in proj_acc_thr and "acc_threshold" in pdata:
                    proj_acc_thr[key] = pdata["acc_threshold"]

    active_proj_list = sorted(projects_with_qc)

    # Get label for each project key
    def get_label(key):
        for name in show_employees.values():
            if name in person_records:
                d = person_records[name]["projects"].get(key)
                if d and "label" in d:
                    return d["label"]
        parts = key.split("|")
        return f"{parts[0][:6]}({'生产' if len(parts)>1 and parts[1]=='生产' else '质检'})准确率"

    lines = []
    lines.append(f"@所有人 早上好！我来汇报工作情况啦 ☀️\n")
    lines.append(f"### 📊 {date_display} WIKI组人效日报\n")

    # Table header - use label from project data
    acc_headers = [get_label(k) for k in active_proj_list]
    header = "| 姓名 | 量级 |" + "".join(f" {h} |" for h in acc_headers)
    separator = "|:---:|:---:|" + ":---:|" * len(active_proj_list)
    lines.append(header)
    lines.append(separator)

    all_met = True

    for emp_id, name in sorted(show_employees.items(), key=lambda x: x[1]):
        # 全天假
        if emp_id in full_leave_ids:
            acc_cells = ["—"] * len(active_proj_list)
            if acc_cells:
                lines.append(f"| {name} | 休 🏖️ | {' | '.join(acc_cells)} |")
            else:
                lines.append(f"| {name} | 休 🏖️ |")
            continue

        rec = person_records.get(name, {"perf_total": 0, "projects": {}})
        total = rec["perf_total"]

        # 半天假阈值=750，正常=1500
        threshold = 750 if emp_id in half_leave_ids else 1500

        # 量级
        if total == 0 and not rec["projects"]:
            if emp_id in half_leave_ids:
                qty_str = "半天假"
            else:
                qty_str = "未填报"
                all_met = False
        elif total >= threshold:
            qty_str = "达标 ✅"
        else:
            qty_str = "未达标"
            all_met = False

        # 准确率各项目
        acc_cells = []
        for proj in active_proj_list:
            proj_data = rec["projects"].get(proj)
            if not proj_data or proj_data["qc"] == 0:
                acc_cells.append("—")
            else:
                acc = (1 - proj_data["diff"] / proj_data["qc"]) * 100
                thr = proj_acc_thr.get(proj, 0.95) * 100
                if acc < thr:
                    all_met = False
                    acc_cells.append(f"{acc:.1f}% ❗")
                else:
                    acc_cells.append(f"{acc:.1f}%")

        acc_str = " | ".join(acc_cells)
        if acc_cells:
            lines.append(f"| {name} | {qty_str} | {acc_str} |")
        else:
            lines.append(f"| {name} | {qty_str} |")

    lines.append("\n")
    if all_met:
        lines.append("太棒啦，我们真厉害！全员达标 🎉🎉🎉")
    else:
        lines.append("还有小伙伴没达标哦，加油呀 💪")

    return "\n".join(lines)


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    group = load_group("wiki")

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")

    if group.get("paused"):
        print(f"[{today_str}] WIKI 组已暂停（wiki.json paused=true），跳过推送。")
        sys.exit(0)

    if not is_workday(today_str):
        print(f"[{today_str}] 非工作日，跳过推送")
        sys.exit(0)

    report_date = find_prev_workday(today)
    print(f"今天: {today_str}，汇报日期: {report_date}")

    mcp_setup(group["sheet_mcp_url"])
    if group.get("personnel_sheet_mcp_url"):
        mcp_setup(group["personnel_sheet_mcp_url"])

    print("读取人员名单...")
    active_employees = load_personnel_active(group, report_date)
    print(f"  当日在职: {len(active_employees)} 人")

    print("读取绩效表...")
    person_records = load_perf_for_date(group, report_date)
    print(f"  有记录: {len(person_records)} 人")

    print("读取考勤...")
    EPOCH = datetime.datetime(1899, 12, 30)
    def sd(v):
        try: return (EPOCH + datetime.timedelta(days=int(float(v)))).strftime("%Y-%m-%d")
        except: return None

    node_id = group["data_node_id"]
    try:
        att_result = get_range(node_id, sheet_id="考勤", range="A1:BF60")
        att_vals = att_result.get("values") or att_result.get("data", {}).get("values", [])
    except:
        att_vals = []

    full_leave_ids = set()
    half_leave_ids = set()
    not_show_ids = set()
    if att_vals:
        header = att_vals[0]
        target_col = None
        r_month = int(report_date[5:7])
        r_day = int(report_date[8:10])
        for i, h in enumerate(header):
            if not h or i < 2: continue
            ds = sd(h)
            if ds and int(ds[5:7]) == r_month and int(ds[8:10]) == r_day:
                target_col = i
                break
            import re as _re
            m = _re.match(r'(\d+)\.(\d+)', str(h).strip())
            if m and int(m.group(1)) == r_month and int(m.group(2)) == r_day:
                target_col = i
                break
        if target_col is not None:
            for row in att_vals[1:]:
                if not row[0] or target_col >= len(row): continue
                emp_id = str(row[0] or "").strip()
                val = str(row[target_col] or "").strip()
                if not val or val == "早4": continue
                if "转项" in val or "离职" in val:
                    not_show_ids.add(emp_id)
                elif val in ("事假1", "年假1", "丧假1", "病假1"):
                    full_leave_ids.add(emp_id)
                elif val in ("事假上", "事假下", "年假上", "年假下", "病假上", "病假下"):
                    half_leave_ids.add(emp_id)
    print(f"  全天假: {len(full_leave_ids)} 人, 半天假: {len(half_leave_ids)} 人")

    message = build_push_message(group, report_date, person_records, active_employees, full_leave_ids, half_leave_ids, not_show_ids)

    print("\n推送内容预览：")
    print(message)

    webhook = TEST_WEBHOOK if test_mode else group["webhook_url"]
    secret = TEST_SECRET if test_mode else group["webhook_secret"]

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"WIKI组 {report_date[5:]} 人效日报",
            "text": message,
        },
        "at": {"isAtAll": True},
    }

    result = send_dingtalk(webhook, secret, payload)
    mode = "测试群" if test_mode else "正式群"
    print(f"\n推送结果({mode}): {result}")
