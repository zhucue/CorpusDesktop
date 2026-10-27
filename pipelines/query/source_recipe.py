"""Fixed S3 surface-token recipe. Importing this module loads no dictionaries."""
import hashlib
import json

RECIPE = {
    "id": "tatoeba-surface-index/v1",
    "builder_algorithm": "source-index-build/v1",
    "identity_rule": "Any token, mapping or matching semantic change requires a new recipe id/version.",
    "cwb_package": "3.5.0-1",
    "cwb_package_sha256": "257ef6f71a055ee70cd57904173e40f8e8f0e6c93ac7edf5d7d2e3a21c023601",
    "normalization": "none",
    "sentence_boundary": "one_upstream_sentence_record",
    "document_count_unit": "imported_sentence_record",
    "order": "ascending_numeric_source_sentence_id",
    "cmn": {"package": "jieba", "version": "0.42.1", "mode": "default", "HMM": False,
            "dictionary_sha256": "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8",
            "user_dictionary": False},
    "eng": {"package": "nltk", "version": "3.10.3", "class": "TreebankWordTokenizer.span_tokenize",
            "model_download": False},
    "form": "exact_original_codepoint_slice",
    "cwb_word_key": "u + lowercase hexadecimal UTF-8 bytes; reversible, avoids CWB implicit NFC",
    "whitespace_tokens": "excluded", "punctuation_tokens": "included",
    "case": "preserved", "numbers": "included", "attributes": ["form"],
    "coordinates": "unicode_codepoint_half_open",
    "character_storage": "sorted_vocabulary_little_endian_uint64_global_positions/v1",
    "token_storage": "cwb-3.5.0+little_endian_uint32_revision_start_end/v1",
}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


RECIPE_ID = RECIPE["id"]
RECIPE_SHA256 = hashlib.sha256(encoded(RECIPE)).hexdigest()


def storage_key(form):
    return "u" + form.encode("utf-8").hex()


class SurfaceTokenizer:
    def __init__(self, temporary_directory):
        import importlib.metadata

        import jieba
        from nltk.tokenize import TreebankWordTokenizer

        for name, version in (("jieba", "0.42.1"), ("nltk", "3.10.3")):
            if importlib.metadata.version(name) != version:
                raise ValueError("TOKENIZER_VERSION_MISMATCH")
        self.chinese = jieba.Tokenizer()
        with self.chinese.get_dict_file() as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != RECIPE["cmn"]["dictionary_sha256"]:
                raise ValueError("TOKENIZER_DICTIONARY_MISMATCH")
        self.chinese.tmp_dir = str(temporary_directory)
        self.chinese.cache_file = "jieba-s3.cache"
        self.english = TreebankWordTokenizer()

    def spans(self, text, language):
        if language == "cmn":
            spans = ((a, b) for _, a, b in self.chinese.tokenize(text, mode="default", HMM=False))
        elif language == "eng":
            spans = self.english.span_tokenize(text)
        else:
            raise ValueError("UNSUPPORTED_LANGUAGE")
        result, cursor = [], 0
        for start, end in spans:
            if not 0 <= cursor <= start < end <= len(text) or text[cursor:start].strip():
                raise ValueError("TOKEN_MAPPING_INCOMPLETE")
            form = text[start:end]
            if not form.isspace():
                if any(c in form for c in "\t\r\n\x00"):
                    raise ValueError("TOKEN_FORM_CONTROL_CHARACTER")
                result.append((start, end, form))
            cursor = end
        if text[cursor:].strip() or not result:
            raise ValueError("TOKEN_MAPPING_INCOMPLETE")
        return result
