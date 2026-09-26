"""
填报提醒 — 通用版
用法: python3 push_reminder.py <组名> [--test]
"""
import sys, datetime
from common import load_group, ensure_mcp, send_dingtalk, is_workday, TEST_WEBHOOK, TEST_SECRET

if len(sys.argv) < 2:
    print("用法: python3 push_reminder.py <组名> [--test]")
    sys.exit(1)

group = load_group(sys.argv[1])
test_mode = "--test" in sys.argv
today = datetime.date.today().strftime("%Y-%m-%d")

if not is_workday(today):
    print(f"[{today}] 非工作日，跳过推送")
    sys.exit(0)

webhook = TEST_WEBHOOK if test_mode else group["webhook_url"]
secret = TEST_SECRET if test_mode else group["webhook_secret"]

payload = {
    "msgtype": "actionCard",
    "actionCard": {
        "title": "下班前填量啦",
        "text": (
            f"❗ **{group['group_name']} 今日填报提醒**  {today}\n\n"
            f"@所有人 请在 **18:00 前** 填写今日工作量\n\n"
            f"> 有临时任务请填写临时任务量和工时"
        ),
        "singleTitle": "去填写",
        "singleURL": group.get("form_url", ""),
    },
    "at": {"isAtAll": True},
}

result = send_dingtalk(webhook, secret, payload)
mode = "测试群" if test_mode else "正式群"
print(f"[{today}] {group['group_name']} 填报提醒推送({mode}): {result}")
