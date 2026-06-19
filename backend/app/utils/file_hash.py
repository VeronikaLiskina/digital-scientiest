import hashlib


def calculate_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
