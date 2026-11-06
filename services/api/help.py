"""Help page data the web client cannot read itself (contracts/p11.md §三 1): metric formulas and references
from engine/methods.py, the same table the method appendix uses."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from engine import methods
from services.api.auth import CurrentUser

router = APIRouter(prefix="/api/help")


@router.get("/metrics")
def metrics(
    _: CurrentUser,
    style: Annotated[Literal["gbt7714", "apa"], Query()] = "gbt7714",
):
    """[{key, name, formula, references: [{key, label, text}]}] in appendix order."""
    return {
        "style": style,
        "items": [
            {
                "key": key,
                "name": name,
                "formula": formula,
                "references": [
                    {
                        "key": ref,
                        "label": methods.REFERENCES[ref][1],
                        "text": methods.reference(ref, style),
                    }
                    for ref in refs
                ],
            }
            for key, (name, formula, refs) in methods.METRICS.items()
        ],
    }
