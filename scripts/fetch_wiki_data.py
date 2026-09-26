"""
WIKI组看板数据抓取（v2）
绩效表 → 产量、标产、培训工时、质检准确率
量级登记 → 请假 + 非任务时长
人员表 → 在职判断
"""
import sys, json, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))

from scripts.dingtalk_doc import setup as mcp_setup
from scripts.dingtalk_sheet import get_range
from common import load_group

EXCEL_EPOCH = datetime.datetime(1899, 12, 30)


def serial_to_date(serial):
    if serial is None or serial == "":
        return None
    try:
        return (EXCEL_EPOCH + datetime.timedelta(days=int(float(serial)))).strftime("%Y-%m-%d")
    except:
        return None


def load_personnel(group):
    node_id = group["personnel_node_id"]
    sheet_id = group["personnel_sheet_id"]
    result = get_range(node_id, sheet_id=sheet_id, range="A1:G60")
    vals = result.get("values") or result.get("data", {}).get("values", [])
    people = []
    for row in vals[1:]:
        if not row[0]:
            continue
        emp_id = str(row[0]).strip()
        name = str(row[1]).strip()
        status = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        leave_date = serial_to_date(row[6] if len(row) > 6 else None)
        if name == group.get("leader", ""):
            continue
        people.append({"emp_id": emp_id, "name": name, "status": status, "leave_date": leave_date})
    return people


def is_active_on(person, date_str):
    if person["status"] == "在职":
        return True
    if person["leave_date"] and person["leave_date"] > date_str:
        return True
    return False


def parse_perf_table(group):
    """读绩效表关键列，分两次避免超时。sheet名固定，直接用名字访问，不依赖sheetId（每月换文档，ID会变）"""
    node_id = group["data_node_id"]
    sheet_id = "绩效"

    print("    绩效表: 读取 D-L 列...")
    r1 = get_range(node_id, sheet_id=sheet_id, range="D2:L2200")
    part1 = r1.get("values") or r1.get("data", {}).get("values", [])
    print(f"    绩效表: D-L {len(part1)} 行")

    print("    绩效表: 读取 N-U 列...")
    r2 = get_range(node_id, sheet_id=sheet_id, range="N2:U2200")
    part2 = r2.get("values") or r2.get("data", {}).get("values", [])
    print(f"    绩效表: N-U {len(part2)} 行")

    # D-L: 日期(0) 工号(1) 姓名(2) 项目类型(3) 项目(4) 子项目(5) 任务分组(6) 类型(7) 标产(8)
    # N-U: 作业工时(0) 作业量(1) 额外(2) 绩效用(3) 验收(4) 准确率目标(5) 被抽检量(6) 不一致量(7)

    def safe(arr, idx, default=0):
        try:
            v = arr[idx] if idx < len(arr) else default
            return float(v) if v else default
        except:
            return default

    records = []
    for i in range(len(part1)):
        r = part1[i]
        r2_row = part2[i] if i < len(part2) else []
        date_str = serial_to_date(r[0] if r else None)
        if not date_str:
            continue
        emp_id = str(r[1] or "").strip() if len(r) > 1 else ""
        if not emp_id:
            continue
        records.append({
            "date": date_str,
            "emp_id": emp_id,
            "name": str(r[2] or "").strip() if len(r) > 2 else "",
            "project_type": str(r[3] or "").strip() if len(r) > 3 else "",
            "task_group": str(r[6] or "").strip() if len(r) > 6 else "",
            "type": str(r[7] or "").strip() if len(r) > 7 else "",
            "threshold": safe(r, 8),
            "hours": safe(r2_row, 0),
            "qty": safe(r2_row, 1),
            "acc_threshold": safe(r2_row, 5),  # S列 准确率目标
            "qc": safe(r2_row, 6),
            "diff": safe(r2_row, 7),
        })
    return records


def parse_qty_register_hours(group):
    """读量级登记：非任务时长 + 多项目工时拆分（不再读请假，改由考勤sheet）。sheet名固定，直接用名字访问"""
    import re
    node_id = group["data_node_id"]
    sheet_id = "量级登记"

    hdr = get_range(node_id, sheet_id=sheet_id, range="A1:CZ1")
    row1 = (hdr.get("values") or hdr.get("data", {}).get("values", [[]]))[0]

    date_columns = {}
    for i, v in enumerate(row1):
        if v and v != " " and v != "姓名":
            ds = serial_to_date(v)
            if ds and ds not in date_columns:
                date_columns[ds] = i

    data = get_range(node_id, sheet_id=sheet_id, range="A3:CZ58")
    rows = data.get("values") or data.get("data", {}).get("values", [])

    hours_data = {}   # {(date, emp_id): non_task_hours}
    split_data = {}   # {(date, emp_id): {project: hours}} for multi-project days

    for row in rows:
        emp_id = str(row[0] or "").strip() if row[0] else ""
        if not emp_id or emp_id in ("应产出量级", "实际产出量级", "差异"):
            continue

        for date_str, col in date_columns.items():
            if col >= len(row):
                continue
            project = str(row[col] or "").strip() if row[col] else ""
            non_task_raw = row[col + 2] if col + 2 < len(row) else ""
            content = str(row[col + 3] or "").strip() if col + 3 < len(row) else ""

            if project == "请假" or str(row[col + 1] if col + 1 < len(row) else "").strip() == "请假":
                continue  # 请假由考勤sheet处理

            non_task = 0
            try:
                non_task = float(non_task_raw) if non_task_raw else 0
            except:
                pass
            if non_task > 0:
                hours_data[(date_str, emp_id)] = non_task

            # 多项目解析：项目列逗号分隔，备注中提取各副项目工时
            if "," in project or "，" in project:
                projects = [p.strip() for p in re.split(r'[,，]', project) if p.strip()]
                if len(projects) >= 2 and content:
                    # 提取备注中所有 "项目名Xh" 或 "项目名X小时" 模式
                    secondary = {}
                    for proj in projects[1:]:
                        # 在备注中查找该项目名后面的小时数
                        pattern = re.escape(proj) + r'.*?(\d+\.?\d*)\s*(?:h|小时)'
                        m = re.search(pattern, content, re.IGNORECASE)
                        if m:
                            secondary[proj] = float(m.group(1))
                    # 如果没有按项目名匹配到，尝试提取所有 Xh 模式按顺序分配
                    if not secondary:
                        all_hours = re.findall(r'(\d+\.?\d*)\s*(?:h|小时)', content, re.IGNORECASE)
                        for i, proj in enumerate(projects[1:]):
                            if i < len(all_hours):
                                secondary[proj] = float(all_hours[i])
                    if secondary:
                        total_secondary = sum(secondary.values())
                        primary_hours = 8 - non_task - total_secondary
                        if primary_hours < 0:
                            primary_hours = 0
                        split = {projects[0]: primary_hours}
                        split.update(secondary)
                        split_data[(date_str, emp_id)] = split

    return hours_data, split_data


def load_wiki_attendance(group, date_str):
    """读考勤sheet，返回 {full_leave: set(emp_ids), half_leave: set(emp_ids), not_show: set(emp_ids)}"""
    import re
    node_id = group["data_node_id"]
    try:
        result = get_range(node_id, sheet_id="考勤", range="A1:BF60")
        vals = result.get("values") or result.get("data", {}).get("values", [])
    except:
        return {"full_leave": set(), "half_leave": set(), "not_show": set()}
    if not vals:
        return {"full_leave": set(), "half_leave": set(), "not_show": set()}

    header = vals[0]
    target_col = None
    month = int(date_str[5:7])
    day = int(date_str[8:10])
    for i, h in enumerate(header):
        if not h or i < 2: continue
        ds = serial_to_date(h)
        if ds and int(ds[5:7]) == month and int(ds[8:10]) == day:
            target_col = i
            break
        m = re.match(r'(\d+)\.(\d+)', str(h).strip())
        if m and int(m.group(1)) == month and int(m.group(2)) == day:
            target_col = i
            break

    if target_col is None:
        return {"full_leave": set(), "half_leave": set(), "not_show": set()}

    full_leave = set()
    half_leave = set()
    not_show = set()
    for row in vals[1:]:
        if not row[0]: continue
        emp_id = str(row[0] or "").strip()  # A=工号
        if not emp_id or target_col >= len(row): continue
        val = str(row[target_col] or "").strip()
        if not val or val == "早4": continue
        if "转项" in val or "离职" in val:
            not_show.add(emp_id)
        elif val in ("事假1", "年假1", "丧假1", "病假1"):
            full_leave.add(emp_id)
        elif val in ("事假上", "事假下", "年假上", "年假下", "病假上", "病假下"):
            half_leave.add(emp_id)
    return {"full_leave": full_leave, "half_leave": half_leave, "not_show": not_show}


def build_wiki_dashboard_data(group):
    print(f"=== {group['group_name']} ===")
    mcp_setup(group["sheet_mcp_url"])
    if group.get("personnel_sheet_mcp_url"):
        mcp_setup(group["personnel_sheet_mcp_url"])

    people = load_personnel(group)
    active_now = [p for p in people if p["status"] == "在职"]
    print(f"  人员表: {len(people)} 人, 当前在职: {len(active_now)}")

    print("  读取量级登记（请假+非任务时长+多项目拆分）...")
    hours_data, split_data = parse_qty_register_hours(group)
    print(f"  量级登记: {len(hours_data)} 条非任务时长, {len(split_data)} 条多项目拆分")

    perf_records = parse_perf_table(group)
    print(f"  绩效表: {len(perf_records)} 条")

    # Build project config dynamically from 绩效表 (标产 col L, 准确率目标 col S)
    # This avoids manual config maintenance - thresholds come directly from the data
    excluded = set(group.get("exclude_from_metrics", []))
    proj_config_cache = {}  # {(task_group, type): {threshold, acc_threshold}}
    for r in perf_records:
        if r["type"] in ("培训-业务需求", "") or r["task_group"] in excluded:
            continue
        key = (r["task_group"], r["type"])
        if key not in proj_config_cache and r["threshold"] > 0:
            proj_config_cache[key] = {
                "threshold": r["threshold"],
                "acc_threshold": r.get("acc_threshold", 0.95),
            }

    # Convert to all_projects dict used by rest of code
    # Use qty_register_mapping to determine category (正式 vs 临时)
    qty_mapping_inv = {v: k for k, v in group.get("qty_register_mapping", {}).items()}
    formal_names = set()
    for cat_dict in [group.get("projects", {}).get("正式", {})]:
        formal_names.update(cat_dict.keys())

    all_projects = {}
    for (task_group, task_type), cfg in proj_config_cache.items():
        key = f"{task_group}|{task_type}"
        # Determine category: if name matches a formal project name (or its mapped name), it's 正式
        is_formal = task_group in formal_names or any(task_group in fn for fn in formal_names)
        all_projects[key] = {
            "name": task_group,
            "type": task_type,
            "category": "正式" if is_formal else "临时",
            "threshold": cfg["threshold"],
            "acc_threshold": cfg["acc_threshold"],
        }

    print(f"  自动识别项目: {len(all_projects)} 个")
    for key, cfg in sorted(all_projects.items()):
        print(f"    {cfg['name']} ({cfg['type']}) 标产={cfg['threshold']} 准确率={cfg['acc_threshold']}")

    dates = sorted(set(r["date"] for r in perf_records))
    print(f"  日期范围: {dates[0] if dates else '无'} ~ {dates[-1] if dates else '无'}")

    daily_data = []
    for date_str in dates:
        active_people = [p for p in people if is_active_on(p, date_str)]
        active_ids = {p["emp_id"] for p in active_people}

        # 读考勤sheet获取请假
        att = load_wiki_attendance(group, date_str)
        full_leave_ids = att["full_leave"] & active_ids
        half_leave_ids = att["half_leave"] & active_ids
        not_show_ids = att["not_show"]
        active_ids = active_ids - not_show_ids
        leave_count_full = len(full_leave_ids)
        leave_count_half = len(half_leave_ids)

        day_perf = [r for r in perf_records if r["date"] == date_str and r["emp_id"] in active_ids]
        if not day_perf:
            continue

        # Group by task_group + type (only 生产, exclude 质检 and 培训)
        task_groups = {}
        for r in day_perf:
            if r["task_group"] in excluded:
                continue
            if r["type"] != "生产":
                continue
            key = f"{r['task_group']}|{r['type']}"
            if key not in task_groups:
                task_groups[key] = []
            task_groups[key].append(r)

        # Find main formal project for leave assignment
        formal_projects = {}
        for r in day_perf:
            if r["project_type"] == "正式项目" and r["type"] == "生产" and r["task_group"] not in excluded:
                formal_projects[r["task_group"]] = formal_projects.get(r["task_group"], 0) + 1
        main_project = max(formal_projects, key=formal_projects.get) if formal_projects else None

        for task_key, records in task_groups.items():
            # Match config
            proj_config = None
            task_group_name = records[0]["task_group"]
            task_type_name = records[0]["type"]
            key = f"{task_group_name}|{task_type_name}"
            proj_config = all_projects.get(key)

            if not proj_config:
                continue

            threshold = proj_config["threshold"]
            hourly = threshold / 8

            producer_ids = set(r["emp_id"] for r in records)
            total_qty = sum(r["qty"] for r in records)

            # Training hours per person from 绩效表
            train_hours = {}
            for r in day_perf:
                if "培训" in r["type"] and r["hours"] > 0:
                    train_hours[r["emp_id"]] = train_hours.get(r["emp_id"], 0) + r["hours"]

            # Calculate input_people (equivalent) and non_prod_hours
            input_people = 0
            non_prod_h = 0
            qty_mapping = group.get("qty_register_mapping", {})
            for emp_id in producer_ids:
                nt = hours_data.get((date_str, emp_id), 0)
                th = train_hours.get(emp_id, 0)

                # Check if this person has multi-project split
                split = split_data.get((date_str, emp_id))
                if split:
                    # Find hours for this specific project
                    proj_h = 0
                    for split_proj, split_hours in split.items():
                        mapped = qty_mapping.get(split_proj, split_proj)
                        if mapped == task_group_name or task_group_name in mapped or mapped in task_group_name:
                            proj_h = split_hours
                            break
                    if proj_h > 0:
                        input_people += proj_h / 8
                    non_prod_h += (8 - proj_h)
                else:
                    non_task = max(nt, th)
                    prod_h = 8 - non_task
                    if prod_h > 0:
                        input_people += prod_h / 8
                    non_prod_h += non_task

            # Leave count (only for main project): full +1, half +0.5
            this_leave = (leave_count_full + leave_count_half * 0.5) if task_group_name == main_project else 0

            headcount = len(producer_ids) + this_leave
            target = threshold * headcount - non_prod_h * hourly

            cpd = total_qty / input_people if input_people > 0 else 0
            tp = (total_qty / target * 1500) if target > 0 else 0

            total_qc = sum(r["qc"] for r in records)
            total_diff = sum(r["diff"] for r in records)
            accuracy = (1 - total_diff / total_qc) * 100 if total_qc > 0 else None

            daily_data.append({
                "date": date_str,
                "project": proj_config["name"],
                "project_type": proj_config["type"],
                "category": proj_config["category"],
                "threshold": threshold,
                "acc_threshold": proj_config["acc_threshold"],
                "cpd": round(cpd, 2),
                "throughput": round(tp, 2),
                "accuracy": round(accuracy, 2) if accuracy is not None else None,
                "input_people": round(input_people, 2),
                "producers": len(producer_ids),
                "leave_count": this_leave,
                "total_qty": total_qty,
                "target": round(target, 2),
                "total_qc": total_qc,
                "total_diff": total_diff,
            })

    print(f"  看板数据: {len(daily_data)} 条 (项目×天)")

    # Build person-level accuracy data for ranking
    person_acc = {}  # {(date, project, emp_name): {qc, diff}}
    for r in perf_records:
        if r["type"] not in ("生产", "质检"):
            continue
        if r["task_group"] in excluded:
            continue
        if r["qc"] <= 0:
            continue
        key = (r["date"], r["task_group"], r["name"])
        if key not in person_acc:
            person_acc[key] = {"qc": 0, "diff": 0}
        person_acc[key]["qc"] += r["qc"]
        person_acc[key]["diff"] += r["diff"]

    ranking_data = [{"date": d, "project": p, "name": n, "qc": v["qc"], "diff": v["diff"]}
                    for (d, p, n), v in person_acc.items()]

    return {
        "group_name": group["group_name"],
        "leader": group["leader"],
        "data_source": "sheet",
        "employees": [p["name"] for p in active_now],
        "daily_data": daily_data,
        "ranking_data": ranking_data,
        "projects_config": {k: v for k, v in all_projects.items()},
    }


if __name__ == "__main__":
    group = load_group("wiki")
    if group.get("paused"):
        print("WIKI 组已暂停（wiki.json paused=true），跳过看板数据更新。")
        sys.exit(0)
    data = build_wiki_dashboard_data(group)

    output = Path(__file__).resolve().parent.parent / "dashboard" / "wiki_data.js"
    _now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    js = f"// WIKI组数据 — 生成时间: {_now}\n"
    js += f"var WIKI_UPDATE_TIME = '{_now}';\n"
    js += f"var WIKI_DATA = {json.dumps(data, ensure_ascii=False, indent=2)};\n"
    with open(output, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"\n✅ 数据已写入 {output}")
