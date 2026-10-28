"""Label sets (contracts/p3.md §二–§三, p5.md §二): built-in `upos`, `jieba`, `ud-deprel`, `learner-errors`,
`translation-strategies` (span) and `error-correction` (relation) (project_id null, seeded at api startup) and
project sets, usually copied from a built-in and edited. A label is {id, name, color?, description?, parent?};
annotations store the label id. learner-errors labels are children of the root label 偏误, so `[偏误]` finds
every error and `[偏误:时态]` the tense errors."""

import uuid
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import case, exists, or_, select
from sqlalchemy.dialects.postgresql import insert

from engine.query import JIEBA_TAGS
from services.api.access import READ, WRITE, human_only, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.models import AnnotationLayer, LabelSet

router = APIRouter(prefix="/api")

UPOS_NAMES = {
    "ADJ": "形容词",
    "ADP": "介词",
    "ADV": "副词",
    "AUX": "助动词",
    "CCONJ": "并列连词",
    "DET": "限定词",
    "INTJ": "叹词",
    "NOUN": "名词",
    "NUM": "数词",
    "PART": "小品词",
    "PRON": "代词",
    "PROPN": "专有名词",
    "PUNCT": "标点",
    "SCONJ": "从属连词",
    "SYM": "符号",
    "VERB": "动词",
    "X": "其他",
}
JIEBA_NAMES = {
    "a": "形容词",
    "ad": "副形词",
    "ag": "形容词性语素",
    "an": "名形词",
    "b": "区别词",
    "c": "连词",
    "d": "副词",
    "df": "副词（不要）",
    "dg": "副语素",
    "e": "叹词",
    "eng": "外文",
    "f": "方位词",
    "g": "语素",
    "h": "前缀",
    "i": "成语",
    "j": "简称略语",
    "k": "后缀",
    "l": "习用语",
    "m": "数词",
    "mg": "数语素",
    "mq": "数量词",
    "n": "名词",
    "ng": "名词性语素",
    "nr": "人名",
    "nrfg": "人名（全名）",
    "nrt": "音译人名",
    "ns": "地名",
    "nt": "机构团体",
    "nz": "其他专名",
    "o": "拟声词",
    "p": "介词",
    "q": "量词",
    "r": "代词",
    "rg": "代词性语素",
    "rr": "人称代词",
    "rz": "指示代词",
    "s": "处所词",
    "t": "时间词",
    "tg": "时语素",
    "u": "助词",
    "ud": "助词（得）",
    "ug": "助词（过）",
    "uj": "助词（的）",
    "ul": "助词（了）",
    "uv": "助词（地）",
    "uz": "助词（着）",
    "v": "动词",
    "vd": "副动词",
    "vg": "动语素",
    "vi": "不及物动词",
    "vn": "名动词",
    "vq": "动量词",
    "w": "标点符号",
    "x": "非语素字",
    "y": "语气词",
    "z": "状态词",
    "zg": "状态词语素",
}
UD_DEPREL = {
    "acl": "形容词性从句",
    "advcl": "状语从句",
    "advmod": "状语",
    "amod": "形容词修饰",
    "appos": "同位语",
    "aux": "助动词",
    "case": "格标记",
    "cc": "并列连词",
    "ccomp": "补语从句",
    "clf": "量词",
    "compound": "复合",
    "conj": "并列",
    "cop": "系词",
    "csubj": "从句主语",
    "dep": "未定关系",
    "det": "限定词",
    "discourse": "话语成分",
    "dislocated": "移位成分",
    "expl": "形式成分",
    "fixed": "固定表达",
    "flat": "平铺结构",
    "goeswith": "拆分词",
    "iobj": "间接宾语",
    "list": "列表",
    "mark": "从句标记",
    "nmod": "名词修饰",
    "nsubj": "名词主语",
    "nummod": "数词修饰",
    "obj": "宾语",
    "obl": "旁格成分",
    "orphan": "孤立成分",
    "parataxis": "意合并列",
    "punct": "标点",
    "reparandum": "修正前成分",
    "root": "根",
    "vocative": "呼语",
    "xcomp": "开放补语",
}
# Subtypes produced by the Stanza en (EWT) and zh-hans (GSDSimp) parsers and the UD English sample.
UD_SUBTYPES = [
    "acl:relcl",
    "advcl:relcl",
    "aux:pass",
    "cc:preconj",
    "compound:ext",
    "compound:prt",
    "csubj:outer",
    "csubj:pass",
    "det:predet",
    "discourse:sp",
    "flat:foreign",
    "flat:name",
    "mark:adv",
    "mark:rel",
    "nmod:desc",
    "nmod:poss",
    "nmod:tmod",
    "nmod:unmarked",
    "nsubj:outer",
    "nsubj:pass",
    "obl:agent",
    "obl:npmod",
    "obl:patient",
    "obl:tmod",
    "obl:unmarked",
]


LEARNER_ERRORS = {
    "时态": "动词时态用错，如该用过去时用了现在时",
    "体": "体貌用错，如完成体、进行体、了 / 着 / 过",
    "冠词": "冠词缺失、多余或误用",
    "介词": "介词缺失、多余或误用",
    "搭配": "词语搭配不当",
    "词序": "语序错误",
    "主谓一致": "主语与谓语的人称、数不一致",
    "拼写": "拼写或错别字",
    "漏词": "缺少必要的词",
    "多词": "多出不该有的词",
    "用词": "选词不当、词义误用",
    "句式": "句式结构错误",
    "标点": "标点符号误用",
}
TRANSLATION_STRATEGIES = {
    "直译": "保留原文结构与字面意义",
    "意译": "舍弃原文形式，传达意义",
    "增译": "增加原文没有的词语或信息",
    "减译": "删去原文的部分词语",
    "词类转换": "改变词性，如名词译为动词",
    "语态转换": "主动与被动互换",
    "分句": "一句拆成多句",
    "合句": "多句合为一句",
    "归化": "向译入语文化靠拢",
    "异化": "保留源语文化特征",
    "音译": "按读音转写",
    "省略": "省去原文的整段或成分",
}
ERROR_CORRECTION = {  # id: (display name, description)
    "correction": ("更正", "从偏误片段指向其更正片段"),
    "cause": ("成因", "从偏误片段指向引起该偏误的片段"),
}


def _label(tag, description=None, parent=None):
    label = {"id": tag, "name": tag}
    if description:
        label["description"] = description
    if parent:
        label["parent"] = parent
    return label


BUILTIN = {
    "upos": ("pos", None, [_label(t, d) for t, d in UPOS_NAMES.items()]),
    "jieba": (
        "pos",
        "zh",
        [
            _label(t, JIEBA_NAMES.get(t), t[0] if len(t) > 1 and t != "eng" else None)
            for t in JIEBA_TAGS
        ],
    ),
    "ud-deprel": (
        "dep",
        None,
        [_label(t, d) for t, d in UD_DEPREL.items()]
        + [_label(t, parent=t.split(":")[0]) for t in UD_SUBTYPES],
    ),
    "learner-errors": (
        "span",
        None,
        [_label("偏误", "学习者语言偏误（未细分）")]
        + [_label(t, d, "偏误") for t, d in LEARNER_ERRORS.items()],
    ),
    "translation-strategies": (
        "span",
        None,
        [_label(t, d) for t, d in TRANSLATION_STRATEGIES.items()],
    ),
    "error-correction": (
        "relation",
        None,
        [{**_label(t, d), "name": n} for t, (n, d) in ERROR_CORRECTION.items()],
    ),
}


def seed_builtin(db):
    """Insert or refresh the built-in label sets (idempotent)."""
    for name, (kind, language, labels) in BUILTIN.items():
        stmt = insert(LabelSet).values(
            id=uuid.uuid4(),
            project_id=None,
            name=name,
            kind=kind,
            language=language,
            labels=labels,
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["name"],
                index_where=LabelSet.project_id.is_(None),
                set_={"kind": kind, "language": language, "labels": labels},
            )
        )


def builtin_id(db, name):
    return db.scalar(
        select(LabelSet.id).where(LabelSet.project_id.is_(None), LabelSet.name == name)
    )


def label_set_view(s):
    return {
        "id": s.id,
        "project_id": s.project_id,
        "name": s.name,
        "kind": s.kind,
        "language": s.language,
        "labels": s.labels,
        "created_at": s.created_at,
    }


class LabelInput(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=500)
    parent: str | None = Field(default=None, max_length=64)


Labels = Annotated[list[LabelInput], Field(max_length=500)]


def _labels(labels):
    ids = [x.id for x in labels]
    if len(set(ids)) != len(ids):
        raise ApiError(422, "VALIDATION_ERROR", "标签 id 重复")
    return [x.model_dump(exclude_none=True) for x in labels]


class LabelSetInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["pos", "dep", "span", "relation"]
    language: str | None = Field(default=None, max_length=20)
    labels: Labels | None = None
    copy_from: UUID | None = None

    @model_validator(mode="after")
    def has_labels(self):
        if self.labels is None and self.copy_from is None:
            raise ValueError("须提供 labels 或 copy_from")
        return self


class LabelSetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    labels: Labels | None = None


def load_label_set(db, label_set_id, user, write=False) -> LabelSet:
    s = db.get(LabelSet, label_set_id)
    if not s:
        raise not_found("标签集")
    if s.project_id is None:
        if write:
            raise forbidden()
    else:
        require_project(db, s.project_id, user, WRITE if write else READ)
    return s


@router.get("/label-sets")
def list_label_sets(
    user: CurrentUser,
    db: Db,
    project_id: UUID | None = None,
    kind: Annotated[Literal["pos", "dep", "span", "relation"] | None, Query()] = None,
):
    where = [LabelSet.project_id.is_(None)]
    if project_id:
        require_project(db, project_id, user)
        where = [or_(LabelSet.project_id.is_(None), LabelSet.project_id == project_id)]
    stmt = select(LabelSet).where(*where)
    if kind:
        stmt = stmt.where(LabelSet.kind == kind)
    builtin_order = case(
        {n: k for k, n in enumerate(BUILTIN)}, value=LabelSet.name, else_=len(BUILTIN)
    )
    rows = db.scalars(
        stmt.order_by(
            LabelSet.project_id.is_not(None),
            builtin_order,
            LabelSet.created_at,
            LabelSet.name,
        )
    ).all()
    return {"items": [label_set_view(s) for s in rows], "total": len(rows)}


@router.post("/projects/{project_id}/label-sets")
def create_label_set(project_id: UUID, body: LabelSetInput, user: CurrentUser, db: Db):
    human_only(user)
    require_project(db, project_id, user, WRITE)
    labels = _labels(body.labels) if body.labels is not None else None
    language = body.language
    if body.copy_from:
        src = load_label_set(db, body.copy_from, user)
        if src.project_id not in (None, project_id):
            raise not_found("标签集")
        if src.kind != body.kind:
            raise ApiError(422, "VALIDATION_ERROR", "复制来源的类型与 kind 不一致")
        labels = src.labels if labels is None else labels
        language = language or src.language
    s = LabelSet(
        project_id=project_id,
        name=body.name.strip(),
        kind=body.kind,
        language=language,
        labels=labels,
    )
    db.add(s)
    db.commit()
    return label_set_view(s)


@router.patch("/label-sets/{label_set_id}")
def patch_label_set(label_set_id: UUID, body: LabelSetPatch, user: CurrentUser, db: Db):
    human_only(user)
    s = load_label_set(db, label_set_id, user, write=True)
    if body.name is not None:
        s.name = body.name.strip()
    if body.labels is not None:
        s.labels = _labels(body.labels)
    db.commit()
    return label_set_view(s)


@router.delete("/label-sets/{label_set_id}", status_code=204)
def delete_label_set(label_set_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    s = load_label_set(db, label_set_id, user, write=True)
    if db.scalar(select(exists().where(AnnotationLayer.label_set_id == s.id))):
        raise ApiError(409, "LABEL_SET_IN_USE", "标签集正被标注层使用")
    db.delete(s)
    db.commit()
