//! Hardware-accelerated RAW demosaicing engine.
//!
//! On macOS, leverages Apple's `ImageIO` and `CoreGraphics` frameworks to perform
//! hardware-accelerated demosaicing of camera RAW files (Sony ARW, Canon CR2/CR3,
//! Nikon NEF, DNG, etc.) with camera "As-Shot" white balance and standard color transforms.
//!
//! On non-macOS platforms or as a fallback, falls back to standard image decoding or
//! embedded preview extraction.

use image::DynamicImage;
use std::path::Path;

#[cfg(target_os = "macos")]
mod macos_imageio {
    use image::{DynamicImage, RgbaImage};
    use std::ffi::c_void;
    use std::path::Path;
    use std::ptr;

    #[repr(C)]
    struct __CFURL(c_void);
    type CFURLRef = *const __CFURL;

    #[repr(C)]
    struct __CFDictionary(c_void);
    type CFDictionaryRef = *const __CFDictionary;

    #[repr(C)]
    struct __CFString(c_void);
    type CFStringRef = *const __CFString;

    #[repr(C)]
    struct __CGImageSource(c_void);
    type CGImageSourceRef = *const __CGImageSource;

    #[repr(C)]
    struct __CGImage(c_void);
    type CGImageRef = *const __CGImage;

    #[repr(C)]
    struct __CGContext(c_void);
    type CGContextRef = *mut __CGContext;

    #[repr(C)]
    struct __CGColorSpace(c_void);
    type CGColorSpaceRef = *const __CGColorSpace;

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct CGPoint {
        x: f64,
        y: f64,
    }

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct CGSize {
        width: f64,
        height: f64,
    }

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct CGRect {
        origin: CGPoint,
        size: CGSize,
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFURLCreateFromFileSystemRepresentation(
            allocator: *const c_void,
            buffer: *const u8,
            buf_len: isize,
            is_directory: bool,
        ) -> CFURLRef;
        fn CFRelease(cf: *const c_void);
    }

    #[link(name = "ImageIO", kind = "framework")]
    extern "C" {
        fn CGImageSourceCreateWithURL(url: CFURLRef, options: CFDictionaryRef) -> CGImageSourceRef;
        fn CGImageSourceCreateImageAtIndex(
            isrc: CGImageSourceRef,
            index: usize,
            options: CFDictionaryRef,
        ) -> CGImageRef;
    }

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        static kCGColorSpaceSRGB: CFStringRef;
        fn CGColorSpaceCreateWithName(name: CFStringRef) -> CGColorSpaceRef;
        fn CGColorSpaceCreateDeviceRGB() -> CGColorSpaceRef;
        fn CGColorSpaceRelease(space: CGColorSpaceRef);
        fn CGImageGetWidth(image: CGImageRef) -> usize;
        fn CGImageGetHeight(image: CGImageRef) -> usize;
        fn CGImageRelease(image: CGImageRef);
        fn CGBitmapContextCreate(
            data: *mut c_void,
            width: usize,
            height: usize,
            bits_per_component: usize,
            bytes_per_row: usize,
            space: CGColorSpaceRef,
            bitmap_info: u32,
        ) -> CGContextRef;
        fn CGContextRelease(context: CGContextRef);
        fn CGContextDrawImage(c: CGContextRef, rect: CGRect, image: CGImageRef);
    }

    // kCGImageAlphaPremultipliedLast = 1
    // kCGBitmapByteOrderDefault = 0
    const BITMAP_INFO_RGBA: u32 = 1;

    pub fn decode_with_imageio(path: &Path) -> Result<DynamicImage, String> {
        let abs_path = path
            .canonicalize()
            .map_err(|e| format!("Failed to canonicalize path {:?}: {}", path, e))?;
        let path_str = abs_path
            .to_str()
            .ok_or_else(|| format!("Path contains invalid UTF-8: {:?}", abs_path))?;
        let path_bytes = path_str.as_bytes();

        unsafe {
            let cf_url = CFURLCreateFromFileSystemRepresentation(
                ptr::null(),
                path_bytes.as_ptr(),
                path_bytes.len() as isize,
                false,
            );
            if cf_url.is_null() {
                return Err(format!("Failed to create CFURL for {:?}", abs_path));
            }

            let source = CGImageSourceCreateWithURL(cf_url, ptr::null());
            CFRelease(cf_url as *const c_void);

            if source.is_null() {
                return Err(format!(
                    "CGImageSourceCreateWithURL returned null for {:?}",
                    abs_path
                ));
            }

            let cg_image = CGImageSourceCreateImageAtIndex(source, 0, ptr::null());
            CFRelease(source as *const c_void);

            if cg_image.is_null() {
                return Err(format!("Failed to decode image from {:?}", abs_path));
            }

            let width = CGImageGetWidth(cg_image);
            let height = CGImageGetHeight(cg_image);

            if width == 0 || height == 0 {
                CGImageRelease(cg_image);
                return Err(format!(
                    "Decoded image has zero dimensions ({}x{})",
                    width, height
                ));
            }

            let mut color_space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
            if color_space.is_null() {
                color_space = CGColorSpaceCreateDeviceRGB();
            }

            let bytes_per_row = width * 4;
            let total_bytes = bytes_per_row * height;
            let mut pixel_buffer = vec![0u8; total_bytes];

            let context = CGBitmapContextCreate(
                pixel_buffer.as_mut_ptr() as *mut c_void,
                width,
                height,
                8,
                bytes_per_row,
                color_space,
                BITMAP_INFO_RGBA,
            );

            CGColorSpaceRelease(color_space);

            if context.is_null() {
                CGImageRelease(cg_image);
                return Err("Failed to create CGBitmapContext for rendering".to_string());
            }

            // Direct drawing into CGBitmapContext places pixels in standard scanline order
            let rect = CGRect {
                origin: CGPoint { x: 0.0, y: 0.0 },
                size: CGSize {
                    width: width as f64,
                    height: height as f64,
                },
            };

            CGContextDrawImage(context, rect, cg_image);
            CGContextRelease(context);
            CGImageRelease(cg_image);

            let rgba_img = RgbaImage::from_raw(width as u32, height as u32, pixel_buffer)
                .ok_or_else(|| "Failed to construct RgbaImage from raw pixel buffer".to_string())?;

            Ok(DynamicImage::ImageRgba8(rgba_img))
        }
    }
}

/// Decodes a RAW image (or any image supported by the native hardware pipeline)
/// into a full-resolution `image::DynamicImage`.
///
/// On macOS, uses Apple's native `ImageIO` engine with camera "As-Shot" white balance
/// and hardware-accelerated demosaicing.
///
/// If native demosaicing fails or on other platforms, attempts fallback decoding.
pub fn decode_raw_image(path: &Path) -> Result<DynamicImage, String> {
    #[cfg(target_os = "macos")]
    {
        match macos_imageio::decode_with_imageio(path) {
            Ok(img) => Ok(img),
            Err(e) => {
                // If native decode fails, check if there's an embedded JPEG fallback
                if let Ok(data) = std::fs::read(path) {
                    if let Some(jpeg_data) = crate::raw_extractor::find_largest_embedded_jpeg(&data)
                    {
                        if let Ok(img) = image::load_from_memory(jpeg_data) {
                            return Ok(img);
                        }
                    }
                }
                Err(format!("Native RAW decode failed: {}", e))
            }
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        // On non-macOS, fallback to embedded JPEG or standard image reader
        if let Ok(data) = std::fs::read(path) {
            if let Some(jpeg_data) = crate::raw_extractor::find_largest_embedded_jpeg(&data) {
                if let Ok(img) = image::load_from_memory(jpeg_data) {
                    return Ok(img);
                }
            }
        }
        image::open(path).map_err(|e| format!("Fallback decode failed: {}", e))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgba, RgbaImage};
    use tempfile::tempdir;

    #[test]
    fn test_decode_raw_image_invalid_path() {
        let res = decode_raw_image(Path::new("/nonexistent/file.arw"));
        assert!(res.is_err());
    }

    #[test]
    fn test_decode_raw_image_native_rendering() {
        let dir = tempdir().expect("Failed to create tempdir");
        let img_path = dir.path().join("test_sample.png");

        // Create a 64x64 test image with known red pixel at (0,0)
        let mut img = RgbaImage::new(64, 64);
        img.put_pixel(0, 0, Rgba([255, 0, 0, 255]));
        img.put_pixel(63, 63, Rgba([0, 255, 0, 255]));
        img.save(&img_path).expect("Failed to save test image");

        let decoded = decode_raw_image(&img_path).expect("decode_raw_image failed");
        assert_eq!(decoded.width(), 64);
        assert_eq!(decoded.height(), 64);

        let rgba = decoded.to_rgba8();
        let p0 = rgba.get_pixel(0, 0);
        // Red channel should be dominant at (0,0)
        assert!(p0[0] > 200, "Expected red at (0,0), got {:?}", p0);
        assert!(p0[1] < 50);
        assert!(p0[2] < 50);

        let p_end = rgba.get_pixel(63, 63);
        // Green channel should be dominant at (63,63)
        assert!(p_end[1] > 200, "Expected green at (63,63), got {:?}", p_end);
    }
}
