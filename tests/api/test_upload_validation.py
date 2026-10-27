"""Small independent integrity tests; integration lives against real services."""

import hashlib
import io
import unittest

from pydantic import ValidationError

from services.api.uploads import CreateUpload
from workers.validation import ValidationFailure, validate_stream


class ValidationTests(unittest.TestCase):
    def test_utf8_across_chunk_boundary_preserves_exact_bytes(self):
        body = b"a" * (1024 * 1024 - 1) + "汉语\n".encode()
        digest = hashlib.sha256(body).hexdigest()
        result = validate_stream(io.BytesIO(body), len(body), digest)
        self.assertEqual(result["size"], len(body))
        self.assertEqual(result["sha256"], digest)

    def test_integrity_and_binary_failures(self):
        for body, size, digest, code in [
            (b"abc", 4, hashlib.sha256(b"abc").hexdigest(), "SIZE_MISMATCH"),
            (b"abc", 2, hashlib.sha256(b"abc").hexdigest(), "SIZE_MISMATCH"),
            (b"abc", 3, "0" * 64, "CHECKSUM_MISMATCH"),
            (b"\x00", 1, hashlib.sha256(b"\x00").hexdigest(), "UNSUPPORTED_CONTENT"),
            (b"\xe4\xb8", 2, hashlib.sha256(b"\xe4\xb8").hexdigest(), "INVALID_TEXT_ENCODING"),
        ]:
            with self.subTest(code=code, size=size):
                with self.assertRaises(ValidationFailure) as caught:
                    validate_stream(io.BytesIO(body), size, digest)
                self.assertEqual(caught.exception.code, code)

    def test_client_cannot_choose_storage_key(self):
        with self.assertRaises(ValidationError):
            CreateUpload(filename="x.txt", size=3, sha256="0" * 64,
                         media_type="text/plain", object_key="other-project/secret")


if __name__ == "__main__":
    unittest.main()
