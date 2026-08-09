import hashlib
from pathlib import Path

def sha256_file(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()

def safe_filename(name):
    return "".join(c for c in Path(name).name if c.isalnum() or c in "._-（）() ")[:180]
