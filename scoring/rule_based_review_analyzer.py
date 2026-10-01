"""Deterministic Korean review-text analysis with the shared text_analysis schema."""
from __future__ import annotations

import re
from dataclasses import dataclass

from scoring.content_scoring import ASPECTS


@dataclass(frozen=True)
class LexicalRule:
    pattern: re.Pattern[str]
    sentiment: str
    intensity: int


RAW_RULES = {
    "taste": {
        "positive": [
            (r"(?:정말|너무|진짜|완전|엄청|매우)\s*(?:맛있\w*|맛이\s*좋\w*)|최고(?:예요|다|네요)?|인생\s*맛집|존맛\w*|강력\s*추천|입에서\s*녹\w*", 3),
            (r"맛있\w*|맛집|맛이\s*좋\w*|고소\w*|담백\w*|진하\w*|풍미|육즙|쫄깃\w*|바삭\w*|촉촉\w*|부드럽\w*|감칠맛|식감이\s*좋\w*", 2),
            (r"맛(?:은|이)?\s*(?:괜찮\w*|나쁘지\s*않\w*)|나쁘지\s*않\w*", 1),
        ],
        "negative": [
            (r"(?:너무|정말|진짜|엄청)\s*(?:짜|싱겁|느끼하|밍밍)\w*|(?:너무|정말|진짜|엄청)?\s*(?:맛없\w*|최악\w*|다시는\s*(?:안|못)\s*(?:가|오|먹)\w*|돈\s*아깝\w*)", 3),
            (r"맛없\w*|별로(?:예요|다|였\w*|네요)?|싱겁\w*|짜(?:요|다|서|고|네요|지네요|네|게)|느끼하\w*|밍밍\w*|실망\w*|기대\s*이하|맛이\s*없\w*|맛이\s*나쁘\w*", 2),
            (r"(?:조금|살짝|약간)\s*아쉽\w*|맛(?:은|이)?\s*괜찮지\s*않\w*", 1),
        ],
        "mention": [r"맛", r"음식 맛"],
    },
    "food_quality": {
        "positive": [
            (r"(?:정말|너무|진짜|아주)\s*(?:신선|싱싱)\w*|재료.{0,6}(?:아주\s*)?(?:좋|신선|싱싱)\w*", 3),
            (r"신선\w*|싱싱\w*|좋은\s*재료|재료.{0,6}(?:좋|괜찮)\w*|품질.{0,6}(?:좋|높)\w*|퀄리티.{0,6}(?:좋|높)\w*|속이\s*꽉\s*차\w*|만두피.{0,6}(?:얇|쫄깃)\w*|수제|직접\s*만든|상태가\s*좋\w*", 2),
        ],
        "negative": [
            (r"상했\w*|상한\s*재료|상태.{0,6}(?:나쁘|안\s*좋)\w*|신선하지\s*않\w*|싱싱하지\s*않\w*|비린내|누린내|잡내|재료.{0,6}(?:별로|나쁘|안\s*좋)\w*|품질.{0,6}(?:낮|떨어)\w*|퀄리티.{0,6}(?:낮|떨어)\w*", 2),
        ],
        "mention": [r"재료", r"신선", r"싱싱", r"식감", r"품질", r"퀄리티", r"고기 질"],
    },
    "portion": {
        "positive": [
            (r"양(?:이|은|도)?\s*(?:아주\s*|정말\s*|너무\s*)?(?:많|푸짐|넉넉|충분)\w*|푸짐\w*|넉넉한\s*양", 2),
            (r"양(?:이|은|도)?\s*적당\w*", 1),
        ],
        "negative": [
            (r"양(?:이|은|도)?\s*(?:너무\s*)?(?:적|부족|모자라|작)\w*|양이\s*아쉽\w*", 2),
            (r"양(?:이|은|도)?\s*(?:조금|살짝|약간)\s*(?:적|부족)\w*", 1),
        ],
        "mention": [r"양"],
    },
    "price": {
        "positive": [
            (r"가성비\s*(?:최고|갑|좋\w*|훌륭\w*)|가격.{0,8}(?:아주\s*|정말\s*|너무\s*)?(?:저렴|싸|착하|합리적)\w*|합리적\s*(?:가격|이었)\w*|가격\s*대비.{0,8}(?:좋|괜찮|만족)\w*|돈이\s*아깝지\s*않\w*", 3),
            (r"가성비|저렴\w*|가격.{0,8}(?:싸|착하|합리적)\w*|가격\s*대비.{0,8}(?:괜찮|좋)\w*", 2),
            (r"가격.{0,6}괜찮\w*|나쁘지\s*않은\s*가격", 1),
        ],
        "negative": [
            (r"(?:너무|정말|진짜)?\s*(?:돈\s*아깝\w*|가격.{0,8}너무\s*비싸\w*|가성비.{0,8}(?:최악|없\w*|너무\s*별로))", 3),
            (r"비싸\w*|비쌌\w*|비싼|가격.{0,8}(?:높|부담|아깝|비싸|비쌌)\w*|돈\s*아깝\w*|가성비.{0,8}(?:별로|나쁘)\w*", 2),
            (r"가격.{0,6}(?:조금|살짝|약간)\s*부담\w*", 1),
        ],
        "mention": [r"가격", r"가성비", r"돈"],
    },
    "service": {
        "positive": [
            (r"(?:정말|너무|매우)\s*(?:친절|상냥)\w*|서비스.{0,8}(?:최고|너무\s*좋)\w*", 3),
            (r"친절\w*|상냥\w*|서비스.{0,8}(?:좋|만족|괜찮)\w*|응대.{0,8}(?:좋|친절)\w*|직원.{0,8}(?:친절|상냥)\w*|사장님.{0,8}친절\w*", 2),
            (r"응대.{0,6}괜찮\w*|서비스.{0,6}나쁘지\s*않\w*", 1),
        ],
        "negative": [
            (r"(?:너무|정말|매우)?\s*(?:불친절\w*|무례\w*|최악의\s*응대|싸가지\s*없\w*|눈치.{0,8}(?:주|보이)|화를\s*내\w*)", 3),
            (r"불친절\w*|서비스.{0,8}(?:별로|나쁘|기대하면\s*안|최악)\w*|응대.{0,8}(?:불쾌|별로|나쁘|아쉽)\w*|눈치.{0,8}(?:주|보이)|짜증\w*|무례\w*|화를\s*내\w*", 2),
            (r"(?:조금|살짝|약간)\s*불편\w*|응대.{0,6}아쉽\w*", 1),
        ],
        "mention": [r"친절", r"불친절", r"직원", r"사장님", r"서비스", r"응대"],
    },
    "waiting": {
        "positive": [
            (r"웨이팅.{0,8}(?:전혀\s*)?없\w*|기다림\s*없이|기다리.{0,8}(?:않\w*|금방)|바로\s*(?:들어가|입장|먹)|기다린\s*보람", 2),
        ],
        "negative": [
            (r"(?:너무|정말|한참|오래)\s*(?:기다리|대기)\w*|웨이팅.{0,8}(?:길|오래|많)\w*|대기.{0,8}(?:길|오래|많)\w*|줄이\s*길\w*|기다리.{0,8}(?:힘들|지루)\w*|(?:20분|30분|한시간|두시간)\s*기다리\w*", 3),
            (r"웨이팅.{0,8}있\w*|대기.{0,8}있\w*|줄\s*서\w*|기다리\w*", 2),
            (r"잠깐\s*기다리\w*|조금\s*기다리\w*", 1),
        ],
        "mention": [r"웨이팅", r"대기", r"기다리", r"줄"],
    },
    "parking_access": {
        "positive": [
            (r"주차.{0,8}(?:아주\s*|너무\s*|정말\s*)?(?:편하|편리|수월|쉬워|넉넉|좋)\w*|주차장.{0,8}(?:넓|넉넉|편하|완비)\w*|주차\s*(?:가능|걱정\s*없\w*)", 2),
        ],
        "negative": [
            (r"주차.{0,8}(?:너무\s*|정말\s*|엄청\s*|매우\s*)(?:힘들|어렵|불편|협소|좁|부족|복잡|빡세)\w*", 3),
            (r"주차.{0,8}없\w*|주차장.{0,8}(?:좁|부족|없)\w*|주차.{0,6}자리.{0,5}(?:없|부족)\w*", 2),
            (r"주차.{0,8}(?:불편|협소|좁|부족|어렵|힘들)\w*|주차장.{0,8}(?:불편|협소|좁|부족)\w*", 2),
            (r"주차.{0,8}(?:조금|살짝|약간)\s*(?:불편|어렵|좁)\w*", 1),
        ],
        "mention": [r"주차", r"주차장", r"주차 공간"],
    },
    "facility_hygiene": {
        "positive": [
            (r"(?:매장|가게|화장실|테이블).{0,8}(?:매우\s*|정말\s*|너무\s*)?(?:깨끗|청결|깔끔)\w*|위생.{0,8}(?:철저|좋|깔끔)\w*", 3),
            (r"깨끗\w*|청결\w*|위생적\w*|위생.{0,8}(?:좋|철저)\w*|매장.{0,8}깔끔\w*", 2),
        ],
        "negative": [
            (r"(?:너무|정말|매우)?\s*(?:더럽\w*|지저분\w*|비위생적\w*)|위생.{0,8}(?:최악|너무\s*나쁘)\w*", 3),
            (r"더럽\w*|지저분\w*|위생.{0,8}(?:나쁘|별로|문제|안\s*좋)\w*|청결하지\s*않\w*|비위생적\w*", 2),
            (r"조금\s*(?:지저분|청결하지)\w*", 1),
        ],
        "mention": [r"위생", r"청결", r"깨끗", r"더럽", r"지저분", r"화장실"],
    },
    "atmosphere": {
        "positive": [
            (r"(?:분위기|매장).{0,8}(?:정말\s*|너무\s*|아주\s*)?(?:좋|아늑|쾌적|편안|조용)\w*", 3),
            (r"분위기.{0,8}(?:좋|아늑|쾌적|편안|조용)\w*|아늑\w*|쾌적\w*|조용한\s*(?:분위기|매장)|편안한\s*분위기", 2),
            (r"분위기.{0,6}괜찮\w*|나쁘지\s*않은\s*분위기", 1),
        ],
        "negative": [
            (r"(?:너무|정말|매우)?\s*(?:시끄럽\w*|소란스럽\w*|답답\w*)|분위기.{0,8}(?:최악|시끄럽|너무\s*나쁘)\w*", 3),
            (r"분위기.{0,8}(?:별로|나쁘|시끄럽|불편)\w*|시끄럽\w*|소란스럽\w*|답답\w*", 2),
            (r"조금\s*(?:시끄럽|답답)\w*", 1),
        ],
        "mention": [r"분위기", r"조용", r"시끄럽", r"아늑", r"쾌적", r"소란"],
    },
    "revisit_intent": {
        "positive": [
            (r"꼭\s*(?:다시\s*)?(?:방문|오|가|먹)\w*|다시\s*꼭\s*(?:오|가|방문)\w*|재방문\s*(?:의사|할게|하고\s*싶|하겠습니다)|또\s*(?:오고\s*싶|가고\s*싶|먹고\s*싶)\w*", 3),
            (r"재방문\w*|다시\s*(?:방문|오|가|먹)\w*|또\s*(?:오|가|먹|방문)\w*", 2),
        ],
        "negative": [
            (r"다시는\s*(?:안|못)\s*(?:가|오|먹)\w*|재방문.{0,8}(?:없|안\s*할|못\s*할)\w*|다시\s*(?:안|못)\s*(?:가|오|먹)\w*|또\s*오고\s*싶지\s*않\w*", 3),
            (r"재방문.{0,8}(?:고민|생각\s*없)\w*|다시\s*갈\s*생각\s*없\w*", 2),
        ],
        "mention": [r"재방문", r"다시\s*(?:방문|오|가|먹)", r"또\s*(?:오|가|먹|방문)"],
    },
}

_COMPILED_RULES = {
    aspect: {
        group: (
            [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
            if group == "mention"
            else [(re.compile(pattern, re.IGNORECASE), intensity) for pattern, intensity in patterns]
        )
        for group, patterns in groups.items()
    }
    for aspect, groups in RAW_RULES.items()
}
_SENTENCE_SPLIT = re.compile(r"[\n\r.!?。！？]+")
_CONTRAST_SPLIT = re.compile(r"(?:하지만|그러나|다만|그런데|근데|반면에|(?<=[가-힣])(?:지만|는데|은데))")
_NEGATION_AFTER = re.compile(r"^\s*(?:(?:지\s*)?(?:않|못)|않|못)(?:아요|어요|습니다|다|았\w*|았어요|았지만|은|은데|고)?")
_NEGATION_BEFORE = re.compile(r"(?:안|못|전혀|별로|덜)\s*$")
_INTENSIFIER_BEFORE = re.compile(r"(?:정말|너무|진짜|완전|엄청|매우|조금|살짝|약간|전혀|별로|다시는|안|못|덜)\s*$")


def split_review_text(review_text: str) -> list[str]:
    sentences = []
    for sentence in _SENTENCE_SPLIT.split(review_text):
        for clause in _CONTRAST_SPLIT.split(sentence):
            clause = clause.strip()
            if clause:
                sentences.append(clause)
    return sentences


def _is_negated(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 10):start]
    after = text[end:end + 14]
    return bool(_NEGATION_BEFORE.search(before) or _NEGATION_AFTER.match(after))


def _evidence(text: str, start: int, end: int) -> str:
    before = text[max(0, start - 10):start]
    modifier = _INTENSIFIER_BEFORE.search(before)
    if modifier:
        start -= len(modifier.group(0))
    after = text[end:end + 14]
    negation = _NEGATION_AFTER.match(after)
    if negation:
        end += len(negation.group(0))
    return text[start:end].strip()


def analyze_review_text(review_text: str) -> dict[str, dict[str, dict[str, str | int | None]]]:
    """Return explicit sentiment, intensity, and source evidence for the ten aspects."""
    results = {}
    clauses = split_review_text(review_text)
    for aspect in ASPECTS:
        signals = []
        mentions = []
        rules = _COMPILED_RULES[aspect]
        for clause_index, clause in enumerate(clauses):
            for group, sentiment in (("positive", "positive"), ("negative", "negative")):
                for pattern, intensity in rules[group]:
                    for match in pattern.finditer(clause):
                        actual_sentiment = sentiment
                        if _is_negated(clause, *match.span()):
                            actual_sentiment = "negative" if sentiment == "positive" else "positive"
                        signals.append({
                            "sentiment": actual_sentiment,
                            "intensity": intensity,
                            "evidence": _evidence(clause, *match.span()),
                            "position": clause_index,
                            "start": match.start(),
                        })
            for pattern in rules["mention"]:
                match = pattern.search(clause)
                if match:
                    mentions.append({
                        "evidence": match.group(0),
                        "position": clause_index,
                        "start": match.start(),
                    })

        if signals:
            signals.sort(key=lambda item: (item["intensity"], item["position"], item["start"]))
            chosen = signals[-1]
            same_strength = [signal for signal in signals if signal["intensity"] == chosen["intensity"]]
            if {signal["sentiment"] for signal in same_strength} == {"positive", "negative"}:
                chosen = max(same_strength, key=lambda item: (item["position"], item["start"]))
            results[aspect] = {
                "sentiment": chosen["sentiment"],
                "intensity": chosen["intensity"],
                "evidence": chosen["evidence"],
            }
        elif mentions:
            mention = mentions[-1]
            results[aspect] = {
                "sentiment": "neutral",
                "intensity": 1,
                "evidence": mention["evidence"],
            }
        else:
            results[aspect] = {"sentiment": "not_mentioned", "intensity": 0, "evidence": None}
    return {"criteria": results}


class RuleBasedReviewAnalyzer:
    """Drop-in analyzer implementation for the OpenAI pipeline's analyze(text) contract."""

    model = "korean-rules-v1"

    def analyze(self, review_text: str) -> dict[str, dict[str, dict[str, str | int | None]]]:
        return analyze_review_text(review_text)