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

    let mut dst_image = fr::images::Image::new(
        display_width,
        display_height,
        fr::PixelType::U8x4,
    );

    let mut resizer = fr::Resizer::new();
    let alg = match stage {
        PreviewStage::Fast => fr::ResizeAlg::Convolution(fr::FilterType::Bilinear),
        PreviewStage::Full => fr::ResizeAlg::Convolution(fr::FilterType::Lanczos3),
    };

    resizer
        .resize(&src_image, &mut dst_image, &fr::ResizeOptions::new().resize_alg(alg))
        .map_err(|e| format!("Failed to resize image: {e}"))?;

    Ok(LoadedImage {
        width: display_width,
        height: display_height,
        rgba: dst_image.into_vec(),
    })
}
