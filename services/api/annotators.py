"""Whose annotations a request reads and writes (contracts/p5.md §三 多人与一致性).

single mode: one shared set; every row has annotator_id = layer creator, any owner / editor / annotator edits it.
multi mode: each listed annotator has an own set. Annotators read and write only their own rows; owner / editor
read everyone's (or one annotator's with `annotator_id`) and adjudicate, and write only if they are listed.
"""

from services.api.access import WRITE, project_role
from services.api.errors import ApiError, forbidden


def layer_annotators(layer) -> list:
    if layer.mode == "multi":
        return list(layer.annotators or [layer.created_by])
    return [layer.created_by]


def writer(layer, user):
    """annotator_id written for this user's annotations."""
    if layer.mode != "multi":
        return layer.created_by
    if user.id not in layer_annotators(layer):
        raise ApiError(403, "NOT_ANNOTATOR", "你不是该层的标注者")
    return user.id


def visible(db, layer, user, annotator_id=None) -> list | None:
    """Annotator ids whose rows the user sees (None = all annotators)."""
    if layer.mode != "multi":
        return [layer.created_by]
    role = project_role(db, layer.project_id, user)
    if role in WRITE:
        if annotator_id is not None:
            return [annotator_id]
        return [user.id] if user.id in layer_annotators(layer) else None
    if annotator_id is not None and annotator_id != user.id:
        raise forbidden()
    return [user.id]


def can_adjudicate(db, layer, user) -> bool:
    return project_role(db, layer.project_id, user) in WRITE
