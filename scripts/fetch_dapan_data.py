"""
从多维表拉取真实数据，生成 dashboard 用的 dapan_data.js
用法: python3 fetch_dashboard_data.py
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_all_groups, ensure_mcp, fetch_all, get_cell_name

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"

all_groups_data = []

for group in load_all_groups():
    print(f"=== {group['group_name']} ===")
    if group.get("data_source") == "sheet":
        print("  Sheet 数据源，跳过（用 fetch_wiki_data.py）")
        continue
    ensure_mcp(group)

    fids = group["field_ids"]
    pfields = group["project_fields"]
    base_id = group["base_id"]

    # 读项目表
    proj_records = fetch_all(base_id, group["table_ids"]["project"])
    projects = []
    for r in proj_records:
        cells = r["cells"]
        name = str(cells.get(fids["project_table"]["name"], "")).strip()
        threshold = float(cells.get(fids["project_table"]["threshold"], 0) or 0)
        status = get_cell_name(cells.get(fids["project_table"]["status"], {}))
        if name:
            projects.append({"name": name, "threshold": threshold, "status": status})
    print(f"  项目: {[p['name'] for p in projects]}")

    # 读员工名单
    roster_records = fetch_all(base_id, group["table_ids"]["roster"])
    employees = []
    for r in roster_records:
        cells = r["cells"]
        status = get_cell_name(cells.get(fids["roster"]["status"], {}))
        if status == "在职":
            employees.append(str(cells.get(fids["roster"]["emp_name"], "")).strip())
    print(f"  在职员工: {len(employees)} 人")

    # 读日报
    daily_records = fetch_all(base_id, group["table_ids"]["daily"])
    records = []
    for r in daily_records:
        cells = r["cells"]
        date_val = str(cells.get(fids["daily"]["date"], ""))[:10]
        if not date_val:
            continue

        rec = {
            "date": date_val,
            "name": str(cells.get(fids["daily"]["emp_name"], "")).strip(),
            "leave": get_cell_name(cells.get(fids["daily"]["leave"], {})),
        }

        for proj_name, pf in pfields.items():
            prefix = proj_name.lower().replace(" ", "_")
            rec[f"{prefix}_qty"] = float(cells.get(pf["qty"], 0) or 0)
            rec[f"{prefix}_hours"] = float(cells.get(pf["hours"], 0) or 0)
            rec[f"{prefix}_qc"] = float(cells.get(pf["qc"], 0) or 0)
            rec[f"{prefix}_diff"] = float(cells.get(pf["diff"], 0) or 0)

        has_temp = group.get("has_temp_tasks", False)
        if has_temp:
            rec["temp_qty"] = float(cells.get(fids["daily"].get("temp_qty", ""), 0) or 0)
            rec["temp_hours"] = float(cells.get(fids["daily"].get("temp_hours", ""), 0) or 0)
        else:
            rec["temp_qty"] = 0
            rec["temp_hours"] = 0
        rec["train_hours"] = float(cells.get(fids["daily"].get("train_hours", ""), 0) or 0)

        records.append(rec)

    print(f"  日报记录: {len(records)} 条")

    # 统计有数据的日期
    dates = sorted(set(r["date"] for r in records))
    print(f"  日期范围: {dates[0] if dates else '无'} ~ {dates[-1] if dates else '无'}")

    all_groups_data.append({
        "group_name": group["group_name"],
        "leader": group["leader"],
        "projects": projects,
        "employees": employees,
        "records": records,
        "project_field_keys": {
            proj_name: {
                "qty": f"{proj_name.lower().replace(' ', '_')}_qty",
                "hours": f"{proj_name.lower().replace(' ', '_')}_hours",
                "qc": f"{proj_name.lower().replace(' ', '_')}_qc",
                "diff": f"{proj_name.lower().replace(' ', '_')}_diff",
            }
            for proj_name in pfields
        },
        "has_temp_tasks": group.get("has_temp_tasks", False),
    })

import datetime as _dt
_now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
output = DASHBOARD_DIR / "dapan_data.js"
js_content = f"// 真实数据 — 由 fetch_dapan_data.py 生成\n"
js_content += f"var DAPAN_UPDATE_TIME = '{_now}';\n"
js_content += f"var DASHBOARD_DATA = {json.dumps(all_groups_data, ensure_ascii=False, indent=2)};\n"

with open(output, "w", encoding="utf-8") as f:
    f.write(js_content)

print(f"\n✅ 数据已写入 {output}")
print(f"   共 {len(all_groups_data)} 个组，{sum(len(g['records']) for g in all_groups_data)} 条记录")
