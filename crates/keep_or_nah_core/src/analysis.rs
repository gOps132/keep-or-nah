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

    /// Build an RGBA buffer where every pixel is the given grey level.
    fn solid(width: usize, height: usize, value: u8) -> Vec<u8> {
        let mut buffer = vec![0u8; width * height * 4];
        for pixel in buffer.chunks_exact_mut(4) {
            pixel[0] = value;
            pixel[1] = value;
            pixel[2] = value;
            pixel[3] = 255;
        }
        buffer
    }

    /// Build a checkerboard RGBA buffer.
    fn checkerboard(width: usize, height: usize) -> Vec<u8> {
        let mut buffer = vec![0u8; width * height * 4];
        for y in 0..height {
            for x in 0..width {
                let value = if (x + y) % 2 == 0 { 255 } else { 0 };
                let index = (y * width + x) * 4;
                buffer[index] = value;
                buffer[index + 1] = value;
                buffer[index + 2] = value;
                buffer[index + 3] = 255;
            }
        }
        buffer
    }

    /// Box blur a RGBA buffer with a 3x3 kernel.
    fn box_blur(source: &[u8], width: usize, height: usize) -> Vec<u8> {
        let mut blurred = vec![0u8; source.len()];
        for y in 0..height {
            for x in 0..width {
                let mut sum = 0u32;
                let mut count = 0u32;
                for dy in -1i32..=1 {
                    for dx in -1i32..=1 {
                        let ny = y as i32 + dy;
                        let nx = x as i32 + dx;
                        if ny < 0 || nx < 0 || ny >= height as i32 || nx >= width as i32 {
                            continue;
                        }
                        let index = (ny as usize * width + nx as usize) * 4;
                        sum += source[index] as u32;
                        count += 1;
                    }
                }
                let index = (y * width + x) * 4;
                blurred[index] = (sum / count) as u8;
                blurred[index + 1] = blurred[index];
                blurred[index + 2] = blurred[index];
                blurred[index + 3] = 255;
            }
        }
        blurred
    }

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

    #[test]
    fn test_truncated_buffer_is_rejected() {
        // The buffer is shorter than width * height * 4, so it is not analysed.
        let truncated = vec![255u8; 10];
        assert_eq!(compute_sharpness(&truncated, 4, 4), 0.0);
        assert_eq!(compute_image_hash(&truncated, 4, 4), 0);
    }

    #[test]
    fn test_images_below_three_pixels_have_no_sharpness() {
        // The Laplacian needs a 3x3 neighbourhood to work on.
        let small = solid(2, 2, 200);
        assert_eq!(compute_sharpness(&small, 2, 2), 0.0);
        let strip = solid(2, 8, 200);
        assert_eq!(compute_sharpness(&strip, 2, 8), 0.0);
    }

    #[test]
    fn test_sharpness_falls_when_the_image_is_blurred() {
        let width = 20;
        let height = 20;
        let sharp = checkerboard(width, height);
        let blurred = box_blur(&sharp, width, height);

        let sharp_score = compute_sharpness(&sharp, width as u32, height as u32);
        let blurred_score = compute_sharpness(&blurred, width as u32, height as u32);

        assert!(
            sharp_score > 1000.0,
            "Expected high variance, got {sharp_score}"
        );
        assert!(
            blurred_score < sharp_score,
            "Blurred image scored {blurred_score}, sharp image scored {sharp_score}"
        );
    }

    #[test]
    fn test_sharpness_of_a_smooth_gradient_is_lower_than_a_hard_edge() {
        let width = 20;
        let height = 20;
        let mut gradient = vec![0u8; width * height * 4];
        for y in 0..height {
            for x in 0..width {
                let value = ((x * 255) / (width - 1)) as u8;
                let index = (y * width + x) * 4;
                gradient[index] = value;
                gradient[index + 1] = value;
                gradient[index + 2] = value;
                gradient[index + 3] = 255;
            }
        }
        let mut edge = vec![0u8; width * height * 4];
        for y in 0..height {
            for x in 0..width {
                let value = if x < width / 2 { 0 } else { 255 };
                let index = (y * width + x) * 4;
                edge[index] = value;
                edge[index + 1] = value;
                edge[index + 2] = value;
                edge[index + 3] = 255;
            }
        }

        let gradient_score = compute_sharpness(&gradient, width as u32, height as u32);
        let edge_score = compute_sharpness(&edge, width as u32, height as u32);

        assert!(edge_score > 0.0, "A hard edge must produce detail");
        assert!(
            gradient_score < edge_score,
            "Gradient scored {gradient_score}, hard edge scored {edge_score}"
        );
    }

    #[test]
    fn test_hash_encodes_the_left_to_right_luminance_order() {
        // A 9x8 buffer maps one to one onto the 9x8 hash grid, so a single
        // bright column decides every comparison of its row.
        let width = 9;
        let height = 8;
        let mut bright_first_column = vec![0u8; width * height * 4];
        for y in 0..height {
            let index = (y * width) * 4;
            bright_first_column[index] = 255;
            bright_first_column[index + 1] = 255;
            bright_first_column[index + 2] = 255;
            bright_first_column[index + 3] = 255;
        }

        // The left neighbour of every comparison is brighter, so the first
        // bit of every row is set.
        let hash = compute_image_hash(&bright_first_column, width as u32, height as u32);
        assert_eq!(hash, 0x0101_0101_0101_0101);
    }

    #[test]
    fn test_hash_of_a_dark_to_bright_gradient_is_zero() {
        // The right hand side of every comparison is at least as bright as the
        // left hand side, so no bit is ever set.
        let width = 9;
        let height = 8;
        let mut bright_last_column = vec![0u8; width * height * 4];
        for y in 0..height {
            let index = (y * width + width - 1) * 4;
            bright_last_column[index] = 255;
            bright_last_column[index + 1] = 255;
            bright_last_column[index + 2] = 255;
            bright_last_column[index + 3] = 255;
        }

        assert_eq!(
            compute_image_hash(&bright_last_column, width as u32, height as u32),
            0
        );
    }

    #[test]
    fn test_hash_is_stable_across_repeated_calls() {
        let width = 18;
        let height = 16;
        let mut img = vec![0u8; width * height * 4];
        for (index, byte) in img.iter_mut().enumerate() {
            *byte = (index % 256) as u8;
        }

        let first = compute_image_hash(&img, width as u32, height as u32);
        let second = compute_image_hash(&img, width as u32, height as u32);
        assert_eq!(first, second);
    }
}
