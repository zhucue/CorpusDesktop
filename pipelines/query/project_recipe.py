"""Immutable project index recipe; importing loads no token models."""
import hashlib

from pipelines.materials.txt import RECIPE_SHA256 as TXT_RECIPE_SHA256
from pipelines.query.source_recipe import RECIPE as SOURCE_RECIPE
from pipelines.query.source_recipe import encoded

RECIPE = {**SOURCE_RECIPE, 'id':'project-surface-index/v1', 'builder_algorithm':'project-index-build/v1',
          'sentence_boundary':'private-txt/v1 segments or fixed source segments',
          'document_count_unit':'document', 'order':'source namespace/identity then private document/revision; contiguous document segments',
          'txt_recipe_sha256':TXT_RECIPE_SHA256,
          'metadata_storage':'ordinal offset-length JSONL/v1',
          'coordinates':'internal segment-local, public complete canonical revision codepoints'}
RECIPE_ID = RECIPE['id']
RECIPE_SHA256 = hashlib.sha256(encoded(RECIPE)).hexdigest()
