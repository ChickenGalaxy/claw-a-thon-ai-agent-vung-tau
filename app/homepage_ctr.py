# ============================================================================ #
# [DISABLED MODULE] Sinh HÌNH % CTR cho từng sản phẩm trên màn hình Home.
# Tạm thời KHÔNG dùng nữa — không module nào import file này.
# Nó phụ thuộc các config ảnh đã được comment trong app/config.py
# (ASSET_DIR, RESULTS_DIR, HOMEPAGE_RESULT_IMAGE, HOMEPAGE_LAYOUT_PATH,
#  HOMEPAGE_RESULT_IMAGE_URL). Muốn bật lại tính năng hình: khôi phục các
# config đó, mở lại import + khối homepage_context trong app/agent.py,
# và 2 route /assets, /results trong app/routes.py.
# ============================================================================ #
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.dataset as pyarrow_dataset
from PIL import Image, ImageDraw, ImageFont

from .config import ASSET_DIR, HOMEPAGE_LAYOUT_PATH, HOMEPAGE_RESULT_IMAGE, HOMEPAGE_RESULT_IMAGE_URL, PARQUET_PATH, RESULTS_DIR
from .storage import safe_filename


def load_homepage_layout() -> dict[str, Any]:
    fallback = {
        "template": HOMEPAGE_RESULT_IMAGE.name,
        "font_size": 26,
        "text_color": [255, 0, 0],
        "items": [],
    }
    try:
        layout = json.loads(HOMEPAGE_LAYOUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    if not isinstance(layout, dict):
        return fallback
    if not isinstance(layout.get("items"), list):
        layout["items"] = []
    return {**fallback, **layout}


def homepage_layout_items() -> list[dict[str, Any]]:
    return [item for item in load_homepage_layout().get("items", []) if isinstance(item, dict)]


def font_for_homepage_image(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def extract_ymd_range(message: str) -> tuple[int | None, int | None, str]:
    normalized = message.lower()
    month_match = re.search(r"(?:tháng|thang|month)\s*(\d{1,2})\s*[/\-\s]\s*(20\d{2})", normalized)
    if month_match:
        month = int(month_match.group(1))
        year = int(month_match.group(2))
        if 1 <= month <= 12:
            next_month = datetime(year + (month // 12), (month % 12) + 1, 1)
            end_day = (next_month - datetime.resolution).day
            return year * 10000 + month * 100 + 1, year * 10000 + month * 100 + end_day, f"tháng {month:02d}/{year}"

    compact_match = re.search(r"\b(20\d{2})(\d{2})\b", normalized)
    if compact_match:
        year = int(compact_match.group(1))
        month = int(compact_match.group(2))
        if 1 <= month <= 12:
            next_month = datetime(year + (month // 12), (month % 12) + 1, 1)
            end_day = (next_month - datetime.resolution).day
            return year * 10000 + month * 100 + 1, year * 10000 + month * 100 + end_day, f"tháng {month:02d}/{year}"

    return None, None, "toàn bộ dữ liệu"


def ymd_in_range(value: Any, start_ymd: int | None, end_ymd: int | None) -> bool:
    if start_ymd is None or end_ymd is None:
        return True
    try:
        ymd_value = int(value)
    except Exception:
        return False
    return start_ymd <= ymd_value <= end_ymd


def calculate_homepage_click_rates(start_ymd: int | None = None, end_ymd: int | None = None) -> list[dict[str, Any]]:
    dataset = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet")
    table = dataset.to_table(columns=["event_id", "user_id", "app_profile_name", "ymd"])
    event_ids = table["event_id"].to_pylist()
    user_ids = table["user_id"].to_pylist()
    names = table["app_profile_name"].to_pylist()
    ymd_values = table["ymd"].to_pylist()

    home_users: set[str] = set()
    clicked_by_service: dict[str, set[str]] = {}
    for event_id, user_id, service_name, ymd_value in zip(event_ids, user_ids, names, ymd_values):
        if not user_id or not ymd_in_range(ymd_value, start_ymd, end_ymd):
            continue
        if event_id in {"AAAA.005", "01.1005.005"}:
            home_users.add(user_id)
        if event_id in {"AAAA.020", "01.1005.020"} and service_name:
            clicked_by_service.setdefault(str(service_name), set()).add(user_id)

    denominator = max(len(home_users), 1)
    rows = []
    for service_name, users in clicked_by_service.items():
        clicked_users = len(users)
        rows.append(
            {
                "service": service_name,
                "clicked_users": clicked_users,
                "home_users": len(home_users),
                "click_rate_pct": round(clicked_users / denominator * 100, 2),
            }
        )
    return sorted(rows, key=lambda row: row["click_rate_pct"], reverse=True)


def is_red_annotation(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 120 and green < 235 and blue < 235 and red > green + 20 and red > blue + 20


def scrub_old_homepage_red_values(image: Image.Image) -> None:
    width, height = image.size
    pixels = image.load()
    for item in homepage_layout_items():
        x = int(item["x"])
        y = int(item["y"])
        fill_color = (248, 252, 255) if y < 700 else (255, 255, 255)
        arrow_left = max(0, x + 55)
        arrow_top = max(0, y + 18)
        arrow_right = min(width - 1, x + 100)
        arrow_bottom = min(height - 1, y + 44)
        for pixel_y in range(arrow_top, arrow_bottom + 1):
            for pixel_x in range(arrow_left, arrow_right + 1):
                pixels[pixel_x, pixel_y] = fill_color

        left = max(0, x - 45)
        top = max(0, y - 12)
        right = min(width - 1, x + 115)
        bottom = min(height - 1, y + 70)
        for pixel_y in range(top, bottom + 1):
            for pixel_x in range(left, right + 1):
                if is_red_annotation(pixels[pixel_x, pixel_y]):
                    pixels[pixel_x, pixel_y] = fill_color


def render_homepage_click_rate_image(job_id: str, click_rates: list[dict[str, Any]]) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    layout = load_homepage_layout()
    rates_by_service = {row["service"]: row for row in click_rates}
    template_path = ASSET_DIR / str(layout.get("template") or HOMEPAGE_RESULT_IMAGE.name)
    image = Image.open(template_path).convert("RGB")
    scrub_old_homepage_red_values(image)
    draw = ImageDraw.Draw(image)
    font = font_for_homepage_image(int(layout.get("font_size") or 26))
    red = tuple(layout.get("text_color") or [255, 0, 0])

    for item in homepage_layout_items():
        aliases = item.get("aliases") or [item.get("label")]
        row = next((rates_by_service.get(alias) for alias in aliases if rates_by_service.get(alias)), None)
        value = f"{row['click_rate_pct']:.2f}%" if row else "0.00%"
        draw.text((int(item["x"]), int(item["y"])), value, fill=red, font=font)

    filename = f"homepage_click_rate_{safe_filename(job_id)}.png"
    output_path = RESULTS_DIR / filename
    image.save(output_path, "PNG")
    return f"/results/{filename}"


def homepage_click_rate_context(job_id: str, message: str) -> dict[str, Any]:
    start_ymd, end_ymd, period_label = extract_ymd_range(message)
    click_rates = calculate_homepage_click_rates(start_ymd, end_ymd)
    image_url = render_homepage_click_rate_image(job_id, click_rates)
    date_filter_sql = ""
    if start_ymd and end_ymd:
        date_filter_sql = f"\n    AND ymd BETWEEN {start_ymd} AND {end_ymd}"
    return {
        "image_url": image_url,
        "period": period_label,
        "start_ymd": start_ymd,
        "end_ymd": end_ymd,
        "image_layout": {
            "source": str(HOMEPAGE_LAYOUT_PATH),
            "value_policy": "percent values are calculated from data at runtime, then mapped to template positions by service aliases",
        },
        "rows": click_rates[:30],
        "sql": f"""WITH home_users AS (
  SELECT COUNT(DISTINCT user_id) AS total_home_users
  FROM event_log
  WHERE event_id = 'AAAA.005'{date_filter_sql}
),
icon_clicks AS (
  SELECT app_profile_name, COUNT(DISTINCT user_id) AS clicked_users
  FROM event_log
  WHERE event_id = 'AAAA.020'{date_filter_sql}
  GROUP BY app_profile_name
)
SELECT app_profile_name,
       clicked_users,
       total_home_users,
       ROUND(clicked_users * 100.0 / total_home_users, 2) AS click_rate_pct
FROM icon_clicks
CROSS JOIN home_users
ORDER BY click_rate_pct DESC;""",
        "python": f"""click_rates = calculate_homepage_click_rates(start_ymd={start_ymd!r}, end_ymd={end_ymd!r})
image_url = render_homepage_click_rate_image(job_id, click_rates)""",
    }


def is_homepage_click_rate_question(message: str) -> bool:
    normalized = message.lower()
    click_terms = ("click rate", "ctr", "tỉ lệ lượt click", "tỷ lệ lượt click", "ti le luot click", "ty le luot click")
    home_terms = ("home page", "homepage", "trang chủ", "trang chu", "trang home")
    return any(term in normalized for term in click_terms) and any(term in normalized for term in home_terms)


def attach_homepage_result_image(answer: str, message: str, image_url: str | None = None) -> str:
    if not is_homepage_click_rate_question(message):
        return answer
    result_url = image_url or HOMEPAGE_RESULT_IMAGE_URL
    answer = re.sub(r"!\[[^\]]*\]\(/(?:assets|results)/homepage[^)]*\.png\)", "", answer).strip()
    image_markdown = f"![Home Page click-rate result]({result_url})"
    if result_url in answer:
        return answer
    return f"{answer.rstrip()}\n\n{image_markdown}"
