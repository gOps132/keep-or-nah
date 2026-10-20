use std::fs::File;
use std::io::BufReader;
use std::path::Path;

use fast_image_resize as fr;
use image::{DynamicImage, ImageError};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PreviewStage {
    Fast,
    Full,
}

#[derive(Clone)]
pub struct LoadedImage {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
}

impl LoadedImage {
    pub fn byte_size(&self) -> usize {
        self.rgba.len()
    }
}

pub fn read_orientation(path: &Path) -> u32 {
    let file = match File::open(path) {
        Ok(f) => f,
        Err(_) => return 1,
    };
    let mut bufreader = BufReader::new(file);
    let exifreader = exif::Reader::new();
    let exif = match exifreader.read_from_container(&mut bufreader) {
        Ok(exif) => exif,
        Err(_) => return 1,
    };
    exif.get_field(exif::Tag::Orientation, exif::In::PRIMARY)
        .and_then(|f| f.value.get_uint(0))
        .unwrap_or(1)
}

pub fn apply_orientation(img: DynamicImage, orientation: u32) -> DynamicImage {
    match orientation {
        2 => img.fliph(),
        3 => img.rotate180(),
        4 => img.flipv(),
        5 => {
            let rotated = img.rotate270();
            rotated.fliph()
        }
        6 => img.rotate90(),
        7 => {
            let rotated = img.rotate90();
            rotated.fliph()
        }
        8 => img.rotate270(),
        _ => img,
    }
}

pub fn load_and_orient(path: &Path) -> Result<LoadedImage, ImageError> {
    let orientation = read_orientation(path);
    let img = image::open(path)?;
    let oriented = apply_orientation(img, orientation);
    let rgba = oriented.into_rgba8();
    let (width, height) = rgba.dimensions();
    Ok(LoadedImage {
        width,
        height,
        rgba: rgba.into_raw(),
    })
}

pub fn render_fit(
    source: &LoadedImage,
    viewport_width: u32,
    viewport_height: u32,
    stage: PreviewStage,
) -> Result<LoadedImage, String> {
    if viewport_width < 8 || viewport_height < 8 {
        return Ok(LoadedImage {
            width: source.width,
            height: source.height,
            rgba: source.rgba.clone(),
        });
    }

    let fit_scale = (viewport_width as f64 / source.width as f64)
        .min(viewport_height as f64 / source.height as f64);
    let display_width = ((source.width as f64 * fit_scale).round() as u32).max(1);
    let display_height = ((source.height as f64 * fit_scale).round() as u32).max(1);

    if display_width == source.width && display_height == source.height {
        return Ok(LoadedImage {
            width: source.width,
            height: source.height,
            rgba: source.rgba.clone(),
        });
    }

    let src_image = fr::images::ImageRef::new(
        source.width,
        source.height,
        &source.rgba,
        fr::PixelType::U8x4,
    )
    .map_err(|e| format!("Failed to create source image buffer: {e}"))?;

    let mut dst_image = fr::images::Image::new(display_width, display_height, fr::PixelType::U8x4);

    let mut resizer = fr::Resizer::new();
    let alg = match stage {
        PreviewStage::Fast => fr::ResizeAlg::Convolution(fr::FilterType::Bilinear),
        PreviewStage::Full => fr::ResizeAlg::Convolution(fr::FilterType::Lanczos3),
    };

    resizer
        .resize(
            &src_image,
            &mut dst_image,
            &fr::ResizeOptions::new().resize_alg(alg),
        )
        .map_err(|e| format!("Failed to resize image: {e}"))?;

    Ok(LoadedImage {
        width: display_width,
        height: display_height,
        rgba: dst_image.into_vec(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgba, RgbaImage};
    use tempfile::TempDir;

    /// A 2x3 image whose pixels encode their own position, so that every
    /// geometric operation is observable.
    fn position_image() -> DynamicImage {
        let image = RgbaImage::from_fn(2, 3, |x, y| Rgba([(x * 10) as u8, (y * 10) as u8, 7, 255]));
        DynamicImage::ImageRgba8(image)
    }

    fn write_png(dir: &Path, name: &str, width: u32, height: u32) -> std::path::PathBuf {
        let path = dir.join(name);
        let image = RgbaImage::from_pixel(width, height, Rgba([10, 20, 30, 255]));
        DynamicImage::ImageRgba8(image)
            .save(&path)
            .expect("write png fixture");
        path
    }

    /// The source pixel that ends up at (x, y) of the oriented image, derived
    /// from the operations the loader applies for each EXIF orientation.
    fn source_pixel(orientation: u32, x: u32, y: u32, width: u32, height: u32) -> (u32, u32) {
        match orientation {
            1 => (x, y),
            2 => (width - 1 - x, y),
            3 => (width - 1 - x, height - 1 - y),
            4 => (x, height - 1 - y),
            5 => (width - 1 - y, height - 1 - x),
            6 => (y, height - 1 - x),
            7 => (y, x),
            8 => (width - 1 - y, x),
            _ => (x, y),
        }
    }

    #[test]
    fn read_orientation_falls_back_to_one_without_exif() {
        let dir = TempDir::new().unwrap();
        let path = write_png(dir.path(), "plain.png", 4, 4);

        assert_eq!(read_orientation(&path), 1);
    }

    #[test]
    fn read_orientation_of_a_missing_file_is_one() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("missing.png");

        assert_eq!(read_orientation(&missing), 1);
    }

    #[test]
    fn orientation_one_keeps_the_image_untouched() {
        let source = position_image();
        let oriented = apply_orientation(source.clone(), 1).into_rgba8();

        assert_eq!(oriented.dimensions(), (2, 3));
        assert_eq!(oriented.into_raw(), source.into_rgba8().into_raw());
    }

    #[test]
    fn every_orientation_maps_the_source_pixels_as_exif_defines() {
        let width = 2;
        let height = 3;
        for orientation in 1..=8u32 {
            let source = position_image();
            let oriented = apply_orientation(source.clone(), orientation).into_rgba8();
            let (oriented_width, oriented_height) = oriented.dimensions();

            let expected_dimensions = if matches!(orientation, 5..=8) {
                (height, width)
            } else {
                (width, height)
            };
            assert_eq!(
                (oriented_width, oriented_height),
                expected_dimensions,
                "wrong dimensions for orientation {orientation}"
            );

            for y in 0..oriented_height {
                for x in 0..oriented_width {
                    let (source_x, source_y) = source_pixel(orientation, x, y, width, height);
                    let expected = Rgba([(source_x * 10) as u8, (source_y * 10) as u8, 7, 255]);
                    assert_eq!(
                        oriented.get_pixel(x, y),
                        &expected,
                        "orientation {orientation} misplaced the pixel at ({x}, {y})"
                    );
                }
            }
        }
    }

    #[test]
    fn an_unknown_orientation_is_treated_as_normal() {
        let source = position_image();
        let oriented = apply_orientation(source.clone(), 42).into_rgba8();

        assert_eq!(oriented.into_raw(), source.into_rgba8().into_raw());
    }

    #[test]
    fn load_and_orient_returns_an_rgba_buffer() {
        let dir = TempDir::new().unwrap();
        let path = write_png(dir.path(), "photo.png", 12, 7);

        let loaded = load_and_orient(&path).expect("image loads");

        assert_eq!((loaded.width, loaded.height), (12, 7));
        assert_eq!(loaded.rgba.len(), 12 * 7 * 4);
        assert_eq!(loaded.byte_size(), loaded.rgba.len());
    }

    #[test]
    fn load_and_orient_reports_a_missing_file() {
        let dir = TempDir::new().unwrap();
        let missing = dir.path().join("missing.png");

        assert!(load_and_orient(&missing).is_err());
    }

    #[test]
    fn render_fit_returns_the_source_for_a_tiny_viewport() {
        let source = LoadedImage {
            width: 100,
            height: 50,
            rgba: vec![1u8; 100 * 50 * 4],
        };

        let rendered = render_fit(&source, 4, 4, PreviewStage::Full).expect("render");

        assert_eq!((rendered.width, rendered.height), (100, 50));
        assert_eq!(rendered.rgba, source.rgba);
    }

    #[test]
    fn render_fit_keeps_a_source_that_already_matches_the_viewport() {
        let source = LoadedImage {
            width: 100,
            height: 50,
            rgba: vec![1u8; 100 * 50 * 4],
        };

        let rendered = render_fit(&source, 100, 50, PreviewStage::Full).expect("render");

        assert_eq!((rendered.width, rendered.height), (100, 50));
        assert_eq!(rendered.rgba, source.rgba);
    }

    #[test]
    fn render_fit_scales_a_small_source_up_to_the_viewport() {
        let source = LoadedImage {
            width: 40,
            height: 20,
            rgba: vec![1u8; 40 * 20 * 4],
        };

        let rendered = render_fit(&source, 100, 100, PreviewStage::Full).expect("render");

        // The 2:1 aspect ratio is kept while the image grows to the width of
        // the viewport.
        assert_eq!((rendered.width, rendered.height), (100, 50));
        assert_eq!(rendered.rgba.len(), 100 * 50 * 4);
    }

    #[test]
    fn render_fit_scales_a_wide_source_down_to_the_viewport() {
        let source = LoadedImage {
            width: 200,
            height: 100,
            rgba: vec![128u8; 200 * 100 * 4],
        };

        let rendered = render_fit(&source, 50, 50, PreviewStage::Full).expect("render");

        assert_eq!((rendered.width, rendered.height), (50, 25));
        assert_eq!(rendered.rgba.len(), 50 * 25 * 4);
    }

    #[test]
    fn render_fit_scales_a_tall_source_down_to_the_viewport() {
        let source = LoadedImage {
            width: 100,
            height: 200,
            rgba: vec![128u8; 100 * 200 * 4],
        };

        let rendered = render_fit(&source, 50, 50, PreviewStage::Full).expect("render");

        assert_eq!((rendered.width, rendered.height), (25, 50));
        assert_eq!(rendered.rgba.len(), 25 * 50 * 4);
    }

    #[test]
    fn render_fit_never_produces_an_empty_image() {
        let source = LoadedImage {
            width: 1000,
            height: 3,
            rgba: vec![128u8; 1000 * 3 * 4],
        };

        let rendered = render_fit(&source, 8, 8, PreviewStage::Fast).expect("render");

        assert!(rendered.width >= 1);
        assert!(rendered.height >= 1);
        assert_eq!(
            rendered.rgba.len(),
            rendered.width as usize * rendered.height as usize * 4
        );
    }
}
