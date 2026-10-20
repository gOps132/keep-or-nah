from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

import keep_or_nah_core
from burst_clustering import BurstClusterer, PhotoBurstInfo


def test_rust_sharpness_and_hash_functions_exist() -> None:
    assert hasattr(keep_or_nah_core, "compute_sharpness")
    assert hasattr(keep_or_nah_core, "compute_image_hash")


def test_sharpness_detects_blur() -> None:
    # Create a sharp image with high-contrast sharp edges (checkerboard)
    width, height = 100, 100
    sharp_img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sharp_img)
    for x in range(0, width, 10):
        for y in range(0, height, 10):
            if (x // 10 + y // 10) % 2 == 0:
                draw.rectangle([x, y, x + 10, y + 10], fill=(0, 0, 0, 255))

    # Create a blurred version of the exact same image
    blurry_img = sharp_img.filter(ImageFilter.GaussianBlur(radius=5))

    sharp_bytes = sharp_img.tobytes()
    blurry_bytes = blurry_img.tobytes()

    sharp_score = keep_or_nah_core.compute_sharpness(sharp_bytes, width, height)
    blurry_score = keep_or_nah_core.compute_sharpness(blurry_bytes, width, height)

    assert isinstance(sharp_score, float)
    assert isinstance(blurry_score, float)
    assert sharp_score > blurry_score * 3, (
        f"Expected sharp ({sharp_score}) >> blurry ({blurry_score})"
    )


def test_perceptual_hash_similar_vs_different() -> None:
    width, height = 64, 64
    img1 = Image.new("RGBA", (width, height), (200, 50, 50, 255))
    draw1 = ImageDraw.Draw(img1)
    draw1.rectangle([10, 10, 50, 50], fill=(50, 200, 50, 255))

    # Slightly modified image (same structure with slight noise)
    img2 = img1.copy()
    draw2 = ImageDraw.Draw(img2)
    draw2.rectangle([11, 11, 49, 49], fill=(50, 205, 50, 255))

    # Completely different image (vertical stripes)
    img3 = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    draw3 = ImageDraw.Draw(img3)
    for x in range(0, width, 4):
        draw3.line([(x, 0), (x, height)], fill=(255, 255, 255, 255))

    h1 = keep_or_nah_core.compute_image_hash(img1.tobytes(), width, height)
    h2 = keep_or_nah_core.compute_image_hash(img2.tobytes(), width, height)
    h3 = keep_or_nah_core.compute_image_hash(img3.tobytes(), width, height)

    assert isinstance(h1, int)
    assert isinstance(h2, int)
    assert isinstance(h3, int)

    # Hamming distance between h1 and h2 should be small
    dist_1_2 = (h1 ^ h2).bit_count()
    dist_1_3 = (h1 ^ h3).bit_count()

    assert dist_1_2 <= 5, f"Expected small distance between similar images, got {dist_1_2}"
    assert dist_1_3 > 15, f"Expected large distance between different images, got {dist_1_3}"


def test_burst_clusterer_identifies_best_shot() -> None:
    clusterer = BurstClusterer(time_threshold_seconds=2.0, hash_distance_threshold=10)

    # 3 photos taken within 1 second of each other with identical hash
    p1 = PhotoBurstInfo(
        path=Path("/photos/burst1.jpg"),
        timestamp=100.0,
        image_hash=0x1234567890ABCDEF,
        sharpness=50.0,
    )
    p2 = PhotoBurstInfo(
        path=Path("/photos/burst2.jpg"),
        timestamp=100.5,
        image_hash=0x1234567890ABCDEF,
        sharpness=120.0,
    )
    p3 = PhotoBurstInfo(
        path=Path("/photos/burst3.jpg"),
        timestamp=101.0,
        image_hash=0x1234567890ABCDEF,
        sharpness=80.0,
    )

    # 1 independent photo taken 10 seconds later with different hash
    p4 = PhotoBurstInfo(
        path=Path("/photos/solo.jpg"),
        timestamp=115.0,
        image_hash=0xFFFFFFFFFFFFFFFF,
        sharpness=95.0,
    )

    clusters = clusterer.cluster([p1, p2, p3, p4])
    assert len(clusters) == 2

    burst_cluster = next(c for c in clusters if len(c.photos) == 3)
    assert burst_cluster.is_burst
    assert burst_cluster.best_shot == Path("/photos/burst2.jpg")  # highest sharpness

    solo_cluster = next(c for c in clusters if len(c.photos) == 1)
    assert not solo_cluster.is_burst
    assert solo_cluster.best_shot == Path("/photos/solo.jpg")
