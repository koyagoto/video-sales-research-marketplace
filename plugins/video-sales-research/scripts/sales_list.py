#!/usr/bin/env python3
"""Manage user-scoped video sales prospects and append-only activity history."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
import unicodedata
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit


PROSPECT_FILENAME = "営業リスト.csv"
ACTIVITY_FILENAME = "営業活動履歴.csv"

PROSPECT_HEADERS = [
    "企業ID",
    "企業名",
    "公式サイトURL",
    "募集・応募URL",
    "初回確認日",
    "最終確認日",
    "適合度",
    "証拠充足率",
    "判断区分",
    "進捗状態",
    "次の行動",
    "送信日",
    "返信日",
    "面談日",
    "提案日",
    "受注日",
    "失注日",
    "除外日",
    "除外理由",
    "担当者",
    "メモ",
    "更新日時",
]

ACTIVITY_HEADERS = [
    "活動ID",
    "企業ID",
    "企業名",
    "活動種別",
    "活動日",
    "内容",
    "記録日時",
]

VALID_STATES = {
    "候補",
    "準備中",
    "送信済み",
    "返信あり",
    "面談",
    "提案",
    "受注",
    "失注",
    "保留",
    "除外",
}

EVENT_ALIASES = {
    "candidate": "候補登録",
    "候補": "候補登録",
    "候補登録": "候補登録",
    "research": "再調査",
    "再調査": "再調査",
    "contact": "送信",
    "contacted": "送信",
    "送信": "送信",
    "応募": "送信",
    "問い合わせ": "送信",
    "reply": "返信",
    "replied": "返信",
    "返信": "返信",
    "meeting": "面談",
    "面談": "面談",
    "proposal": "提案",
    "提案": "提案",
    "won": "受注",
    "受注": "受注",
    "lost": "失注",
    "失注": "失注",
    "hold": "保留",
    "保留": "保留",
    "excluded": "除外",
    "除外": "除外",
    "note": "メモ",
    "メモ": "メモ",
}

STATE_BY_EVENT = {
    "候補登録": "候補",
    "送信": "送信済み",
    "返信": "返信あり",
    "面談": "面談",
    "提案": "提案",
    "受注": "受注",
    "失注": "失注",
    "保留": "保留",
    "除外": "除外",
}

DATE_FIELD_BY_EVENT = {
    "送信": "送信日",
    "返信": "返信日",
    "面談": "面談日",
    "提案": "提案日",
    "受注": "受注日",
    "失注": "失注日",
    "除外": "除外日",
}

DATE_FIELDS = {
    "初回確認日",
    "最終確認日",
    "送信日",
    "返信日",
    "面談日",
    "提案日",
    "受注日",
    "失注日",
    "除外日",
}


class SalesListError(RuntimeError):
    pass


def now_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def normalize_company(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return re.sub(r"[\s\u3000]+", "", text)


def normalize_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    scheme = parsed.scheme.casefold()
    netloc = parsed.netloc.casefold()
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def data_paths(raw_dir: str) -> Tuple[Path, Path, Path]:
    data_dir = Path(raw_dir).expanduser().resolve()
    plugin_root = Path(__file__).resolve().parents[1]
    if data_dir == plugin_root or is_inside(data_dir, plugin_root):
        raise SalesListError(
            "営業データはプラグイン内に保存できません。利用者の作業フォルダを指定してください。"
        )
    return data_dir, data_dir / PROSPECT_FILENAME, data_dir / ACTIVITY_FILENAME


def atomic_write(path: Path, headers: Sequence[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=list(headers), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})
        os.replace(str(temporary), str(path))
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def read_rows(path: Path, expected_headers: Sequence[str]) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            actual = reader.fieldnames or []
            if actual != list(expected_headers):
                raise SalesListError(
                    f"{path.name}の列構成が一致しません。自動上書きせず確認を停止しました。"
                )
            return [dict(row) for row in reader]
    except UnicodeDecodeError as exc:
        raise SalesListError(f"{path.name}をUTF-8として読み取れません。") from exc


def ensure_files(raw_dir: str) -> Tuple[Path, Path, Path]:
    data_dir, prospects_path, activities_path = data_paths(raw_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if prospects_path.exists():
        read_rows(prospects_path, PROSPECT_HEADERS)
    else:
        atomic_write(prospects_path, PROSPECT_HEADERS, [])
    if activities_path.exists():
        read_rows(activities_path, ACTIVITY_HEADERS)
    else:
        atomic_write(activities_path, ACTIVITY_HEADERS, [])
    return data_dir, prospects_path, activities_path


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def empty_prospect() -> Dict[str, str]:
    return {header: "" for header in PROSPECT_HEADERS}


def find_matches(
    prospects: Sequence[Dict[str, str]],
    company: str = "",
    company_id: str = "",
    official_url: str = "",
) -> List[int]:
    if company_id:
        return [index for index, row in enumerate(prospects) if row["企業ID"] == company_id]
    normalized_official_url = normalize_url(official_url)
    if normalized_official_url:
        url_matches = [
            index
            for index, row in enumerate(prospects)
            if normalize_url(row["公式サイトURL"]) == normalized_official_url
        ]
        if url_matches:
            return url_matches
    normalized_name = normalize_company(company)
    if normalized_name:
        return [
            index
            for index, row in enumerate(prospects)
            if normalize_company(row["企業名"]) == normalized_name
        ]
    return []


def validate_percentage(value: str, label: str) -> None:
    if value == "":
        return
    try:
        number = int(value)
    except ValueError as exc:
        raise SalesListError(f"{label}は0から100の整数で指定してください。") from exc
    if number < 0 or number > 100:
        raise SalesListError(f"{label}は0から100の範囲で指定してください。")


def validate_date(value: str, label: str) -> None:
    if value == "":
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SalesListError(f"{label}はYYYY-MM-DD形式で指定してください。") from exc


def append_activity(
    activities: List[Dict[str, str]],
    prospect: Dict[str, str],
    event_type: str,
    activity_date: str,
    note: str,
) -> Dict[str, str]:
    activity = {
        "活動ID": new_id("act"),
        "企業ID": prospect["企業ID"],
        "企業名": prospect["企業名"],
        "活動種別": event_type,
        "活動日": activity_date,
        "内容": note,
        "記録日時": now_timestamp(),
    }
    activities.append(activity)
    return activity


def command_init(args: argparse.Namespace) -> Dict[str, object]:
    data_dir, prospects_path, activities_path = ensure_files(args.dir)
    return {
        "result": "initialized",
        "data_dir": str(data_dir),
        "files": [str(prospects_path), str(activities_path)],
    }


def command_upsert(args: argparse.Namespace) -> Dict[str, object]:
    if not args.company.strip():
        raise SalesListError("企業名は必須です。")
    validate_percentage(args.score, "適合度")
    validate_percentage(args.evidence, "証拠充足率")
    validate_date(args.checked_date, "確認日")
    if args.status and args.status not in VALID_STATES:
        raise SalesListError(f"進捗状態が不正です: {args.status}")

    _, prospects_path, activities_path = ensure_files(args.dir)
    prospects = read_rows(prospects_path, PROSPECT_HEADERS)
    activities = read_rows(activities_path, ACTIVITY_HEADERS)
    matches = find_matches(prospects, company=args.company, official_url=args.official_url)
    if len(matches) > 1:
        raise SalesListError("同一候補が複数見つかりました。企業IDを確認してから更新してください。")

    created = not matches
    if created:
        row = empty_prospect()
        row["企業ID"] = new_id("cmp")
        row["企業名"] = args.company.strip()
        row["進捗状態"] = args.status or "候補"
        row["初回確認日"] = args.checked_date
        prospects.append(row)
    else:
        row = prospects[matches[0]]

    updates = {
        "企業名": args.company,
        "公式サイトURL": args.official_url,
        "募集・応募URL": args.opportunity_url,
        "最終確認日": args.checked_date,
        "適合度": args.score,
        "証拠充足率": args.evidence,
        "判断区分": args.decision,
        "進捗状態": args.status,
        "次の行動": args.next_action,
        "担当者": args.owner,
        "メモ": args.note,
    }
    changed_fields: List[str] = []
    for field, raw_value in updates.items():
        value = (raw_value or "").strip()
        if value and row.get(field, "") != value:
            row[field] = value
            changed_fields.append(field)
    if created and args.checked_date:
        row["最終確認日"] = args.checked_date
    row["更新日時"] = now_timestamp()

    event_type = "候補登録" if created else "再調査"
    activity_date = args.checked_date or today_iso()
    activity_note = args.note or ("営業候補を登録" if created else "候補情報を更新")
    activity = append_activity(activities, row, event_type, activity_date, activity_note)
    atomic_write(prospects_path, PROSPECT_HEADERS, prospects)
    atomic_write(activities_path, ACTIVITY_HEADERS, activities)
    return {
        "result": "created" if created else "updated",
        "company_id": row["企業ID"],
        "company": row["企業名"],
        "changed_fields": changed_fields,
        "activity_id": activity["活動ID"],
    }


def canonical_event_type(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    event_type = EVENT_ALIASES.get(normalized)
    if not event_type:
        raise SalesListError(f"活動種別が不正です: {value}")
    return event_type


def command_event(args: argparse.Namespace) -> Dict[str, object]:
    event_type = canonical_event_type(args.type)
    validate_date(args.date, "活動日")
    if event_type == "除外" and not args.reason.strip():
        raise SalesListError("除外には理由を指定してください。")

    _, prospects_path, activities_path = ensure_files(args.dir)
    prospects = read_rows(prospects_path, PROSPECT_HEADERS)
    activities = read_rows(activities_path, ACTIVITY_HEADERS)
    matches = find_matches(prospects, company=args.company, company_id=args.company_id)
    if not matches:
        raise SalesListError("対象企業が営業リストに見つかりません。先に候補を登録してください。")
    if len(matches) > 1:
        raise SalesListError("対象企業が複数見つかりました。企業IDを指定してください。")
    row = prospects[matches[0]]
    activity_date = args.date or today_iso()

    if event_type in STATE_BY_EVENT:
        row["進捗状態"] = STATE_BY_EVENT[event_type]
    date_field = DATE_FIELD_BY_EVENT.get(event_type)
    if date_field:
        row[date_field] = activity_date
    if args.next_action.strip():
        row["次の行動"] = args.next_action.strip()
    if args.owner.strip():
        row["担当者"] = args.owner.strip()
    if args.note.strip():
        row["メモ"] = args.note.strip()
    if event_type == "除外":
        row["除外理由"] = args.reason.strip()
    row["更新日時"] = now_timestamp()

    note_parts = [part for part in [args.note.strip(), args.reason.strip()] if part]
    activity = append_activity(activities, row, event_type, activity_date, " / ".join(note_parts))
    atomic_write(prospects_path, PROSPECT_HEADERS, prospects)
    atomic_write(activities_path, ACTIVITY_HEADERS, activities)
    return {
        "result": "recorded",
        "company_id": row["企業ID"],
        "company": row["企業名"],
        "event": event_type,
        "activity_date": activity_date,
        "status": row["進捗状態"],
        "activity_id": activity["活動ID"],
    }


def last_activity_by_company(activities: Sequence[Dict[str, str]]) -> Dict[str, str]:
    latest: Dict[str, str] = {}
    for row in activities:
        value = row.get("活動日", "")
        company_id = row.get("企業ID", "")
        if value and (company_id not in latest or value > latest[company_id]):
            latest[company_id] = value
    return latest


def command_list(args: argparse.Namespace) -> Dict[str, object]:
    _, prospects_path, activities_path = ensure_files(args.dir)
    prospects = read_rows(prospects_path, PROSPECT_HEADERS)
    activities = read_rows(activities_path, ACTIVITY_HEADERS)
    latest = last_activity_by_company(activities)
    rows = []
    for row in prospects:
        if args.status and row["進捗状態"] != args.status:
            continue
        rows.append(
            {
                "企業ID": row["企業ID"],
                "企業名": row["企業名"],
                "適合度": row["適合度"],
                "証拠充足率": row["証拠充足率"],
                "判断区分": row["判断区分"],
                "進捗状態": row["進捗状態"],
                "最終活動日": latest.get(row["企業ID"], ""),
                "次の行動": row["次の行動"],
            }
        )
    return {"result": "ok", "count": len(rows), "prospects": rows}


def companies_with_event(
    prospects: Sequence[Dict[str, str]],
    activities: Sequence[Dict[str, str]],
    event_type: str,
    date_field: str = "",
) -> set:
    ids = {row["企業ID"] for row in activities if row["活動種別"] == event_type}
    if date_field:
        ids.update(row["企業ID"] for row in prospects if row.get(date_field, ""))
    return ids


def percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 1)


def command_summary(args: argparse.Namespace) -> Dict[str, object]:
    _, prospects_path, activities_path = ensure_files(args.dir)
    prospects = read_rows(prospects_path, PROSPECT_HEADERS)
    activities = read_rows(activities_path, ACTIVITY_HEADERS)
    status_counts = {state: 0 for state in sorted(VALID_STATES)}
    for row in prospects:
        status = row.get("進捗状態", "")
        if status in status_counts:
            status_counts[status] += 1

    contacted = companies_with_event(prospects, activities, "送信", "送信日")
    replied = companies_with_event(prospects, activities, "返信", "返信日")
    meetings = companies_with_event(prospects, activities, "面談", "面談日")
    proposals = companies_with_event(prospects, activities, "提案", "提案日")
    won = companies_with_event(prospects, activities, "受注", "受注日")
    lost = companies_with_event(prospects, activities, "失注", "失注日")
    excluded = companies_with_event(prospects, activities, "除外", "除外日")
    counts = {
        "登録企業数": len(prospects),
        "候補数": status_counts["候補"],
        "準備中企業数": status_counts["準備中"],
        "送信済み企業数": len(contacted),
        "返信企業数": len(replied),
        "面談企業数": len(meetings),
        "提案企業数": len(proposals),
        "受注企業数": len(won),
        "失注企業数": len(lost),
        "保留企業数": status_counts["保留"],
        "除外企業数": len(excluded),
    }
    rates = {
        "返信率": percentage(len(replied), len(contacted)),
        "面談化率": percentage(len(meetings), len(contacted)),
        "受注率": percentage(len(won), len(contacted)),
    }
    return {"result": "ok", "counts": counts, "rates_percent": rates}


def collect_validation_issues(
    prospects: Sequence[Dict[str, str]], activities: Sequence[Dict[str, str]]
) -> List[str]:
    issues: List[str] = []
    seen_ids: Dict[str, int] = {}
    seen_urls: Dict[str, str] = {}
    for index, row in enumerate(prospects, start=2):
        company_id = row.get("企業ID", "")
        if not company_id:
            issues.append(f"営業リスト{index}行目: 企業IDがありません。")
        elif company_id in seen_ids:
            issues.append(f"営業リスト{index}行目: 企業IDが重複しています。")
        else:
            seen_ids[company_id] = index
        if not row.get("企業名", "").strip():
            issues.append(f"営業リスト{index}行目: 企業名がありません。")
        normalized = normalize_url(row.get("公式サイトURL", ""))
        if normalized:
            if normalized in seen_urls:
                issues.append(
                    f"営業リスト{index}行目: 公式サイトURLが{seen_urls[normalized]}と重複しています。"
                )
            else:
                seen_urls[normalized] = f"{seen_ids.get(company_id, index)}行目"
        for field in ("適合度", "証拠充足率"):
            try:
                validate_percentage(row.get(field, ""), field)
            except SalesListError as exc:
                issues.append(f"営業リスト{index}行目: {exc}")
        state = row.get("進捗状態", "")
        if state and state not in VALID_STATES:
            issues.append(f"営業リスト{index}行目: 不正な進捗状態です: {state}")
        for field in DATE_FIELDS:
            try:
                validate_date(row.get(field, ""), field)
            except SalesListError as exc:
                issues.append(f"営業リスト{index}行目: {exc}")

    known_ids = set(seen_ids)
    seen_activity_ids = set()
    for index, row in enumerate(activities, start=2):
        activity_id = row.get("活動ID", "")
        if not activity_id:
            issues.append(f"営業活動履歴{index}行目: 活動IDがありません。")
        elif activity_id in seen_activity_ids:
            issues.append(f"営業活動履歴{index}行目: 活動IDが重複しています。")
        seen_activity_ids.add(activity_id)
        if row.get("企業ID", "") not in known_ids:
            issues.append(f"営業活動履歴{index}行目: 対応する企業IDがありません。")
        try:
            validate_date(row.get("活動日", ""), "活動日")
        except SalesListError as exc:
            issues.append(f"営業活動履歴{index}行目: {exc}")
    return issues


def command_validate(args: argparse.Namespace) -> Dict[str, object]:
    _, prospects_path, activities_path = data_paths(args.dir)
    missing = [
        path.name
        for path in (prospects_path, activities_path)
        if not path.exists()
    ]
    if missing:
        issues = [
            f"{name}が見つかりません。新規作成せず確認を停止しました。"
            for name in missing
        ]
        return {"result": "invalid", "issues": issues}
    prospects = read_rows(prospects_path, PROSPECT_HEADERS)
    activities = read_rows(activities_path, ACTIVITY_HEADERS)
    issues = collect_validation_issues(prospects, activities)
    return {"result": "valid" if not issues else "invalid", "issues": issues}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="映像営業調査の営業リストを管理します。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="空の営業リストを初期化")
    init_parser.add_argument("--dir", required=True, help="利用者が確認した営業データ保存先")
    init_parser.set_defaults(handler=command_init)

    upsert_parser = subparsers.add_parser("upsert", help="営業候補を追加または更新")
    upsert_parser.add_argument("--dir", required=True)
    upsert_parser.add_argument("--company", required=True)
    upsert_parser.add_argument("--official-url", default="")
    upsert_parser.add_argument("--opportunity-url", default="")
    upsert_parser.add_argument("--checked-date", default="")
    upsert_parser.add_argument("--score", default="")
    upsert_parser.add_argument("--evidence", default="")
    upsert_parser.add_argument("--decision", default="")
    upsert_parser.add_argument("--status", default="")
    upsert_parser.add_argument("--next-action", default="")
    upsert_parser.add_argument("--owner", default="")
    upsert_parser.add_argument("--note", default="")
    upsert_parser.set_defaults(handler=command_upsert)

    event_parser = subparsers.add_parser("event", help="営業活動を記録")
    event_parser.add_argument("--dir", required=True)
    event_parser.add_argument("--company", default="")
    event_parser.add_argument("--company-id", default="")
    event_parser.add_argument("--type", required=True)
    event_parser.add_argument("--date", default="")
    event_parser.add_argument("--note", default="")
    event_parser.add_argument("--reason", default="")
    event_parser.add_argument("--next-action", default="")
    event_parser.add_argument("--owner", default="")
    event_parser.set_defaults(handler=command_event)

    list_parser = subparsers.add_parser("list", help="営業リストを表示")
    list_parser.add_argument("--dir", required=True)
    list_parser.add_argument("--status", default="", choices=[""] + sorted(VALID_STATES))
    list_parser.set_defaults(handler=command_list)

    summary_parser = subparsers.add_parser("summary", help="営業状況を集計")
    summary_parser.add_argument("--dir", required=True)
    summary_parser.set_defaults(handler=command_summary)

    validate_parser = subparsers.add_parser("validate", help="営業リストの整合性を検証")
    validate_parser.add_argument("--dir", required=True)
    validate_parser.set_defaults(handler=command_validate)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SalesListError as exc:
        print(json.dumps({"result": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
