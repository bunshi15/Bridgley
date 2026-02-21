# app/infra/image_processor.py
"""
Secure image processing with validation and sanitization.

Security features:
- File size limits
- Format validation (magic bytes, not just extension)
- Image re-encoding to strip EXIF/metadata
- Max pixel dimensions
- UUID-based filenames to prevent path traversal
- WebP chunk validation (CVE-2023-4863 mitigation)
- Resource limits during processing
"""
from __future__ import annotations

import io
import struct
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO

from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# Try to import PIL, but make it optional
try:
    from PIL import Image, ImageFile

    # IMPORTANT: Do NOT allow truncated images!
    # Setting LOAD_TRUNCATED_IMAGES = True causes black bands at bottom of images
    # when data is incomplete. Better to reject corrupted images than serve broken ones.
    ImageFile.LOAD_TRUNCATED_IMAGES = False

    # SECURITY: Decompression bomb protection
    # A small compressed file can decompress to huge dimensions (DoS attack)
    # Default MAX_IMAGE_PIXELS is ~178 million, we set stricter limit
    #
    # NOTE: This is the PARSING limit, not the output limit. Modern phones like
    # iPhone 15 shoot 48MP (8064x6048). We allow parsing up to 50MP, but then
    # resize down to config.max_pixels (default 16MP) for storage/processing.
    # This balances security (reject >50MP bombs) with usability (accept phone photos).
    Image.MAX_IMAGE_PIXELS = 50_000_000  # 50 megapixels - allows iPhone 48MP

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not installed - image processing disabled")


class ImageError(Exception):
    """Base exception for image processing errors"""
    pass


class ImageTooLargeError(ImageError):
    """Image file size exceeds limit"""
    pass


class ImageInvalidFormatError(ImageError):
    """Image format not allowed or invalid"""
    pass


class ImageDimensionError(ImageError):
    """Image dimensions exceed limit"""
    pass


class AllowedFormat(str, Enum):
    """Allowed image formats"""
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    HEIC = "heic"  # iPhone format


# Magic bytes for format detection
MAGIC_BYTES = {
    b'\xff\xd8\xff': AllowedFormat.JPEG,
    b'\x89PNG\r\n\x1a\n': AllowedFormat.PNG,
    b'RIFF': AllowedFormat.WEBP,  # WebP starts with RIFF
    b'\x00\x00\x00': AllowedFormat.HEIC,  # HEIC/HEIF (simplified)
}

# WebP chunk types - for validation
# CVE-2023-4863 exploited malformed VP8L (lossless) chunks
WEBP_VALID_CHUNKS = {b'VP8 ', b'VP8L', b'VP8X', b'ANIM', b'ANMF', b'ALPH', b'ICCP', b'EXIF', b'XMP '}
WEBP_MAX_CHUNK_SIZE = 100 * 1024 * 1024  # 100MB max per chunk (sanity check)


@dataclass
class ImageConfig:
    """Configuration for image processing"""
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_width: int = 4096
    max_height: int = 4096
    max_pixels: int = 16 * 1024 * 1024  # 16 megapixels
    output_format: str = "JPEG"
    output_quality: int = 85
    allowed_formats: set[AllowedFormat] = None

    def __post_init__(self):
        if self.allowed_formats is None:
            self.allowed_formats = {
                AllowedFormat.JPEG,
                AllowedFormat.PNG,
                AllowedFormat.WEBP,
                AllowedFormat.HEIC,
            }


def get_image_config() -> ImageConfig:
    """
    Get ImageConfig from application settings.
    Allows runtime configuration of allowed formats and limits.
    """
    from app.config import settings

    allowed = {AllowedFormat.JPEG, AllowedFormat.PNG}

    # SECURITY: WebP can be disabled via config due to historical RCE vulns
    if settings.allow_webp_images:
        allowed.add(AllowedFormat.WEBP)

    # HEIC (iPhone) can also be disabled
    if settings.allow_heic_images:
        allowed.add(AllowedFormat.HEIC)

    return ImageConfig(
        max_file_size_bytes=settings.image_max_file_size_mb * 1024 * 1024,
        max_pixels=settings.image_max_pixels_millions * 1024 * 1024,
        allowed_formats=allowed,
    )


# Default configuration (static fallback)
DEFAULT_CONFIG = ImageConfig()


@dataclass
class ProcessedImage:
    """Result of image processing"""
    uuid: str
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    data: bytes


def detect_format(data: bytes) -> AllowedFormat | None:
    """
    Detect image format from magic bytes.
    More secure than relying on file extension or Content-Type header.
    """
    for magic, fmt in MAGIC_BYTES.items():
        if data.startswith(magic):
            return fmt

    # Special handling for WebP (RIFF....WEBP)
    if data[:4] == b'RIFF' and len(data) > 11 and data[8:12] == b'WEBP':
        return AllowedFormat.WEBP

    # Special handling for HEIC/HEIF
    if len(data) > 12:
        # Check for ftyp box with heic/heif brand
        if b'ftyp' in data[4:12] and (b'heic' in data[8:20] or b'heif' in data[8:20] or b'mif1' in data[8:20]):
            return AllowedFormat.HEIC

    return None


def validate_webp_structure(data: bytes) -> None:
    """
    Validate WebP file structure before passing to image decoder.

    SECURITY: This is defense-in-depth against WebP parser vulnerabilities like
    CVE-2023-4863 (libwebp heap buffer overflow). By validating the chunk structure
    ourselves, we can reject malformed files before they reach the vulnerable parser.

    WebP format (RIFF container):
    - Bytes 0-3: "RIFF"
    - Bytes 4-7: File size (little-endian, excludes first 8 bytes)
    - Bytes 8-11: "WEBP"
    - Bytes 12+: Chunks (4-byte type + 4-byte size + data + optional padding)

    Raises:
        ImageInvalidFormatError: If WebP structure is invalid
    """
    if len(data) < 12:
        raise ImageInvalidFormatError("WebP file too small")

    # Validate RIFF header
    if data[:4] != b'RIFF':
        raise ImageInvalidFormatError("Invalid WebP: missing RIFF header")

    # Validate WEBP signature
    if data[8:12] != b'WEBP':
        raise ImageInvalidFormatError("Invalid WebP: missing WEBP signature")

    # Parse declared file size
    declared_size = struct.unpack('<I', data[4:8])[0]
    actual_size = len(data) - 8  # RIFF size excludes first 8 bytes

    # Allow some tolerance for padding, but reject if declared >> actual (overflow attempt)
    if declared_size > actual_size + 1:
        logger.warning(
            f"WebP declared size mismatch: declared={declared_size}, actual={actual_size}"
        )
        raise ImageInvalidFormatError("Invalid WebP: size mismatch (possible overflow attempt)")

    # Validate chunks
    offset = 12  # Start after "RIFF" + size + "WEBP"
    chunk_count = 0
    max_chunks = 100  # Sanity limit

    while offset < len(data) - 8 and chunk_count < max_chunks:
        if offset + 8 > len(data):
            break  # Not enough data for chunk header

        chunk_type = data[offset:offset + 4]
        chunk_size = struct.unpack('<I', data[offset + 4:offset + 8])[0]

        # Validate chunk type (must be printable ASCII or known types)
        if chunk_type not in WEBP_VALID_CHUNKS:
            # Check if it's at least printable ASCII (some extended chunks)
            if not all(32 <= b < 127 for b in chunk_type):
                logger.warning(f"WebP invalid chunk type at offset {offset}: {chunk_type!r}")
                raise ImageInvalidFormatError("Invalid WebP: malformed chunk type")

        # Validate chunk size
        if chunk_size > WEBP_MAX_CHUNK_SIZE:
            logger.warning(f"WebP chunk too large: {chunk_type!r} size={chunk_size}")
            raise ImageInvalidFormatError("Invalid WebP: chunk size exceeds limit")

        # Check chunk doesn't overflow file
        chunk_end = offset + 8 + chunk_size
        if chunk_end > len(data) + 1:  # +1 for optional padding byte
            logger.warning(
                f"WebP chunk overflow: {chunk_type!r} at {offset}, size={chunk_size}, "
                f"would end at {chunk_end}, file size={len(data)}"
            )
            raise ImageInvalidFormatError("Invalid WebP: chunk extends beyond file (possible exploit)")

        # Move to next chunk (chunks are padded to even byte boundary)
        offset = chunk_end + (chunk_size % 2)
        chunk_count += 1

    if chunk_count == 0:
        raise ImageInvalidFormatError("Invalid WebP: no valid chunks found")

    logger.debug(f"WebP validation passed: {chunk_count} chunks")


def validate_size(data: bytes, config: ImageConfig = DEFAULT_CONFIG) -> None:
    """Validate file size"""
    if len(data) > config.max_file_size_bytes:
        raise ImageTooLargeError(
            f"Image size {len(data)} bytes exceeds limit of {config.max_file_size_bytes} bytes"
        )


def validate_format(data: bytes, config: ImageConfig = DEFAULT_CONFIG) -> AllowedFormat:
    """Validate image format using magic bytes"""
    fmt = detect_format(data)
    if fmt is None:
        raise ImageInvalidFormatError("Unable to detect image format from file content")

    if fmt not in config.allowed_formats:
        raise ImageInvalidFormatError(f"Image format '{fmt.value}' is not allowed")

    return fmt


def process_image(
    data: bytes,
    config: ImageConfig = DEFAULT_CONFIG,
) -> ProcessedImage:
    """
    Process and sanitize an image.

    Security steps:
    1. Validate file size
    2. Validate format (magic bytes)
    3. Re-encode to strip EXIF/metadata
    4. Resize if dimensions exceed limits
    5. Generate UUID filename

    Args:
        data: Raw image bytes
        config: Processing configuration

    Returns:
        ProcessedImage with sanitized data

    Raises:
        ImageError: If validation fails
    """
    if not PIL_AVAILABLE:
        raise ImageError("Pillow is required for image processing")

    # Step 1: Validate file size
    validate_size(data, config)

    # Step 2: Validate format
    detected_format = validate_format(data, config)
    logger.info(f"Detected image format: {detected_format.value}")

    # Step 2b: SECURITY - WebP-specific structure validation
    # Defense against CVE-2023-4863 and similar parser exploits
    if detected_format == AllowedFormat.WEBP:
        validate_webp_structure(data)

    # Step 3: Open image with PIL (lazy - doesn't decompress yet)
    # SECURITY: Wrap in broad exception handling to catch any parser crashes
    # Note: True RCE exploits may crash before exception handling, but this catches
    # many malformed file issues that could otherwise leak information
    try:
        img = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:
        # Pillow's built-in protection triggered
        raise ImageDimensionError(f"Decompression bomb detected: {e}")
    except (OSError, IOError) as e:
        # Common for corrupted/malformed images
        logger.warning(f"Image parsing error (possible malformed file): {e}")
        raise ImageInvalidFormatError(f"Failed to decode image: corrupted or malformed")
    except MemoryError as e:
        logger.error(f"Memory error during image parsing: {e}")
        raise ImageDimensionError("Image too large to process")
    except Exception as e:
        # Catch-all for unexpected parser issues
        logger.error(f"Unexpected error during image parsing: {type(e).__name__}: {e}")
        raise ImageInvalidFormatError(f"Failed to decode image: {e}")

    # Step 4: Validate dimensions BEFORE full decompression (defense against bombs)
    # Image.size is available without loading pixel data
    width, height = img.size
    total_pixels = width * height

    logger.debug(f"Image dimensions: {width}x{height} ({total_pixels} pixels)")

    # SECURITY: Reject images that exceed Pillow's MAX_IMAGE_PIXELS (50MP)
    # This is defense-in-depth - Pillow should have already rejected these
    max_allowed_pixels = 50_000_000  # Must match Image.MAX_IMAGE_PIXELS
    if total_pixels > max_allowed_pixels:
        raise ImageDimensionError(
            f"Image has {total_pixels:,} pixels, exceeds safety limit of {max_allowed_pixels:,}"
        )

    # Flag if image needs resize (will be resized after loading)
    # Modern phones like iPhone 15 shoot 48MP - we accept and resize down
    needs_resize = (
        total_pixels > config.max_pixels
        or width > config.max_width
        or height > config.max_height
    )

    if needs_resize:
        logger.info(f"Large image {width}x{height} ({total_pixels:,}px) will be resized")

    # Step 4b: Force load to verify image data is valid (and catch decompression issues)
    # SECURITY: This is where actual decompression happens - most exploits trigger here
    try:
        img.load()
    except Image.DecompressionBombError as e:
        raise ImageDimensionError(f"Decompression bomb detected during load: {e}")
    except (OSError, IOError) as e:
        logger.warning(f"Image load error (possible malformed/truncated file): {e}")
        raise ImageInvalidFormatError(f"Failed to load image: corrupted, truncated, or malformed")
    except MemoryError as e:
        logger.error(f"Memory error during image load: {e}")
        raise ImageDimensionError("Image decompression exceeded memory limit")
    except Exception as e:
        logger.error(f"Unexpected error during image load: {type(e).__name__}: {e}")
        raise ImageInvalidFormatError(f"Failed to load image data: {e}")

    # Step 4c: Additional JPEG integrity check
    # For JPEGs, verify the file ends with the EOI marker (0xFFD9)
    # Truncated JPEGs missing this marker often result in black bands
    if detected_format == AllowedFormat.JPEG:
        # JPEG must end with EOI (End Of Image) marker
        if len(data) < 2 or data[-2:] != b'\xff\xd9':
            # Sometimes there's trailing whitespace/padding
            # Search for EOI in last 10 bytes
            tail = data[-10:] if len(data) >= 10 else data
            if b'\xff\xd9' not in tail:
                logger.warning("JPEG missing EOI marker - likely truncated")
                raise ImageInvalidFormatError("JPEG image is truncated (missing end marker)")

    # Step 5: Resize if needed (dimensions OR pixel count exceeds limits)
    if needs_resize:
        original_size = f"{width}x{height}"

        # Calculate target size - respect both dimension and pixel limits
        target_width = min(width, config.max_width)
        target_height = min(height, config.max_height)

        # If still over pixel limit after dimension resize, scale down further
        target_pixels = target_width * target_height
        if target_pixels > config.max_pixels:
            # Scale factor to fit within pixel budget
            scale = (config.max_pixels / target_pixels) ** 0.5
            target_width = int(target_width * scale)
            target_height = int(target_height * scale)

        img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        width, height = img.size
        logger.info(f"Resized image from {original_size} to {width}x{height}")

    # Step 6: Convert to RGB if necessary (for JPEG output)
    if config.output_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        # Create white background for transparency
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif config.output_format == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")

    # Step 7: Re-encode (strips EXIF and all metadata)
    output = io.BytesIO()
    if config.output_format == "JPEG":
        img.save(output, format="JPEG", quality=config.output_quality, optimize=True)
        content_type = "image/jpeg"
        extension = ".jpg"
    elif config.output_format == "PNG":
        img.save(output, format="PNG", optimize=True)
        content_type = "image/png"
        extension = ".png"
    elif config.output_format == "WEBP":
        img.save(output, format="WEBP", quality=config.output_quality)
        content_type = "image/webp"
        extension = ".webp"
    else:
        # Default to JPEG
        img.save(output, format="JPEG", quality=config.output_quality, optimize=True)
        content_type = "image/jpeg"
        extension = ".jpg"

    output_data = output.getvalue()

    # Step 8: Generate UUID filename
    image_uuid = uuid.uuid4().hex
    filename = f"{image_uuid}{extension}"

    logger.info(
        f"Image processed: uuid={image_uuid}, size={len(output_data)}, "
        f"dimensions={width}x{height}, format={config.output_format}"
    )

    return ProcessedImage(
        uuid=image_uuid,
        filename=filename,
        content_type=content_type,
        size_bytes=len(output_data),
        width=width,
        height=height,
        data=output_data,
    )


def _parse_trusted_suffixes(raw: str) -> list[str]:
    """Parse comma-separated domain suffix list into normalized entries."""
    suffixes = []
    for part in raw.split(","):
        part = part.strip().lower()
        if part:
            # Ensure each suffix starts with a dot for safe matching
            # e.g. "twilio.com" → ".twilio.com" so "evil-twilio.com" won't match
            if not part.startswith("."):
                part = "." + part
            suffixes.append(part)
    return suffixes


def _is_trusted_domain(host: str, trusted_suffixes: list[str]) -> bool:
    """Check if a hostname matches any trusted domain suffix."""
    host = host.lower()
    for suffix in trusted_suffixes:
        # Exact match (host IS the suffix without leading dot)
        if host == suffix.lstrip("."):
            return True
        # Subdomain match (host ends with .suffix)
        if host.endswith(suffix):
            return True
    return False


async def download_media_from_url(
    url: str,
    config: ImageConfig | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> tuple[bytes, str | None]:
    """
    Download media from URL and return raw bytes (no image processing).

    This is the download-only portion of the media pipeline.  It handles
    redirects, auth injection, Content-Length validation, and retries.
    Image validation / re-encoding is handled separately by process_image().

    Security:
    - Validates URL scheme
    - Config-driven redirect trust (TRUSTED_REDIRECT_DOMAIN_SUFFIXES)
    - Authorization stripped on untrusted cross-origin redirects
    - Size limit enforcement
    - Retry with exponential backoff

    Args:
        url: Media URL to download
        config: Image config (used for max_file_size_bytes)
        timeout: Total download timeout in seconds
        max_retries: Number of retry attempts

    Returns:
        (raw_bytes, content_type) tuple
    """
    import asyncio
    import aiohttp
    import base64
    from urllib.parse import urlparse
    from app.config import settings
    from app.infra.http_client import get_fetcher_session

    if config is None:
        config = get_image_config()

    # Parse trusted domain suffixes once per call
    trusted_suffixes = _parse_trusted_suffixes(settings.trusted_redirect_domain_suffixes)

    # Validate URL
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ImageInvalidFormatError(f"Invalid URL scheme: {parsed.scheme}")

    logger.info(f"Downloading media from: {parsed.netloc}")

    # Prepare headers — add auth based on config-driven domain matching
    headers = {}
    origin_host = parsed.netloc.lower()

    if _is_trusted_domain(origin_host, _parse_trusted_suffixes("twilio.com")):
        if settings.twilio_account_sid and settings.twilio_auth_token:
            auth_string = f"{settings.twilio_account_sid}:{settings.twilio_auth_token}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()
            headers["Authorization"] = f"Basic {auth_bytes}"
            logger.debug("Added Twilio Basic Auth for media download")
    elif _is_trusted_domain(origin_host, _parse_trusted_suffixes("fbcdn.net,whatsapp.net,facebook.com")):
        if settings.meta_access_token:
            headers["Authorization"] = f"Bearer {settings.meta_access_token}"
            logger.debug("Added Meta Bearer token for media download")

    last_error = None
    original_host = parsed.netloc

    session = get_fetcher_session()
    client_timeout = aiohttp.ClientTimeout(
        total=timeout,
        connect=15,
        sock_read=timeout,
    )

    for attempt in range(max_retries):
        try:
            current_url = url
            current_headers = dict(headers)

            # Manual redirect loop (max 5 hops)
            for redirect_num in range(5):
                async with session.get(
                    current_url,
                    headers=current_headers,
                    timeout=client_timeout,
                    allow_redirects=False,
                ) as response:
                    # Follow 3xx redirects manually
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ImageError(f"Redirect {response.status} without Location header")

                        # Resolve relative redirects
                        if location.startswith("/"):
                            redirect_parsed = urlparse(current_url)
                            location = f"{redirect_parsed.scheme}://{redirect_parsed.netloc}{location}"

                        redirect_host = urlparse(location).netloc

                        logger.debug(
                            f"Redirect hop {redirect_num + 1}: "
                            f"{response.status} {urlparse(current_url).netloc} → {redirect_host}"
                        )

                        if redirect_host != original_host:
                            # Cross-origin redirect — decide whether to keep auth
                            if (
                                settings.keep_auth_on_trusted_redirects
                                and _is_trusted_domain(redirect_host, trusted_suffixes)
                            ):
                                logger.debug(
                                    f"Trusted cross-origin redirect → {redirect_host}, "
                                    f"keeping Authorization header"
                                )
                            else:
                                current_headers = {
                                    k: v for k, v in current_headers.items()
                                    if k.lower() != "authorization"
                                }
                                logger.debug(
                                    f"Untrusted cross-origin redirect → {redirect_host}, "
                                    f"stripped Authorization header"
                                )

                        current_url = location
                        continue  # next redirect hop

                    if response.status != 200:
                        raise ImageError(f"Failed to download media: HTTP {response.status}")

                    # Log response headers for debugging download issues
                    logger.debug(
                        f"Download response: status={response.status}, "
                        f"Content-Length={response.headers.get('Content-Length', 'absent')}, "
                        f"Content-Type={response.headers.get('Content-Type', 'absent')}"
                    )

                    content_type = response.headers.get("Content-Type")

                    # Check Content-Length header for size limit
                    content_length_header = response.headers.get("Content-Length")
                    expected_size = int(content_length_header) if content_length_header else None

                    if expected_size:
                        size_mb = expected_size / (1024 * 1024)
                        logger.info(f"Downloading {size_mb:.1f}MB media (attempt {attempt + 1})")

                    if expected_size and expected_size > config.max_file_size_bytes:
                        raise ImageTooLargeError(
                            f"Media size {expected_size} bytes ({expected_size / 1024 / 1024:.1f}MB) exceeds limit"
                        )

                    # Read full content
                    data = await response.read()

                    if len(data) > config.max_file_size_bytes:
                        raise ImageTooLargeError("Media size exceeds limit")

                    # IMPORTANT: Verify we received complete data
                    # If Content-Length was provided, ensure we got all bytes
                    # Incomplete downloads cause black bands at bottom of images
                    if expected_size and len(data) < expected_size:
                        percent = (len(data) / expected_size) * 100
                        logger.warning(
                            f"Incomplete media download (attempt {attempt + 1}/{max_retries}): "
                            f"expected={expected_size}, received={len(data)} ({percent:.1f}%)"
                        )
                        raise ImageError(
                            f"Incomplete download: received {len(data)} of {expected_size} bytes ({percent:.0f}%)"
                        )

                    # Success - got complete data
                    size_kb = len(data) / 1024
                    logger.info(f"Media download complete: {size_kb:.0f}KB" + (f" (attempt {attempt + 1})" if attempt > 0 else ""))

                    return data, content_type

            # If we exit the redirect loop without returning
            raise ImageError(f"Too many redirects (>5) downloading media")

        except (aiohttp.ClientError, ImageError) as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                logger.warning(
                    f"Media download failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait_time}s: {e}"
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Media download failed after {max_retries} attempts: {e}")

    # All retries exhausted
    raise ImageError(f"Failed to download media after {max_retries} attempts: {last_error}")


async def process_image_from_url(
    url: str,
    config: ImageConfig | None = None,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> ProcessedImage:
    """
    Download and process an image from URL with retry support.

    Convenience wrapper that calls download_media_from_url() then process_image().
    All existing callers see no change in behavior.

    Args:
        url: Image URL
        config: Processing configuration (uses settings if None)
        timeout: Download timeout in seconds (default 60s for large images)
        max_retries: Number of retry attempts for failed downloads

    Returns:
        ProcessedImage with sanitized data
    """
    if config is None:
        config = get_image_config()

    data, _content_type = await download_media_from_url(url, config, timeout, max_retries)
    return process_image(data, config)


def get_image_info(data: bytes) -> dict:
    """
    Get image information without full processing.
    Useful for validation before accepting upload.
    """
    if not PIL_AVAILABLE:
        return {"error": "Pillow not available"}

    try:
        fmt = detect_format(data)
        img = Image.open(io.BytesIO(data))
        width, height = img.size

        return {
            "format": fmt.value if fmt else "unknown",
            "width": width,
            "height": height,
            "pixels": width * height,
            "size_bytes": len(data),
            "mode": img.mode,
        }
    except Exception as e:
        return {"error": str(e)}
