"""
通用工具：加载组配置、多维表查询、钉钉推送、节假日判断
所有推送脚本共用此模块
"""
import sys, os, base64, hashlib, hmac, json, time, urllib.request, urllib.parse, datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
GROUPS_DIR = SKILL_DIR / "groups"

sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "devix-dingtalk-skill"))
from scripts.dingtalk_ai_table import query_records
from scripts._mcp_client import setup as mcp_setup

TEST_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=YOUR_DINGTALK_ACCESS_TOKEN"
TEST_SECRET  = "YOUR_DINGTALK_SECRET"


def load_group(name):
    path = GROUPS_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all_groups():
    groups = []
    for p in sorted(GROUPS_DIR.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            groups.append(json.load(f))
    return groups


def ensure_mcp(group):
    mcp_setup(group["mcp_url"])


def fetch_all(base_id, table_id):
    records, cursor = [], None
    while True:
        kwargs = {"limit": 100}
        if cursor:
            kwargs["cursor"] = cursor
        res = query_records(base_id, table_id, **kwargs)
        data = res.get("data", {})
        recs = data.get("records", [])
        records.extend(recs)
        cursor = data.get("nextCursor")
        if not recs or not cursor:
            break
    return records


def get_cell_name(cell):
    if isinstance(cell, dict):
        return cell.get("name", "")
    return str(cell) if cell else ""


def is_workday(date_str):
    try:
        url = f"https://timor.tech/api/holiday/info/{date_str}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        day_type = data.get("type", {}).get("type", -1)
        return day_type in (0, 3)
    except Exception as e:
        print(f"[节假日API] 查询失败: {e}，降级为周一至周五判断")
        return datetime.date.fromisoformat(date_str).weekday() < 5


def find_prev_workday(today):
    d = today - datetime.timedelta(days=1)
    for _ in range(10):
        if is_workday(d.strftime("%Y-%m-%d")):
            return d.strftime("%Y-%m-%d")
        d -= datetime.timedelta(days=1)
    return (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def sign_url(webhook_url, secret):
    ts = str(round(time.time() * 1000))
    enc = secret.encode()
    sig = urllib.parse.quote_plus(
        base64.b64encode(hmac.new(enc, f"{ts}\n{secret}".encode(), digestmod=hashlib.sha256).digest())
    )
    return f"{webhook_url}&timestamp={ts}&sign={sig}"


def send_dingtalk(webhook_url, secret, payload):
    url = sign_url(webhook_url, secret)
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def load_active_projects(group):
    """读取项目表，返回启用项目 {名称: {"threshold": 阈值, "acc_threshold": 准确率阈值}}"""
    fids = group["field_ids"]["project_table"]
    records = fetch_all(group["base_id"], group["table_ids"]["project"])
    projects = {}
    for r in records:
        cells = r["cells"]
        name = str(cells.get(fids["name"], "")).strip()
        threshold = float(cells.get(fids["threshold"], 0) or 0)
        acc_threshold = float(cells.get(fids.get("acc_threshold", ""), 0) or 0)
        if acc_threshold == 0:
            acc_threshold = 0.95
        status = get_cell_name(cells.get(fids["status"], {}))
        if name and status == "启用":
            projects[name] = {"threshold": threshold, "acc_threshold": acc_threshold}
    return projects


def load_active_employees(group):
    """读取在职员工 {工号: 姓名}"""
    fids = group["field_ids"]["roster"]
    records = fetch_all(group["base_id"], group["table_ids"]["roster"])
    active = {}
    for r in records:
        cells = r["cells"]
        status = get_cell_name(cells.get(fids["status"], {}))
        if status == "在职":
            emp_id = str(cells.get(fids["emp_id"], "")).strip()
            emp_name = str(cells.get(fids["emp_name"], "")).strip()
            if emp_id:
                active[emp_id] = emp_name
    return active


def load_daily_records(group, target_date):
    """读取指定日期的填报记录 {工号: cells}"""
    fids = group["field_ids"]["daily"]
    records = fetch_all(group["base_id"], group["table_ids"]["daily"])
    filled = {}
    for r in records:
        cells = r["cells"]
        date_val = str(cells.get(fids["date"], ""))[:10]
        if date_val != target_date:
            continue
        emp_id = str(cells.get(fids["emp_id"], "")).strip()
        if emp_id:
            filled[emp_id] = cells
    return filled
