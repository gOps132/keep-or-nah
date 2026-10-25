use keep_or_nah_core::analysis::{compute_image_hash, compute_sharpness};

#[test]
fn test_image_hash_identical_buffers_have_zero_hamming_distance() {
    let width = 32;
    let height = 32;
    let mut rgba = vec![0u8; (width * height * 4) as usize];
    for y in 0..height {
        for x in 0..width {
            let idx = ((y * width + x) * 4) as usize;
            rgba[idx] = (x * 8) as u8;
            rgba[idx + 1] = (y * 8) as u8;
            rgba[idx + 2] = 128;
            rgba[idx + 3] = 255;
        }
    }

    let hash1 = compute_image_hash(&rgba, width, height);
    let hash2 = compute_image_hash(&rgba, width, height);

    let distance = (hash1 ^ hash2).count_ones();
    assert_eq!(distance, 0);
}

#[test]
fn test_image_hash_different_images_have_nonzero_hamming_distance() {
    let width = 32;
    let height = 32;

    // Gradient left-to-right
    let mut grad_lr = vec![0u8; (width * height * 4) as usize];
    for y in 0..height {
        for x in 0..width {
            let idx = ((y * width + x) * 4) as usize;
            grad_lr[idx] = (x * 8) as u8;
            grad_lr[idx + 1] = (x * 8) as u8;
            grad_lr[idx + 2] = (x * 8) as u8;
            grad_lr[idx + 3] = 255;
        }
    }

    // Gradient right-to-left
    let mut grad_rl = vec![0u8; (width * height * 4) as usize];
    for y in 0..height {
        for x in 0..width {
            let idx = ((y * width + x) * 4) as usize;
            grad_rl[idx] = ((width - 1 - x) * 8) as u8;
            grad_rl[idx + 1] = ((width - 1 - x) * 8) as u8;
            grad_rl[idx + 2] = ((width - 1 - x) * 8) as u8;
            grad_rl[idx + 3] = 255;
        }
    }

    let hash_lr = compute_image_hash(&grad_lr, width, height);
    let hash_rl = compute_image_hash(&grad_rl, width, height);

    let distance = (hash_lr ^ hash_rl).count_ones();
    assert!(
        distance > 10,
        "Opposite gradients should have significant Hamming distance"
    );
}

#[test]
fn test_laplacian_sharpness_drops_when_blurred() {
    let width = 32;
    let height = 32;

    // High contrast sharp checkerboard pattern
    let mut sharp = vec![0u8; (width * height * 4) as usize];
    for y in 0..height {
        for x in 0..width {
            let idx = ((y * width + x) * 4) as usize;
            let val = if (x / 2 + y / 2) % 2 == 0 { 255 } else { 0 };
            sharp[idx] = val;
            sharp[idx + 1] = val;
            sharp[idx + 2] = val;
            sharp[idx + 3] = 255;
        }
    }

    // Blurred / uniform flat buffer
    let mut flat = vec![0u8; (width * height * 4) as usize];
    for y in 0..height {
        for x in 0..width {
            let idx = ((y * width + x) * 4) as usize;
            flat[idx] = 128;
            flat[idx + 1] = 128;
            flat[idx + 2] = 128;
            flat[idx + 3] = 255;
        }
    }

    let sharp_score = compute_sharpness(&sharp, width, height);
    let flat_score = compute_sharpness(&flat, width, height);

    assert!(
        sharp_score > 100.0,
        "Sharp pattern should have high variance"
    );
    assert_eq!(
        flat_score, 0.0,
        "Flat buffer should have 0.0 sharpness variance"
    );
    assert!(sharp_score > flat_score);
}
