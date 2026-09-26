"""
天猫榜单看板数据抓取
文档1: 周度/月度汇总 → CPD、吞吐、准确率（项目维度）
文档2: 日常数据 → 个人准确率排名
"""
import sys, json, datetime, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))

from scripts.dingtalk_doc import setup as mcp_setup
from scripts.dingtalk_sheet import get_range
from common import load_group

EXCEL_EPOCH = datetime.datetime(1899, 12, 30)

def sf(v):
    try: return float(v) if v is not None and str(v).strip() and str(v).strip() != '-' else 0
    except: return 0


def parse_period(period_str):
    """解析周期字符串如 '6.22-6.26' → ('2026-06-22', '2026-06-26')"""
    if not period_str or not period_str.strip():
        return None, None
    year = datetime.date.today().year
    m = re.match(r'(\d+)\.(\d+)-(\d+)\.(\d+)', period_str.strip())
    if m:
        m1, d1, m2, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        start_year = year if m1 <= 12 else year - 1
        end_year = year if m2 >= m1 else year + 1
        return f"{start_year}-{m1:02d}-{d1:02d}", f"{end_year}-{m2:02d}-{d2:02d}"
    m2 = re.match(r'(\d+)\.(\d+)-(\d+)', period_str.strip())
    if m2:
        month, d1, d2 = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        return f"{year}-{month:02d}-{d1:02d}", f"{year}-{month:02d}-{d2:02d}"
    return None, None


def load_weekly_summary(group):
    """读周度汇总表，筛选天猫榜单"""
    node_id = group["summary_node_id"]
    sheet_name = group["summary_sheets"]["周度"]
    project_filter = group["summary_project_filter"]

    r = get_range(node_id, sheet_id=sheet_name, range="A1:T500")
    vals = r.get("values") or r.get("data", {}).get("values", [])

    # 周度表列: A=周期 B=任务归属项目 C=任务名称 D=任务量级目标 E=周任务量级
    # J=人效目标(CPD阈值) K=本周人效(CPD) M=准确率目标 N=抽检量 O=不一致量 P=本周准确率
    weekly_data = []
    current_period = ""
    current_project = ""
    for row in vals[1:]:
        period = str(row[0] or "").strip()
        project = str(row[1] or "").strip()
        if period:
            current_period = period
            current_project = project
        elif not project:
            project = current_project
        else:
            current_project = project

        if current_project != project_filter:
            continue

        task_name = str(row[2] or "").strip()
        if not task_name:
            continue
        task_type = str(row[3] or "").strip()  # 长期任务/临时任务

        start_date, end_date = parse_period(current_period)
        if not start_date:
            continue

        target_qty = sf(row[4])
        actual_qty = sf(row[5])
        cpd_target = sf(row[10])
        cpd = sf(row[11])
        acc_target = sf(row[13])
        qc_count = sf(row[14])
        diff_count = sf(row[15])
        accuracy_raw = row[16] if len(row) > 16 else None
        accuracy = sf(accuracy_raw) * 100 if accuracy_raw and str(accuracy_raw).strip() not in ('-', '', '#DIV/0!') else None
        throughput = (actual_qty / target_qty * 1500) if target_qty > 0 else 0

        weekly_data.append({
            "period": current_period,
            "start_date": start_date,
            "end_date": end_date,
            "project": task_name,
            "category": "正式" if task_type == "长期任务" else "临时",
            "cpd": round(cpd, 2),
            "cpd_target": round(cpd_target, 2),
            "throughput": round(throughput, 2),
            "accuracy": round(accuracy, 2) if accuracy is not None else None,
            "acc_target": round(acc_target * 100, 2) if acc_target > 0 else 95,
            "total_qty": actual_qty,
            "target_qty": target_qty,
            "total_qc": qc_count,
            "total_diff": diff_count,
        })

    print(f"  周度数据: {len(weekly_data)} 条")
    return weekly_data


def load_monthly_summary(group):
    """读月度汇总表"""
    node_id = group["summary_node_id"]
    sheet_name = group["summary_sheets"]["月度"]

    r = get_range(node_id, sheet_id=sheet_name, range="A1:T100")
    vals = r.get("values") or r.get("data", {}).get("values", [])

    # 月度表列: A=周期 B=任务名称 D=任务量级目标 E=达成任务量级
    # J=人效目标 K=本月人效 M=准确率目标 N=抽检量 O=不一致量 P=本月准确率
    monthly_data = []
    current_period = ""
    for row in vals[1:]:
        period = str(row[0] or "").strip()
        if period:
            current_period = period

        task_name = str(row[1] or "").strip()
        if not task_name:
            continue
        task_type = str(row[2] or "").strip()  # 长期任务/临时任务

        start_date, end_date = parse_period(current_period)
        if not start_date:
            continue

        target_qty = sf(row[3])
        actual_qty = sf(row[4])
        cpd_target = sf(row[9])
        cpd = sf(row[10])
        acc_target = sf(row[12])
        qc_count = sf(row[13])
        diff_count = sf(row[14])
        accuracy_raw = row[15] if len(row) > 15 else None
        accuracy = sf(accuracy_raw) * 100 if accuracy_raw and str(accuracy_raw).strip() not in ('-', '', '#DIV/0!') else None
        throughput = (actual_qty / target_qty * 1500) if target_qty > 0 else 0

        monthly_data.append({
            "period": current_period,
            "start_date": start_date,
            "end_date": end_date,
            "project": task_name,
            "category": "正式" if task_type == "长期任务" else "临时",
            "cpd": round(cpd, 2),
            "cpd_target": round(cpd_target, 2),
            "throughput": round(throughput, 2),
            "accuracy": round(accuracy, 2) if accuracy is not None else None,
            "acc_target": round(acc_target * 100, 2) if acc_target > 0 else 95,
            "total_qty": actual_qty,
            "target_qty": target_qty,
            "total_qc": qc_count,
            "total_diff": diff_count,
        })

    print(f"  月度数据: {len(monthly_data)} 条")
    return monthly_data


def load_ranking_data(group):
    """读当月日常数据表，聚合个人准确率"""
    node_id = group["ranking_node_id"]
    pattern = group["ranking_sheet_name_pattern"]
    today = datetime.date.today()
    sheet_name = pattern.format(year=today.year, month=today.month)

    print(f"  排名数据: 读取 sheet「{sheet_name}」...")
    try:
        r = get_range(node_id, sheet_id=sheet_name, range="A1:I1000")
        vals = r.get("values") or r.get("data", {}).get("values", [])
    except:
        print(f"  ⚠️ 未找到 sheet「{sheet_name}」")
        return []

    # A=日期(Excel序列号) C=姓名 D=队列 H=抽检数 I=错误量
    records = []
    for row in vals[1:]:
        if not row[0] or not str(row[0]).strip():
            continue
        try:
            date_str = (EXCEL_EPOCH + datetime.timedelta(days=int(float(row[0])))).strftime("%Y-%m-%d")
        except:
            continue
        name = str(row[2] or "").strip()
        project = str(row[3] or "").strip()
        qc = sf(row[7]) if len(row) > 7 else 0
        diff = sf(row[8]) if len(row) > 8 else 0
        if not name or not project:
            continue
        records.append({
            "date": date_str,
            "name": name,
            "project": project,
            "qc": qc,
            "diff": diff,
        })

    print(f"  排名数据: {len(records)} 条")
    return records


def build_tianmao_dashboard_data(group):
    print(f"=== {group['group_name']} ===")

    # 项目维度（文档1）
    mcp_setup(group["sheet_mcp_url"])
    weekly_data = load_weekly_summary(group)
    monthly_data = load_monthly_summary(group)

    # 个人排名（文档2，不同组织的 MCP）
    mcp_setup(group["ranking_mcp_url"])
    ranking_records = load_ranking_data(group)

    return {
        "group_name": group["group_name"],
        "leader": group.get("leader", ""),
        "data_source": "tianmao",
        "weekly_data": weekly_data,
        "monthly_data": monthly_data,
        "ranking_data": ranking_records,
    }


if __name__ == "__main__":
    group = load_group("tianmao")
    data = build_tianmao_dashboard_data(group)

    output = Path(__file__).resolve().parent.parent / "dashboard" / "tianmao_data.js"

    # 增量合并：保留旧月排名数据
    today = datetime.date.today()
    current_month_start = f"{today.year}-{today.month:02d}-01"

    if output.exists():
        try:
            old_content = output.read_text(encoding="utf-8")
            old_json = old_content.split("=", 1)[1].strip().rstrip(";").strip()
            old_data = json.loads(old_json)
            old_ranking = [r for r in old_data.get("ranking_data", []) if r["date"] < current_month_start]
            data["ranking_data"] = old_ranking + data["ranking_data"]
            print(f"  增量合并: 保留 {len(old_ranking)} 条历史排名 + {len(data['ranking_data'])-len(old_ranking)} 条当月")
        except:
            print("  ⚠️ 无法读取旧数据，全量写入")

    _now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    js = f"// 天猫榜单数据 — 生成时间: {_now}\n"
    js += f"var TIANMAO_DATA = {json.dumps(data, ensure_ascii=False, indent=2)};\n"
    with open(output, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"\n✅ 数据已写入 {output}")
