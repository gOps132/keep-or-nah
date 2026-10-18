/// High-performance image analysis: Laplacian blur detection and difference hash (dHash)

/// Compute the Laplacian variance (sharpness score) of an RGBA image buffer.
/// Higher values indicate sharper edges and more fine detail.
pub fn compute_sharpness(rgba: &[u8], width: u32, height: u32) -> f32 {
    let (w, h) = (width as usize, height as usize);
    if w < 3 || h < 3 || rgba.len() < w * h * 4 {
        return 0.0;
    }

    // Convert RGBA to luminance buffer: Y = (77*R + 150*G + 29*B) >> 8
    let mut lum = Vec::with_capacity(w * h);
    for chunk in rgba[..w * h * 4].chunks_exact(4) {
        let r = chunk[0] as u32;
        let g = chunk[1] as u32;
        let b = chunk[2] as u32;
        lum.push(((77 * r + 150 * g + 29 * b) >> 8) as i32);
    }

    let mut sum: f64 = 0.0;
    let mut sum_sq: f64 = 0.0;
    let mut count: usize = 0;

    // Apply 3x3 discrete Laplacian kernel:
    // [ 0,  1,  0]
    // [ 1, -4,  1]
    // [ 0,  1,  0]
    for y in 1..(h - 1) {
        let row_curr = y * w;
        let row_prev = (y - 1) * w;
        let row_next = (y + 1) * w;

        for x in 1..(w - 1) {
            let center = lum[row_curr + x];
            let top = lum[row_prev + x];
            let bottom = lum[row_next + x];
            let left = lum[row_curr + x - 1];
            let right = lum[row_curr + x + 1];

            let lap = (top + bottom + left + right) - 4 * center;
            let val = lap as f64;
            sum += val;
            sum_sq += val * val;
            count += 1;
        }
    }

    if count == 0 {
        return 0.0;
    }

    let n = count as f64;
    let mean = sum / n;
    let variance = (sum_sq / n) - (mean * mean);
    variance.max(0.0) as f32
}

/// Compute a 64-bit difference hash (dHash) for perceptual similarity comparison.
/// Downsamples the image to a 9x8 luminance grid and compares adjacent horizontal pixels.
pub fn compute_image_hash(rgba: &[u8], width: u32, height: u32) -> u64 {
    let (w, h) = (width as usize, height as usize);
    if w == 0 || h == 0 || rgba.len() < w * h * 4 {
        return 0;
    }

    // Downsample to 9 columns x 8 rows using area averaging
    const GRID_W: usize = 9;
    const GRID_H: usize = 8;
    let mut grid = [0u32; GRID_W * GRID_H];

    for gy in 0..GRID_H {
        let y_start = gy * h / GRID_H;
        let y_end = ((gy + 1) * h / GRID_H).max(y_start + 1);

        for gx in 0..GRID_W {
            let x_start = gx * w / GRID_W;
            let x_end = ((gx + 1) * w / GRID_W).max(x_start + 1);

            let mut lum_sum: u64 = 0;
            let mut pixel_count: u64 = 0;

            for y in y_start..y_end {
                let row_offset = y * w;
                for x in x_start..x_end {
                    let idx = (row_offset + x) * 4;
                    if idx + 2 < rgba.len() {
                        let r = rgba[idx] as u64;
                        let g = rgba[idx + 1] as u64;
                        let b = rgba[idx + 2] as u64;
                        lum_sum += (77 * r + 150 * g + 29 * b) >> 8;
                        pixel_count += 1;
                    }
                }
            }

            grid[gy * GRID_W + gx] = if pixel_count > 0 {
                (lum_sum / pixel_count) as u32
            } else {
                0
            };
        }
    }

    // Compare adjacent horizontal pixels (8 comparisons per row x 8 rows = 64 bits)
    let mut hash: u64 = 0;
    for y in 0..GRID_H {
        for x in 0..8 {
            let left = grid[y * GRID_W + x];
            let right = grid[y * GRID_W + x + 1];
            if left > right {
                hash |= 1 << (y * 8 + x);
            }
        }
    }

    hash
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty_or_small_buffer_returns_zero() {
        assert_eq!(compute_sharpness(&[], 0, 0), 0.0);
        assert_eq!(compute_sharpness(&[255; 16], 2, 2), 0.0);
        assert_eq!(compute_image_hash(&[], 0, 0), 0);
    }

    #[test]
    fn test_uniform_buffer_has_zero_sharpness() {
        let w = 20;
        let h = 20;
        let uniform = vec![128u8; w * h * 4];
        assert_eq!(compute_sharpness(&uniform, w as u32, h as u32), 0.0);
    }

    #[test]
    fn test_sharpness_differentiates_edges() {
        let w = 20;
        let h = 20;
        let mut sharp = vec![0u8; w * h * 4];
        for y in 0..h {
            for x in 0..w {
                let val = if (x + y) % 2 == 0 { 255 } else { 0 };
                let idx = (y * w + x) * 4;
                sharp[idx] = val;
                sharp[idx + 1] = val;
                sharp[idx + 2] = val;
                sharp[idx + 3] = 255;
            }
        }
        let score = compute_sharpness(&sharp, w as u32, h as u32);
        assert!(score > 1000.0, "Expected high variance, got {score}");
    }

    #[test]
    fn test_hash_identical_images_have_zero_hamming_distance() {
        let w = 18;
        let h = 16;
        let mut img = vec![0u8; w * h * 4];
        for (i, byte) in img.iter_mut().enumerate() {
            *byte = (i % 256) as u8;
        }
        let h1 = compute_image_hash(&img, w as u32, h as u32);
        let h2 = compute_image_hash(&img, w as u32, h as u32);
        assert_eq!(h1, h2);
    }
}
