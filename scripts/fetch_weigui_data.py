"""
违规申诉组看板数据抓取
绩效表 → 产量、标产、项目工时、质检准确率
考勤表 → 请假（含半天）
"""
import sys, json, datetime, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))

from scripts.dingtalk_doc import setup as mcp_setup
from scripts.dingtalk_sheet import get_range
from common import load_group

EXCEL_EPOCH = datetime.datetime(1899, 12, 30)

def serial_to_date(serial):
    if serial is None or serial == "": return None
    try: return (EXCEL_EPOCH + datetime.timedelta(days=int(float(serial)))).strftime("%Y-%m-%d")
    except: return None

def sf(v):
    try: return float(v) if v is not None and str(v).strip() else 0
    except: return 0


def load_personnel(group):
    """读违规组人员名单，返回 {name: emp_id}（仅在职）"""
    node_id = group["data_node_id"]
    sheet_id = group["data_sheet_ids"]["人员名单"]
    result = get_range(node_id, sheet_id=sheet_id, range="A1:F20")
    vals = result.get("values") or result.get("data", {}).get("values", [])
    active = {}
    for row in vals[1:]:
        if not row or len(row) < 5: continue
        name = str(row[3] or "").strip()
        emp_id = str(row[4] or "").strip()
        status = str(row[5] or "").strip() if len(row) > 5 else ""
        if not name or name == group.get("leader", ""): continue
        if status in ("离职", "转项"): continue
        active[name] = emp_id
    return active


def get_sheet_name(pattern, date_str):
    year, month = int(date_str[:4]), int(date_str[5:7])
    return pattern.format(year=year, month=month)


def load_attendance(group):
    """读当月+上月考勤 sheet"""
    node_id = group["attendance_node_id"]
    today = datetime.date.today()
    prev_month = (today.replace(day=1) - datetime.timedelta(days=1))
    months_to_read = [prev_month.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]

    target_names = set(load_personnel(group).keys())
    leave_data = {}

    for m_date in months_to_read:
        sheet_name = get_sheet_name(group["attendance_sheet_name_pattern"], m_date)
        try:
            result = get_range(node_id, sheet_id=sheet_name, range="A1:BF50")
            vals = result.get("values") or result.get("data", {}).get("values", [])
        except:
            continue
        if not vals: continue
        header = vals[0]
        date_cols = {}
        for i, h in enumerate(header):
            if not h or i < 3: continue
            m = re.match(r'(\d+)\.(\d+)', str(h).strip())
            if m:
                month, day = int(m.group(1)), int(m.group(2))
                date_cols[i] = f"{today.year}-{month:02d}-{day:02d}"
        for row in vals[1:]:
            if not row[0]: continue
            name = str(row[0]).strip()
            if name not in target_names: continue
            for col_idx, date_str in date_cols.items():
                if col_idx >= len(row): continue
                val = str(row[col_idx] or "").strip()
                if not val or val == "早4": continue
                if "离职" in val or "转项" in val: continue
                # 不应出勤（不算请假，透明）
                if val in ("休息", "保护性事假", "调休", "上班半天离职"): continue
                # 调休半天/x小时：不算请假，工时按实际
                if val == "调休半天": continue
                if re.search(r'调休\d+(?:\.\d+)?\s*(?:小时|h)', val): continue
                # 休（加班）：正常计算，不算请假
                if val == "休（加班）": continue
                if date_str not in leave_data:
                    leave_data[date_str] = {"full": set(), "half": set(), "hour": {}}
                # 请假xh
                m2 = re.search(r'请假(\d+(?:\.\d+)?)\s*(?:小时|h)', val)
                if m2:
                    leave_data[date_str]["hour"][name] = float(m2.group(1))
                    continue
                # 精确半天假
                if val in ("请假上半天", "请假下半天", "年假半天"):
                    leave_data[date_str]["half"].add(name)
                    continue
                # 全天假
                if val == "半天年假半天病假":
                    leave_data[date_str]["full"].add(name)
                    continue
                if val in ("请假", "年假", "病假"):
                    leave_data[date_str]["full"].add(name)
                    continue
                print(f"  ⚠️ 考勤未识别: {name} {date_str} = \"{val}\"，请确认如何映射后手动重新触发")
                sys.exit(1)
    return leave_data


def build_weigui_dashboard_data(group):
    print(f"=== {group['group_name']} ===")
    mcp_setup(group["sheet_mcp_url"])

    # Read 绩效表（当月+上月）
    node_id = group["data_node_id"]
    today = datetime.datetime.now()
    prev_month = (today.replace(day=1) - datetime.timedelta(days=1))
    months_to_read = [prev_month.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]

    all_rows = []
    for m_date in months_to_read:
        sheet_name = get_sheet_name(group["perf_sheet_name_pattern"], m_date)
        print(f"  绩效表: 读取 sheet「{sheet_name}」...")
        for start in range(2, 10**6, 100):
            try:
                r = get_range(node_id, sheet_id=sheet_name, range=f"A{start}:S{start+99}")
                vals = r.get("values") or r.get("data", {}).get("values", [])
            except:
                vals = []
            all_rows.extend(vals)
            if len(vals) < 100 or not any(row and str(row[0] or "").strip() for row in vals): break

    excluded = set(group.get("exclude_from_metrics", []))
    exclude_employees = set(group.get("exclude_employees", []))
    records = []
    for row in all_rows:
        if not row or not str(row[0] or "").strip(): continue
        date_str = serial_to_date(row[0])
        if not date_str: continue
        name = str(row[2] or "").strip() if len(row) > 2 else ""
        name = ''.join(c for c in name if c.isprintable() and ord(c) > 31 and not (0x200B <= ord(c) <= 0x200F))
        if not name or name in exclude_employees: continue
        tg = str(row[6] or "").strip() if len(row) > 6 else ""
        ty = str(row[7] or "").strip() if len(row) > 7 else ""
        biao_chan = sf(row[8]) if len(row) > 8 else 0   # I = 标产
        biao_chan2 = sf(row[9]) if len(row) > 9 else 0  # J = 标产2
        k_hours = sf(row[10]) if len(row) > 10 else 0   # K = 作业工时（培训/答疑）
        qty = sf(row[11]) if len(row) > 11 else 0
        acc_thr = sf(row[15]) if len(row) > 15 else 0
        qc = sf(row[16]) if len(row) > 16 else 0
        diff = sf(row[17]) if len(row) > 17 else 0
        proj_h = sf(row[18]) if len(row) > 18 else 0   # S = 项目工时（生产/质检）
        records.append({
            "date": date_str, "name": name, "task_group": tg, "type": ty,
            "threshold": biao_chan2 if biao_chan2 > 0 else biao_chan,
            "qty": qty, "proj_h": proj_h, "k_hours": k_hours,
            "acc_threshold": acc_thr, "qc": qc, "diff": diff,
        })
    print(f"  绩效表: {len(records)} 条")

    # Attendance
    print("  读取考勤...")
    leave_data = load_attendance(group)
    print(f"  考勤: {sum(len(v['full'])+len(v['half']) for v in leave_data.values())} 人次请假")

    # Auto-detect projects
    proj_config = {}
    for r in records:
        if r["type"] in ("培训-业务需求", "答疑", "") or r["task_group"] in excluded: continue
        key = r["task_group"]
        if key not in proj_config and r["threshold"] > 0:
            proj_config[key] = {"threshold": r["threshold"], "acc_threshold": r["acc_threshold"]}
    print(f"  自动识别项目: {len(proj_config)} 个")

    from collections import defaultdict
    dates = sorted(set(r["date"] for r in records))
    print(f"  日期范围: {dates[0] if dates else '无'} ~ {dates[-1] if dates else '无'}")

    daily_data = []
    for date_str in dates:
        day_recs = [r for r in records if r["date"] == date_str]
        leave_info = leave_data.get(date_str, {"full": set(), "half": set(), "hour": {}})

        # Group by task_group — 只收集生产和质检用于准确率，但 CPD/吞吐只算生产
        task_groups = defaultdict(list)  # 生产记录
        qc_groups = defaultdict(list)    # 质检记录（仅用于准确率）
        for r in day_recs:
            if r["task_group"] in excluded: continue
            if r["type"] == "生产":
                task_groups[r["task_group"]].append(r)
            elif r["type"] == "质检":
                qc_groups[r["task_group"]].append(r)

        # Main project for leave assignment（按生产记录数量）
        proj_counts = {tg: len(recs) for tg, recs in task_groups.items()}
        main_project = max(proj_counts, key=proj_counts.get) if proj_counts else None

        # 每人当天实际总工时 = S列(项目工时,生产/质检) + K列(作业工时,培训/答疑)
        person_total_hours = defaultdict(float)
        for r in day_recs:
            if r["type"] in ("培训-业务需求", "答疑"):
                if r["k_hours"] > 0:
                    person_total_hours[r["name"]] += r["k_hours"]
            else:
                if r["proj_h"] > 0:
                    person_total_hours[r["name"]] += r["proj_h"]

        for tg, tg_recs in task_groups.items():
            cfg = proj_config.get(tg)
            if not cfg: continue
            threshold = cfg["threshold"]
            hourly = threshold / 8

            # producer_names = 做了该项目生产的人（不含只做质检的）
            producer_names = set(r["name"] for r in tg_recs)
            # 总产出 = 只算生产量
            total_qty = sum(r["qty"] for r in tg_recs)

            # 等效人数 = Σ 该项目生产工时 / 该人总工时
            input_people = 0
            non_prod_h = 0
            for name in producer_names:
                prod_hours = sum(r["proj_h"] for r in tg_recs if r["name"] == name)
                total_h = person_total_hours.get(name, 0)
                if total_h > 0 and prod_hours > 0:
                    input_people += prod_hours / total_h
                # 非生产工时 = 总工时 - 该项目生产工时（含质检/培训/答疑/其他项目时间）
                non_prod_h += (total_h - prod_hours) if total_h > prod_hours else 0

            # Leave: full +1, half +0.5
            this_leave = 0
            if tg == main_project:
                this_leave = len(leave_info["full"]) + len(leave_info["half"]) * 0.5 + sum(v/8 for v in leave_info.get("hour", {}).values())

            headcount = len(producer_names) + this_leave
            target = threshold * headcount - non_prod_h * hourly

            cpd = total_qty / input_people if input_people > 0 else 0
            tp = (total_qty / target * 1500) if target > 0 else 0

            # 准确率：只用生产记录的抽检数据
            total_qc = sum(r["qc"] for r in tg_recs)
            total_diff = sum(r["diff"] for r in tg_recs)
            accuracy = (1 - total_diff / total_qc) * 100 if total_qc > 0 else None

            daily_data.append({
                "date": date_str, "project": tg, "project_type": "生产",
                "category": "正式", "threshold": threshold,
                "acc_threshold": cfg["acc_threshold"],
                "cpd": round(cpd, 2), "throughput": round(tp, 2),
                "accuracy": round(accuracy, 2) if accuracy is not None else None,
                "input_people": round(input_people, 2),
                "producers": len(producer_names),
                "leave_count": this_leave, "total_qty": total_qty,
                "target": round(target, 2),
                "total_qc": total_qc, "total_diff": total_diff,
            })

    print(f"  看板数据: {len(daily_data)} 条")

    # Ranking（只用生产记录）
    person_acc = {}
    for r in records:
        if r["type"] != "生产" or r["task_group"] in excluded or r["qc"] <= 0: continue
        key = (r["date"], r["task_group"], r["name"])
        if key not in person_acc: person_acc[key] = {"qc": 0, "diff": 0}
        person_acc[key]["qc"] += r["qc"]
        person_acc[key]["diff"] += r["diff"]

    ranking_data = [{"date": d, "project": p, "name": n, "qc": v["qc"], "diff": v["diff"]}
                    for (d, p, n), v in person_acc.items()]

    active_employees = load_personnel(group)
    return {
        "group_name": group["group_name"],
        "leader": group["leader"],
        "data_source": "sheet",
        "employees": list(active_employees.keys()),
        "daily_data": daily_data,
        "ranking_data": ranking_data,
        "projects_config": {},
    }


if __name__ == "__main__":
    group = load_group("weigui")
    data = build_weigui_dashboard_data(group)
    output = Path(__file__).resolve().parent.parent / "dashboard" / "weigui_data.js"

    # 增量合并：保留上上月及之前的数据，当月+上月从表重算
    today = datetime.date.today()
    prev_month_start = f"{(today.replace(day=1) - datetime.timedelta(days=1)).year}-{(today.replace(day=1) - datetime.timedelta(days=1)).month:02d}-01"

    if output.exists():
        try:
            old_content = output.read_text(encoding="utf-8")
            old_json = old_content.split("=", 1)[1].strip().rstrip(";").strip()
            old_data = json.loads(old_json)
            old_daily = [d for d in old_data.get("daily_data", []) if d["date"] < prev_month_start]
            old_ranking = [r for r in old_data.get("ranking_data", []) if r["date"] < prev_month_start]
            data["daily_data"] = old_daily + data["daily_data"]
            data["ranking_data"] = old_ranking + data["ranking_data"]
            print(f"  增量合并: 保留 {len(old_daily)} 条历史 + {len(data['daily_data'])-len(old_daily)} 条当月+上月")
        except:
            print("  ⚠️ 无法读取旧数据，全量写入")

    _now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    js = f"// 违规申诉组数据 — 生成时间: {_now}\n"
    js += f"var WEIGUI_DATA = {json.dumps(data, ensure_ascii=False, indent=2)};\n"
    with open(output, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"\n✅ 数据已写入 {output}")
