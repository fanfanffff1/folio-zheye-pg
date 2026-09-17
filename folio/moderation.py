from __future__ import annotations

import re

# 宽松自动审核：默认通过。只拦截明显辱骂、仇恨与政治敏感用语。
ABUSE = (
    "傻逼", "傻b", "傻比", "傻屌", "傻吊", "煞笔", "蠢逼", "废物", "去死", "滚蛋",
    "操你", "草你", "肏你", "操你妈", "草你妈", "他妈的", "你妈的", "你妈逼",
    "白痴", "智障", "脑残", "贱种", "贱人", "狗东西", "畜生", "全家死",
    "fuckyou", "fuckyour", "stupidbitch", "kill yourself", "kys",
)
HATE = (
    "去死吧", "屠华", "杀光", "种族灭绝", "纳粹", "nigger", "faggot",
)
POLITICAL = (
    "法轮功", "台独", "港独", "藏独", "疆独", "分裂国家", "推翻政府",
    "习近平", "毛泽东", "江泽民", "六四", "天安门事件",
)

_SEP = re.compile(r"[\s\-_\.*·•、,，.。!！?？~～'\"“”‘’()（）\[\]【】]+")
_REPEAT = re.compile(r"(.)\1{4,}")


def _fold(text: str) -> str:
    raw = (text or "").replace("\x00", "")
    raw = _SEP.sub("", raw).lower()
    raw = _REPEAT.sub(r"\1\1", raw)
    return raw


def auto_review(text: str) -> dict:
    folded = _fold(text)
    for word in ABUSE + HATE + POLITICAL:
        needle = _fold(word)
        if needle and needle in folded:
            return {
                "status": "pending",
                "reason": "auto_hold",
                "message": "评论含有不适宜公开的用语，已交给编辑复核，通过后才会显示。",
            }
    return {
        "status": "published",
        "reason": "auto_pass",
        "message": "评论已发布。",
    }


def publish_clean_pending(db) -> int:
    from .models import Comment
    n = 0
    rows = db.query(Comment).filter(Comment.status == "pending", Comment.deleted_at.is_(None)).all()
    for row in rows:
        if auto_review(row.content)["status"] == "published":
            row.status = "published"
            n += 1
    if n:
        db.commit()
    return n
