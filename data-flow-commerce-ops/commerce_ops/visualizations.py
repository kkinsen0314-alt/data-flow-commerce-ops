import csv
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from .datasets import MAX_INPUT_BYTES
from .native_api import OPERATOR_DATA_SOURCES
from .visualization_models import (
    DetailColumn, DetailKind, VisualizationChart, VisualizationDetails,
    VisualizationFilters, VisualizationMetric, VisualizationSnapshot,
)


PAID = {"paid", "completed"}
ORDER_LABELS = {"paid": "已付款", "completed": "已完成", "pending": "待付款", "cancelled": "已取消"}
COLUMNS = {
    "content": [("reference", "内容编号"), ("published_at", "发布时间"), ("impressions", "曝光次数"), ("clicks", "点击次数"), ("leads", "关联线索数")],
    "live": [("reference", "线索编号"), ("session", "直播场次"), ("reserved_at", "预约时间"), ("attended", "是否到课"), ("ordered", "是否购买课程")],
    "leads": [("reference", "线索编号"), ("channel", "线索渠道"), ("created_at", "创建时间"), ("paid_orders", "有效付款订单数"), ("gmv", "付款金额（元）")],
    "followups": [("reference", "线索编号"), ("channel", "线索渠道"), ("assigned_at", "分配时间"), ("first_followup_at", "首次跟进时间"), ("hours", "首跟进间隔（小时）"), ("bucket", "时效分组")],
    "orders": [("reference", "订单编号"), ("lead", "线索编号"), ("channel", "线索渠道"), ("ordered_at", "下单时间"), ("paid_at", "付款时间"), ("status", "订单状态"), ("gmv", "有效付款金额（元）")],
}
REQUIRED = {
    "short_video": {"content_id_hash", "click_id_hash", "published_at", "impressions", "plays", "clicks"},
    "live_session": {"用户ID", "直播场次", "预约时间", "是否到课", "是否购买课程"},
    "channel_lead": {"lead_id_hash", "click_id_hash", "channel", "created_at"},
    "sales_followup": {"lead_id_hash", "assigned_at", "first_followup_at"},
    "order": {"order_id_hash", "lead_id_hash", "ordered_at", "paid_at", "paid_amount", "order_status"},
}
KEYS = {
    "short_video": ("content_id_hash",), "live_session": ("用户ID", "直播场次"),
    "channel_lead": ("lead_id_hash",), "sales_followup": ("lead_id_hash",), "order": ("order_id_hash",),
}


def moment(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def amount(rows: list[dict]) -> float:
    return float(sum((Decimal(row["paid_amount"]) for row in rows if row["order_status"] in PAID), Decimal(0)))


def followup_hours(row: dict | None) -> float | None:
    if not row or not row["assigned_at"] or not row["first_followup_at"]:
        return None
    return (moment(row["first_followup_at"]) - moment(row["assigned_at"])).total_seconds() / 3600


def bucket(hours: float | None) -> str:
    if hours is None:
        return "无首跟进记录"
    if hours < 0:
        return "时间异常"
    if hours <= 1:
        return "1小时内"
    if hours <= 24:
        return "1–24小时"
    return "超过24小时"


class VisualizationDataError(ValueError):
    pass


class VisualizationService:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()

    def load(self, filters: VisualizationFilters):
        paths = OPERATOR_DATA_SOURCES.get(filters.source_id)
        if paths is None:
            raise ValueError("请选择已接入的数据源。")
        tables = {}
        modified = []
        try:
            for kind, relative in paths.items():
                path = (self.data_root / relative).resolve()
                if not path.is_relative_to(self.data_root) or path.stat().st_size > MAX_INPUT_BYTES:
                    raise ValueError("invalid dataset")
                modified.append(path.stat().st_mtime)
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not REQUIRED[kind].issubset(reader.fieldnames or []):
                        raise ValueError("missing fields")
                    rows = list(reader)
                unique = {}
                for row in rows:
                    key = tuple(row[column] for column in KEYS[kind])
                    if not all(key) or (key in unique and unique[key] != row):
                        raise ValueError("ambiguous relationship key")
                    unique[key] = row
                tables[kind] = list(unique.values())
            for row in tables["order"]:
                value = Decimal(row["paid_amount"])
                if not value.is_finite() or value < 0 or row["order_status"] not in ORDER_LABELS:
                    raise ValueError("invalid order")
                if row["order_status"] in PAID:
                    moment(row["paid_at"])
            for row in tables["short_video"]:
                for field in ("impressions", "plays", "clicks"):
                    if int(row[field]) < 0:
                        raise ValueError("invalid metric")
            all_leads = tables["channel_lead"]
            if not all_leads:
                raise ValueError("no source leads")
            dates = [moment(row["created_at"]).date() for row in all_leads]
            observed = [moment(row[field]) for kind, fields in {
                "channel_lead": ["created_at"], "short_video": ["published_at"],
                "live_session": ["预约时间"], "sales_followup": ["assigned_at", "first_followup_at"],
                "order": ["ordered_at", "paid_at"],
            }.items() for row in tables[kind] for field in fields if row[field]]
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, csv.Error) as exc:
            raise VisualizationDataError("数据源读取校验未通过，请在数据源管理中检查字段与记录。") from exc
        options = {
            "channel": [{"value": value, "label": value} for value in sorted({row["channel"] for row in all_leads})],
            "content": [{"value": row["content_id_hash"], "label": f"内容 {index + 1:03d}"} for index, row in enumerate(tables["short_video"])],
            "session": [{"value": value, "label": f"场次 {value}"} for value in sorted({row["直播场次"] for row in tables["live_session"]})],
        }
        for key in options:
            selected = getattr(filters, key)
            if selected is not None and selected not in {option["value"] for option in options[key]}:
                raise ValueError("筛选项不存在，请重置筛选后重试。")
        content_clicks = {row["click_id_hash"] for row in tables["short_video"] if row["content_id_hash"] == filters.content}
        session_leads = {row["用户ID"] for row in tables["live_session"] if row["直播场次"] == filters.session}
        selected_leads = [row for row in all_leads
            if (not filters.date_from or moment(row["created_at"]).date() >= filters.date_from)
            and (not filters.date_to or moment(row["created_at"]).date() <= filters.date_to)
            and (not filters.channel or row["channel"] == filters.channel)
            and (not filters.content or row["click_id_hash"] in content_clicks)
            and (not filters.session or row["lead_id_hash"] in session_leads)]
        lead_ids = {row["lead_id_hash"] for row in selected_leads}
        clicks = {row["click_id_hash"] for row in selected_leads}
        selected = {
            "channel_lead": selected_leads,
            "short_video": [row for row in tables["short_video"] if row["click_id_hash"] in clicks],
            "live_session": [row for row in tables["live_session"] if row["用户ID"] in lead_ids and (not filters.session or row["直播场次"] == filters.session)],
            "sales_followup": [row for row in tables["sales_followup"] if row["lead_id_hash"] in lead_ids],
            "order": [row for row in tables["order"] if row["lead_id_hash"] in lead_ids],
        }
        return selected, {
            "source_id": filters.source_id, "source_name": "电商运营数据", "source_type": "本地 CSV",
            "synthetic": True, "data_updated_at": datetime.fromtimestamp(max(modified), timezone.utc).isoformat(),
            "observed_through": max(observed).isoformat(), "date_min": min(dates), "date_max": max(dates),
            "filters": filters, "options": options,
        }

    def snapshot(self, filters: VisualizationFilters) -> VisualizationSnapshot:
        tables, metadata = self.load(filters)
        leads, orders = tables["channel_lead"], tables["order"]
        paid = [row for row in orders if row["order_status"] in PAID]
        paid_leads = {row["lead_id_hash"] for row in paid}
        follows = {row["lead_id_hash"]: row for row in tables["sales_followup"]}
        timely = {key for key, row in follows.items() if (hours := followup_hours(row)) is not None and 0 <= hours <= 24}
        n = len(leads)
        metrics = [
            ("gmv", "有效付款金额", amount(orders), "currency", "订单状态为已付款或已完成的金额合计；待付款和已取消不计入。"),
            ("paid_orders", "有效付款订单", len(paid), "number", "按订单编号去重，统计已付款与已完成订单。"),
            ("leads", "线索数量", n, "number", "按线索编号去重，包含无效线索与无跟进记录的线索。"),
            ("paid_conversion", "付款转化率", ratio(len(paid_leads), n), "percent", "有有效付款订单的去重线索数 ÷ 全部筛选线索数。"),
            ("followup_24h", "24小时首跟进率", ratio(len(timely), n), "percent", "首次跟进距分配时间0至24小时的线索数 ÷ 全部筛选线索数；无记录计入分母。"),
        ]
        charts = []

        def chart(key, title, description, kind, detail, series, rows):
            charts.append(VisualizationChart(
                key=key, title=title, description=description, kind=kind, detail=detail,
                series=[{"key": field, "label": label, "color": color} for field, label, color in series], rows=rows,
            ))

        daily = defaultdict(list)
        for row in paid:
            daily[moment(row["paid_at"]).date()].append(row)
        trend = []
        if daily:
            day = min(daily)
            while day <= max(daily):
                trend.append({"label": day.isoformat(), "gmv": amount(daily[day])})
                day += timedelta(days=1)
        chart("sales", "付款金额趋势", "按实际付款日期统计所选线索的后续订单，金额单位：元。", "line", "orders", [("gmv", "付款金额", "#16745a")], trend)
        content = tables["short_video"]
        chart("content", "内容转化路径", "关联内容全量曝光与点击为次数，线索为去重人数；用于观察路径规模。", "funnel", "content", [("value", "数量", "#16745a")], [
            {"label": "内容曝光", "value": sum(int(row["impressions"]) for row in content)},
            {"label": "内容点击", "value": sum(int(row["clicks"]) for row in content)},
            {"label": "关联线索", "value": n},
        ])
        channels = []
        for channel in sorted({row["channel"] for row in leads}):
            ids = {row["lead_id_hash"] for row in leads if row["channel"] == channel}
            channels.append({"label": channel, "leads": len(ids), "timely": len(ids & timely), "paid": len(ids & paid_leads)})
        chart("channels", "渠道承接对比", "渠道以线索入库渠道为准；对比人数，不代表增量归因。", "bar", "leads", [("leads", "线索", "#9abfb0"), ("timely", "24小时首跟进", "#16745a"), ("paid", "付款线索", "#d29340")], channels)
        sessions = []
        for session in sorted({row["直播场次"] for row in tables["live_session"]}):
            rows = [row for row in tables["live_session"] if row["直播场次"] == session]
            sessions.append({"label": f"场次 {session}", "registered": len(rows), "attended": sum(row["是否到课"] == "是" for row in rows), "ordered": sum(row["是否购买课程"] == "是" for row in rows)})
        chart("live", "直播场次转化", "按用户×场次去重。购买为直播表行为标记，与订单实付口径独立。", "bar", "live", [("registered", "预约人数", "#9abfb0"), ("attended", "到课人数", "#16745a"), ("ordered", "购买人数", "#d29340")], sessions)
        buckets = Counter(bucket(followup_hours(follows.get(row["lead_id_hash"]))) for row in leads)
        chart("followups", "首次跟进时效", "从线索分配起计时。无首跟进记录单独展示。", "bar", "followups", [("value", "线索数", "#16745a")], [{"label": label, "value": buckets[label]} for label in ["1小时内", "1–24小时", "超过24小时", "无首跟进记录", "时间异常"]])
        statuses = Counter(row["order_status"] for row in orders)
        chart("orders", "订单状态分布", "所有关联订单按当前状态分组；只有已付款、已完成计入付款金额。", "bar", "orders", [("value", "订单数", "#16745a")], [{"label": label, "value": statuses[key]} for key, label in ORDER_LABELS.items()])
        return VisualizationSnapshot(
            **metadata, selected_leads=n,
            metrics=[VisualizationMetric(key=key, label=label, value=value, format=fmt, definition=definition) for key, label, value, fmt, definition in metrics],
            charts=charts, notices=[
                "日期筛选依据线索创建时间；后续跟进、直播行为与订单统计截至数据快照，不按创建日期截断。",
                "内容与渠道、场次筛选取交集。内容曝光与点击为关联内容的完整计数，不能解释为所选渠道独占流量。",
                "直播表提供预约时间，未提供真实开播时间；按场次比较，不生成开播时间趋势。场次关联订单不代表直播促成的订单。",
                "当前数据为合成测试数据；所有指标由数据记录计算，金额为人民币。",
            ],
        )

    def details(self, filters: VisualizationFilters, dataset: DetailKind, offset: int = 0, limit: int = 50) -> VisualizationDetails:
        tables, _ = self.load(filters)
        leads = {row["lead_id_hash"]: row for row in tables["channel_lead"]}
        orders = defaultdict(list)
        for row in tables["order"]:
            orders[row["lead_id_hash"]].append(row)
        follows = {row["lead_id_hash"]: row for row in tables["sales_followup"]}
        rows = []
        if dataset == "content":
            clicks = Counter(row["click_id_hash"] for row in leads.values())
            rows = [{"reference": row["content_id_hash"], "published_at": row["published_at"], "impressions": int(row["impressions"]), "clicks": int(row["clicks"]), "leads": clicks[row["click_id_hash"]]} for row in tables["short_video"]]
        elif dataset == "live":
            rows = [{"reference": row["用户ID"], "session": row["直播场次"], "reserved_at": row["预约时间"], "attended": row["是否到课"], "ordered": row["是否购买课程"]} for row in tables["live_session"]]
        elif dataset == "leads":
            rows = [{"reference": key, "channel": row["channel"], "created_at": row["created_at"], "paid_orders": sum(item["order_status"] in PAID for item in orders[key]), "gmv": amount(orders[key])} for key, row in leads.items()]
        elif dataset == "followups":
            for key, row in leads.items():
                follow = follows.get(key, {})
                hours = followup_hours(follow)
                rows.append({"reference": key, "channel": row["channel"], "assigned_at": follow.get("assigned_at"), "first_followup_at": follow.get("first_followup_at"), "hours": round(hours, 2) if hours is not None else None, "bucket": bucket(hours)})
        else:
            rows = [{"reference": row["order_id_hash"], "lead": row["lead_id_hash"], "channel": leads[row["lead_id_hash"]]["channel"], "ordered_at": row["ordered_at"], "paid_at": row["paid_at"] or None, "status": ORDER_LABELS[row["order_status"]], "gmv": amount([row])} for row in tables["order"]]
        return VisualizationDetails(dataset=dataset, columns=[DetailColumn(key=key, label=label) for key, label in COLUMNS[dataset]], rows=rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)

    def export_csv(self, filters: VisualizationFilters, dataset: DetailKind) -> bytes:
        data = self.details(filters, dataset, limit=10**9)
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow([column.label for column in data.columns])
        for row in data.rows:
            values = [row[column.key] for column in data.columns]
            writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
        return stream.getvalue().encode("utf-8-sig")
