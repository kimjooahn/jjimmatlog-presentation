"""Collect public review data from the KakaoMap page for 이고집만두.

This script reads rendered review data and its public Vue component props. It
does not call Kakao APIs or attempt to bypass login, CAPTCHA, or access restrictions.
"""
from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

DEFAULT_PLACE_URL = "https://place.map.kakao.com/22319551#review"
DEFAULT_PLACE_NAME = "이고집만두"
DEFAULT_OUTPUT_NAME = "igojip-reviews.json"
MAX_REVIEWS = 100
MAX_SCROLLS = 40
MAX_STAGNANT_ROUNDS = 3
REVIEW_SELECTOR = ".section_review .list_review > li:has(.inner_review)"


def review_id(author: str, date: str, text: str) -> str:
    source = "|".join((author, date, text))
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def clean_reviewer_name(author: str) -> str:
    prefix = "리뷰어 이름,"
    return author.removeprefix(prefix).strip()


def normalize_review(review: dict, restaurant_id: str) -> None:
    reviewer_name = clean_reviewer_name(str(review.get("reviewer_name") or review.get("author", "")))
    reviewer_id = review.get("reviewer_id")
    review.update(
        {
            "reviewer_id": str(reviewer_id) if reviewer_id not in (None, "") else None,
            "reviewer_name": reviewer_name,
            "restaurant_id": restaurant_id,
            "review_text": review.get("review_text", review.get("text", "")),
            "review_date": review.get("review_date", review.get("date", "")),
            "has_photo": bool(review.get("has_photo", review.get("hasImage", False))),
        }
    )


def review_match_key(review: dict) -> tuple[str, str, str]:
    return (
        clean_reviewer_name(str(review.get("reviewer_name") or review.get("author", ""))),
        str(review.get("review_date") or review.get("date", "")).strip(),
        str(review.get("review_text") or review.get("text", "")).strip(),
    )


def merge_reviewer_ids(target_reviews: list[dict], source_reviews: list[dict]) -> int:
    ids_by_review = {
        review_match_key(review): str(review["reviewer_id"])
        for review in source_reviews
        if review.get("reviewer_id") not in (None, "")
    }
    matched = 0
    for review in target_reviews:
        if review.get("reviewer_id") not in (None, ""):
            continue
        reviewer_id = ids_by_review.get(review_match_key(review))
        if reviewer_id is not None:
            review["reviewer_id"] = reviewer_id
            matched += 1
    return matched


def parse_rating(values: list[str]) -> float:
    for value in values:
        try:
            rating = float(value.strip())
        except ValueError:
            continue
        if 1 <= rating <= 5:
            return rating
    return 0


def write_result(reviews: list[dict], place_name: str, place_id: str, place_url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for review in reviews:
        normalize_review(review, place_id)
    payload = {
        "restaurant": {
            "name": place_name,
            "kakaoPlaceId": place_id,
            "url": place_url,
        },
        "reviews": reviews[:MAX_REVIEWS],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def click_review_tab(page) -> None:
    tab = page.get_by_role("tab", name="후기", exact=True)
    if await tab.count() and await tab.get_attribute("aria-selected") != "true":
        await tab.click()
        await page.wait_for_timeout(800)


async def click_more_reviews(page) -> bool:
    buttons = page.locator(".section_review button")
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        label = (await button.inner_text()).strip()
        if "더보기" in label and await button.is_visible() and await button.is_enabled():
            await button.click()
            await page.wait_for_timeout(800)
            return True
    return False


async def reviewer_ids_from_vue(page) -> list[str | None]:
    return await page.evaluate(
        """() => {
            const root = document.querySelector('.container-doc')?._vnode;
            const idsByElement = new WeakMap();
            const visited = new Set();

            function visit(vnode, comment = null) {
                if (!vnode || typeof vnode !== 'object' || visited.has(vnode)) return;
                visited.add(vnode);
                if (vnode.type?.name === 'CommentReviewer' || vnode.type?.__name === 'CommentReviewer') {
                    comment = vnode.props?.comment || comment;
                }
                if (vnode.el instanceof Element && vnode.el.matches('.link_user')) {
                    const id = comment?.meta?.owner?.map_user_id;
                    idsByElement.set(vnode.el, id == null ? null : String(id));
                }
                if (vnode.component?.subTree) visit(vnode.component.subTree, comment);
                if (Array.isArray(vnode.children)) {
                    for (const child of vnode.children) visit(child, comment);
                }
            }

            visit(root);
            return Array.from(
                document.querySelectorAll('.section_review .list_review > li:has(.inner_review) .link_user'),
                element => idsByElement.get(element) ?? null
            );
        }"""
    )


async def extract_reviews(page, place_url: str) -> list[dict]:
    collected: dict[str, dict] = {}
    stagnant_rounds = 0
    previous_count = 0

    for scroll_number in range(MAX_SCROLLS + 1):
        reviewer_ids = await reviewer_ids_from_vue(page)
        cards = page.locator(REVIEW_SELECTOR)
        for index in range(await cards.count()):
            card = cards.nth(index)
            author_locator = card.locator(".link_user .name_user")
            text_locator = card.locator(".desc_review")
            if not await author_locator.count() or not await text_locator.count():
                continue
            try:
                author = await author_locator.evaluate(
                    "element => Array.from(element.childNodes)"
                    ".filter(node => node.nodeType === Node.TEXT_NODE)"
                    ".map(node => node.textContent).join('').trim()"
                )
                text = (await text_locator.text_content(timeout=3_000) or "").strip()
                date = (await card.locator(".txt_date").text_content(timeout=3_000) or "").strip()
                grade_values = await card.locator(".info_grade .screen_out").all_inner_texts()
            except PlaywrightTimeoutError:
                continue
            rating = parse_rating(grade_values)
            images = []
            image_locator = card.locator(".list_photo img.img_g")
            has_photo_element = await card.locator(".list_photo li").count() > 0
            for image_index in range(await image_locator.count()):
                image = image_locator.nth(image_index)
                try:
                    await image.scroll_into_view_if_needed(timeout=3_000)
                    await image.evaluate("element => element.complete || new Promise(resolve => element.addEventListener('load', resolve, {once: true}))")
                except PlaywrightTimeoutError:
                    pass
                sources = []
                for attribute in ("src", "data-src", "data-original", "data-lazy-src"):
                    value = (await image.get_attribute(attribute) or "").strip()
                    if value:
                        sources.append(value)
                srcset = (await image.get_attribute("srcset") or "").strip()
                if srcset:
                    sources.extend(part.split()[0] for part in srcset.split(",") if part.strip())
                for source in sources:
                    absolute_source = urljoin(place_url, source)
                    if absolute_source.startswith(("http://", "https://")) and absolute_source not in images:
                        images.append(absolute_source)
            identifier = review_id(author, date, text)
            if text and identifier not in collected:
                reviewer_id = reviewer_ids[index] if index < len(reviewer_ids) else None
                collected[identifier] = {
                    "id": identifier,
                    "reviewer_id": reviewer_id,
                    "reviewer_name": author,
                    "author": author,
                    "date": date,
                    "rating": rating,
                    "text": text,
                    "review_text": text,
                    "review_date": date,
                    "has_photo": bool(images) or has_photo_element,
                    "hasImage": bool(images) or has_photo_element,
                    "imageUrls": images,
                }

        count = min(len(collected), MAX_REVIEWS)
        if count != previous_count:
            print(f"현재 수집: {count}/{MAX_REVIEWS}", flush=True)
            previous_count = count
            stagnant_rounds = 0
        else:
            stagnant_rounds += 1

        if count >= MAX_REVIEWS:
            break

        loaded_more = await click_more_reviews(page)
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(900)
        if not loaded_more and stagnant_rounds >= MAX_STAGNANT_ROUNDS:
            break

    return list(collected.values())[:MAX_REVIEWS]


def find_reviews_by_reviewer_id(reviewer_id: str, data_directory: Path) -> list[dict]:
    matches = []
    for path in sorted(data_directory.glob("*-reviews.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        restaurant = payload.get("restaurant", {})
        for review in payload.get("reviews", []):
            if review.get("reviewer_id") == reviewer_id:
                matches.append(
                    {
                        **review,
                        "restaurant_id": review.get("restaurant_id") or restaurant.get("kakaoPlaceId"),
                    }
                )
    return matches


async def backfill_existing_reviewer_ids(data_directory: Path) -> None:
    for path in sorted(data_directory.glob("*-reviews.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        restaurant = payload.get("restaurant", {})
        place_url = restaurant.get("url")
        place_id = str(restaurant.get("kakaoPlaceId") or "")
        if not place_url or not place_id:
            print(f"건너뜀: {path.name}에 식당 URL 또는 ID가 없습니다.", flush=True)
            continue
        try:
            current_reviews = await collect(place_url)
        except Exception as error:
            print(f"수집 실패: {path.name}: {error}", flush=True)
            continue
        reviews = payload.get("reviews", [])
        matched = merge_reviewer_ids(reviews, current_reviews)
        for review in reviews:
            normalize_review(review, place_id)
        payload["reviews"] = reviews
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.name}: 기존 리뷰 {len(reviews)}개 중 {matched}개 reviewer_id 복원", flush=True)


async def collect(place_url: str) -> list[dict]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(locale="ko-KR", viewport={"width": 1440, "height": 1000})
        try:
            print("리뷰 수집 시작", flush=True)
            await page.goto(place_url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_load_state("networkidle", timeout=30_000)
            await click_review_tab(page)
            try:
                await page.locator(REVIEW_SELECTOR).first.wait_for(state="visible", timeout=15_000)
            except PlaywrightTimeoutError as error:
                body_text = await page.locator("body").inner_text()
                if any(word in body_text for word in ("CAPTCHA", "접근이 제한", "로그인")):
                    raise RuntimeError("카카오맵 접근 제한 또는 로그인 화면이 감지되어 수집을 중단했습니다.") from error
                raise RuntimeError("실제 리뷰 DOM을 찾지 못했습니다. 페이지 구조가 변경되었을 수 있습니다.") from error
            return await extract_reviews(page, place_url)
        finally:
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="카카오맵 공개 리뷰 DOM 수집기")
    parser.add_argument("--name", default=DEFAULT_PLACE_NAME, help="식당명")
    parser.add_argument("--url", default=DEFAULT_PLACE_URL, help="카카오맵 장소 리뷰 URL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_NAME, help="data 폴더에 저장할 JSON 파일명")
    parser.add_argument("--reviewer-id", help="저장된 리뷰에서 고유 reviewer_id로 리뷰 검색")
    parser.add_argument("--backfill-reviewer-ids", action="store_true", help="기존 리뷰를 다시 수집해 정확히 일치하는 항목의 reviewer_id를 복원")
    args = parser.parse_args()
    data_directory = Path(__file__).resolve().parents[1] / "data"
    if args.backfill_reviewer_ids:
        asyncio.run(backfill_existing_reviewer_ids(data_directory))
        return
    if args.reviewer_id is not None:
        reviews = find_reviews_by_reviewer_id(args.reviewer_id, data_directory)
        print(
            json.dumps(
                {
                    "reviewer_id": args.reviewer_id,
                    "review_count": len(reviews),
                    "reviews": reviews,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    place_id = args.url.split("/place.map.kakao.com/")[-1].split("#", 1)[0].strip("/")
    output_path = data_directory / args.output
    try:
        reviews = asyncio.run(collect(args.url))
    except Exception as error:
        print(f"수집 중단: {error}", flush=True)
        raise SystemExit(1) from error
    if output_path.exists():
        previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
        merge_reviewer_ids(reviews, previous_payload.get("reviews", []))
    write_result(reviews, args.name, place_id, args.url, output_path)
    print(f"수집 완료: {len(reviews)}개", flush=True)
    print(f"저장 위치: {output_path}", flush=True)


if __name__ == "__main__":
    main()
