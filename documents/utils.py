import re


def get_cloudinary_public_id_regex(url):
    """
    Extracts the public ID from a Cloudinary image URL using regex.
    """
    # Regex to capture the public ID after /upload/ and before the extension
    # It accounts for optional transformations and version numbers
    if not url:
        return None

    # Regex to capture everything after /upload/(optional vXXX/) and before the extension
    # Includes any folder path
    match = re.search(r"/upload/(?:v\d+/)?(.+?)\.[a-zA-Z0-9]+$", url)
    if match:
        return match.group(1)

    return None
