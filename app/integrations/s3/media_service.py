import uuid
import os


def get_file_extension(filename: str) -> str:

    if not filename or "." not in filename:
        return ".jpg"

    return os.path.splitext(filename)[1]


def generate_media_key(folder: str, filename: str) -> str:

    extension = get_file_extension(filename)

    unique_filename = f"{uuid.uuid4()}{extension}"

    return f"{folder}/{unique_filename}"