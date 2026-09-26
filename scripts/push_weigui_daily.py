"""
违规申诉组人效日报推送
用法: python3 push_weigui_daily.py [--test]
"""
import sys, json, datetime, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))

from scripts.dingtalk_doc import setup as mcp_setup
from scripts.dingtalk_sheet import get_range
from common import load_group, send_dingtalk, is_workday, find_prev_workday, TEST_WEBHOOK, TEST_SECRET

EXCEL_EPOCH = datetime.datetime(1899, 12, 30)

def get_sheet_name(pattern, date_str):
    year, month = int(date_str[:4]), int(date_str[5:7])
    return pattern.format(year=year, month=month)

def serial_to_date(v):
    if v is None or v == "": return None
    try: return (EXCEL_EPOCH + datetime.timedelta(days=int(float(v)))).strftime("%Y-%m-%d")
    except: return None

def sf(v):
    try: return float(v) if v is not None and str(v).strip() else 0
    except: return 0


def load_personnel(group):
    node_id = group["data_node_id"]
    sheet_id = group["data_sheet_ids"]["人员名单"]
    result = get_range(node_id, sheet_id=sheet_id, range="A1:F20")
    vals = result.get("values") or result.get("data", {}).get("values", [])
    active = {}
    for row in vals[1:]:
        if not row or len(row) < 5: continue
        name = str(row[3] or "").strip()   # D=姓名
        emp_id = str(row[4] or "").strip() # E=工号
        status = str(row[5] or "").strip() if len(row) > 5 else ""  # F=状态
        if not name or name == group.get("leader", ""): continue
        if status in ("离职", "转项"): continue
        active[name] = emp_id
    return active


def load_attendance_for_date(group, date_str):
    node_id = group["attendance_node_id"]
    sheet_id = get_sheet_name(group["attendance_sheet_name_pattern"], date_str)
    result = get_range(node_id, sheet_id=sheet_id, range="A1:BF50")
    vals = result.get("values") or result.get("data", {}).get("values", [])
    if not vals: return None

    header = vals[0]
    target_col = None
    month = int(date_str[5:7])
    day = int(date_str[8:10])
    for i, h in enumerate(header):
        if not h or i < 3: continue
        m = re.match(r'(\d+)\.(\d+)', str(h).strip())
        if m and int(m.group(1)) == month and int(m.group(2)) == day:
            target_col = i
            break
    if target_col is None: return None

    # 检查该日考勤列是否全空
    checkable = [row for row in vals[1:] if row[0] and target_col < len(row)]
    if checkable and all(not str(row[target_col] or "").strip() for row in checkable):
        return None

    target_names = set(load_personnel(group).keys())
    result = {"full_leave": set(), "half_leave": set(), "hour_leave": {},
              "not_show": set(), "comp_half": set(), "comp_hours": {}}
    for row in vals[1:]:
        if not row[0] or target_col >= len(row): continue
        name = str(row[0]).strip()
        if name not in target_names: continue
        val = str(row[target_col] or "").strip()
        if not val or val == "早4": continue
        if "离职" in val or "转项" in val:
            result["not_show"].add(name)
            continue
        if val in ("休息", "保护性事假", "调休"):
            result["not_show"].add(name)
            continue
        if val == "上班半天离职":
            result["not_show"].add(name)
            continue
        if val == "休（加班）":
            result["not_show"].add(name)
            continue
        if val == "调休半天":
            result["comp_half"].add(name)
            continue
        m = re.search(r'调休(\d+(?:\.\d+)?)\s*(?:小时|h)', val)
        if m:
            result["comp_hours"][name] = float(m.group(1))
            continue
        m2 = re.search(r'请假(\d+(?:\.\d+)?)\s*(?:小时|h)', val)
        if m2:
            result["hour_leave"][name] = float(m2.group(1))
            continue
        if val in ("请假上半天", "请假下半天", "年假半天"):
            result["half_leave"].add(name)
            continue
        if val == "半天年假半天病假":
            result["full_leave"].add(name)
            continue
        if val in ("请假", "年假", "病假"):
            result["full_leave"].add(name)
            continue
        print(f"  ⚠️ 考勤未识别: {name} = \"{val}\"，请确认如何映射后手动重新触发")
        sys.exit(1)
    return result


def load_perf_for_date(group, report_date):
    node_id = group["data_node_id"]
    sheet_id = get_sheet_name(group["perf_sheet_name_pattern"], report_date)
    excluded = set(group.get("exclude_from_metrics", []))

    all_rows = []
    for start in range(2, 10**6, 100):
        r = get_range(node_id, sheet_id=sheet_id, range=f"A{start}:S{start+99}")
        vals = r.get("values") or r.get("data", {}).get("values", [])
        all_rows.extend(vals)
        if len(vals) < 100: break

    person_records = {}
    for row in all_rows:
        if not row or not str(row[0] or "").strip(): continue
        date = serial_to_date(row[0])
        if date != report_date: continue
        name = str(row[2] or "").strip() if len(row) > 2 else ""
        name = ''.join(c for c in name if c.isprintable() and ord(c) > 31 and not (0x200B <= ord(c) <= 0x200F))
        if not name: continue

        tg = str(row[6] or "").strip() if len(row) > 6 else ""
        ty = str(row[7] or "").strip() if len(row) > 7 else ""
        qc = sf(row[16]) if len(row) > 16 else 0
        diff_raw = row[17] if len(row) > 17 else None
        diff_is_empty = diff_raw is None or str(diff_raw).strip() == ""
        diff = sf(diff_raw)
        acc_thr = sf(row[15]) if len(row) > 15 else 0
        perf_score = sf(row[13]) if len(row) > 13 else 0

        if name not in person_records:
            person_records[name] = {"perf_total": 0, "projects": {}}
        person_records[name]["perf_total"] += round(perf_score)

        if tg in excluded: continue
        if name in set(group.get("exclude_employees", [])): continue
        if ty == "生产" and qc > 0:
            key = f"{tg}|生产"
            if key not in person_records[name]["projects"]:
                person_records[name]["projects"][key] = {"qc": 0, "diff": 0, "acc_threshold": acc_thr or 0.95, "label": f"{tg}(生产)准确率"}
            person_records[name]["projects"][key]["qc"] += qc
            person_records[name]["projects"][key]["diff"] += diff
        elif ty == "质检" and qc > 0 and not diff_is_empty:
            key = f"{tg}|质检"
            if key not in person_records[name]["projects"]:
                person_records[name]["projects"][key] = {"qc": 0, "diff": 0, "acc_threshold": acc_thr or 0.95, "label": f"{tg}(质检)准确率"}
            person_records[name]["projects"][key]["qc"] += qc
            person_records[name]["projects"][key]["diff"] += diff

    return person_records


def build_push_message(group, report_date, person_records, active_employees, att):
    not_show = att["not_show"]
    full_leave = att["full_leave"]
    half_leave = att["half_leave"]
    hour_leave = att["hour_leave"]
    comp_half = att["comp_half"]
    comp_hours = att["comp_hours"]

    # Filter out not_show from active
    show_employees = {k: v for k, v in active_employees.items() if k not in not_show}
    date_display = report_date[5:].replace("-", "月") + "日"

    projects_with_qc = set()
    for name in show_employees:
        if name in person_records:
            for key in person_records[name]["projects"]:
                projects_with_qc.add(key)
    active_proj_list = sorted(projects_with_qc)

    def get_label(key):
        for name in show_employees:
            if name in person_records:
                d = person_records[name]["projects"].get(key)
                if d and "label" in d: return d["label"]
        return f"{key[:8]}准确率"

    proj_acc_thr = {}
    for name in show_employees:
        if name in person_records:
            for key, pdata in person_records[name]["projects"].items():
                if key not in proj_acc_thr:
                    proj_acc_thr[key] = pdata.get("acc_threshold", 0.95)

    lines = []
    lines.append(f"@所有人 早上好！我来汇报工作情况啦 ☀️\n")
    lines.append(f"### 📊 {date_display} {group['group_name']}人效日报\n")

    acc_headers = [get_label(k) for k in active_proj_list]
    header = "| 姓名 | 量级 |" + "".join(f" {h} |" for h in acc_headers)
    separator = "|:---:|:---:|" + ":---:|" * len(active_proj_list)
    lines.append(header)
    lines.append(separator)

    all_met = True
    for name in sorted(show_employees.keys()):
        if name in full_leave:
            acc_cells = ["—"] * len(active_proj_list)
            if acc_cells:
                lines.append(f"| {name} | 休 🏖️ | {' | '.join(acc_cells)} |")
            else:
                lines.append(f"| {name} | 休 🏖️ |")
            continue

        rec = person_records.get(name, {"perf_total": 0, "projects": {}})
        total = rec["perf_total"]

        # 达标阈值
        if name in comp_half:
            threshold = 750
        elif name in comp_hours:
            threshold = round(1500 * (8 - comp_hours[name]) / 8)
        else:
            threshold = 1500

        if total == 0 and not rec["projects"]:
            if name in half_leave:
                qty_str = "半天假"
            elif name in hour_leave:
                qty_str = f"{hour_leave[name]}h假"
            else:
                qty_str = "未填报"
                all_met = False
        elif total >= threshold:
            qty_str = "达标 ✅"
        else:
            qty_str = "未达标"
            all_met = False

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

        if acc_cells:
            lines.append(f"| {name} | {qty_str} | {' | '.join(acc_cells)} |")
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
    group = load_group("weigui")

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    if not is_workday(today_str):
        print(f"[{today_str}] 非工作日，跳过推送")
        sys.exit(0)

    report_date = find_prev_workday(today)
    print(f"今天: {today_str}，汇报日期: {report_date}")

    mcp_setup(group["sheet_mcp_url"])

    print("读取人员名单...")
    active_employees = load_personnel(group)
    print(f"  在职: {len(active_employees)} 人")

    print("读取考勤...")
    att = load_attendance_for_date(group, report_date)
    if att is None:
        print(f"  ⚠️ {report_date} 考勤列全空，考勤未填！请提醒示例人员3填写后手动重新触发。")
        sys.exit(1)
    print(f"  全天假: {att['full_leave']}, 半天假: {att['half_leave']}, 不显示: {att['not_show']}")

    print("读取绩效表...")
    person_records = load_perf_for_date(group, report_date)
    print(f"  有记录: {len(person_records)} 人")

    message = build_push_message(group, report_date, person_records, active_employees, att)

    print("\n推送内容预览：")
    print(message)

    webhook = TEST_WEBHOOK if test_mode else group["webhook_url"]
    secret = TEST_SECRET if test_mode else group["webhook_secret"]

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": f"违规申诉组 {report_date[5:]} 人效日报", "text": message},
        "at": {"isAtAll": True},
    }

    result = send_dingtalk(webhook, secret, payload)
    mode = "测试群" if test_mode else "正式群"
    print(f"\n推送结果({mode}): {result}")
