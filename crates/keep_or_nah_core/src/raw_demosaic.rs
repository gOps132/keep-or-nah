//! Hardware-accelerated RAW demosaicing engine.
//!
//! On macOS, leverages Apple's `ImageIO` and `CoreGraphics` frameworks to perform
//! hardware-accelerated demosaicing of camera RAW files (Sony ARW, Canon CR2/CR3,
//! Nikon NEF, DNG, etc.) with camera "As-Shot" white balance and standard color transforms.
//!
//! Output can be decoded into `image::DynamicImage` or exported directly to cached JPEG
//! via Apple's native hardware media engine (`CGImageDestination`) with zero intermediate buffer copies.

use image::DynamicImage;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};

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
    struct __CGImageDestination(c_void);
    type CGImageDestinationRef = *mut __CGImageDestination;

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
        fn CFStringCreateWithCString(
            alloc: *const c_void,
            c_str: *const u8,
            encoding: u32,
        ) -> CFStringRef;
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
        fn CGImageDestinationCreateWithURL(
            url: CFURLRef,
            image_type: CFStringRef,
            count: usize,
            options: CFDictionaryRef,
        ) -> CGImageDestinationRef;
        fn CGImageDestinationAddImage(
            idst: CGImageDestinationRef,
            image: CGImageRef,
            properties: CFDictionaryRef,
        );
        fn CGImageDestinationFinalize(idst: CGImageDestinationRef) -> bool;
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

    const BITMAP_INFO_RGBA: u32 = 1;
    const K_CF_STRING_ENCODING_UTF8: u32 = 0x08000100;

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

    /// Hardware-accelerated direct export from RAW image source to JPEG destination
    /// using Apple's ImageIO and hardware media blocks with zero intermediate heap buffers.
    pub fn export_hardware_jpeg(input_raw: &Path, output_temp: &Path) -> Result<(), String> {
        let abs_input = input_raw
            .canonicalize()
            .map_err(|e| format!("Failed to canonicalize path {:?}: {}", input_raw, e))?;
        let input_str = abs_input
            .to_str()
            .ok_or_else(|| format!("Path contains invalid UTF-8: {:?}", abs_input))?;
        let input_bytes = input_str.as_bytes();

        let output_str = output_temp
            .to_str()
            .ok_or_else(|| format!("Output path contains invalid UTF-8: {:?}", output_temp))?;
        let output_bytes = output_str.as_bytes();

        unsafe {
            let in_url = CFURLCreateFromFileSystemRepresentation(
                ptr::null(),
                input_bytes.as_ptr(),
                input_bytes.len() as isize,
                false,
            );
            if in_url.is_null() {
                return Err(format!("Failed to create input CFURL for {:?}", abs_input));
            }

            let source = CGImageSourceCreateWithURL(in_url, ptr::null());
            CFRelease(in_url as *const c_void);

            if source.is_null() {
                return Err(format!(
                    "CGImageSourceCreateWithURL returned null for {:?}",
                    abs_input
                ));
            }

            let cg_image = CGImageSourceCreateImageAtIndex(source, 0, ptr::null());
            CFRelease(source as *const c_void);

            if cg_image.is_null() {
                return Err(format!("Failed to demosaic image from {:?}", abs_input));
            }

            let out_url = CFURLCreateFromFileSystemRepresentation(
                ptr::null(),
                output_bytes.as_ptr(),
                output_bytes.len() as isize,
                false,
            );
            if out_url.is_null() {
                CGImageRelease(cg_image);
                return Err(format!(
                    "Failed to create output CFURL for {:?}",
                    output_temp
                ));
            }

            let jpeg_type = CFStringCreateWithCString(
                ptr::null(),
                c"public.jpeg".as_ptr() as *const u8,
                K_CF_STRING_ENCODING_UTF8,
            );
            if jpeg_type.is_null() {
                CFRelease(out_url as *const c_void);
                CGImageRelease(cg_image);
                return Err("Failed to create CFString for public.jpeg".to_string());
            }

            let dest = CGImageDestinationCreateWithURL(out_url, jpeg_type, 1, ptr::null());
            CFRelease(out_url as *const c_void);
            CFRelease(jpeg_type as *const c_void);

            if dest.is_null() {
                CGImageRelease(cg_image);
                return Err("Failed to create CGImageDestination".to_string());
            }

            CGImageDestinationAddImage(dest, cg_image, ptr::null());
            let success = CGImageDestinationFinalize(dest);
            CFRelease(dest as *const c_void);
            CGImageRelease(cg_image);

            if !success {
                return Err("CGImageDestinationFinalize failed to write hardware JPEG".to_string());
            }

            Ok(())
        }
    }
}

/// Decodes a RAW image into a full-resolution `image::DynamicImage`.
pub fn decode_raw_image(path: &Path) -> Result<DynamicImage, String> {
    #[cfg(target_os = "macos")]
    {
        match macos_imageio::decode_with_imageio(path) {
            Ok(img) => Ok(img),
            Err(e) => {
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

/// Renders a RAW image into a cached full-resolution JPEG file.
///
/// On macOS, uses hardware-accelerated direct export via `CGImageDestination`
/// with zero intermediate buffer copies and zero software compression CPU overhead.
/// Falls back to software demosaic + encoding when hardware export is unavailable.
pub fn render_raw_to_cache(raw_path: &Path, cache_dir: &Path) -> Result<PathBuf, String> {
    let _ = std::fs::create_dir_all(cache_dir);

    let mtime = std::fs::metadata(raw_path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let size = std::fs::metadata(raw_path).map(|m| m.len()).unwrap_or(0);

    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    (raw_path.to_string_lossy(), mtime, size).hash(&mut hasher);
    let cache_key = format!("{:016x}", hasher.finish());
    let cache_file = cache_dir.join(format!("{cache_key}.jpg"));

    if cache_file.exists()
        && std::fs::metadata(&cache_file)
            .map(|m| m.len() > 0)
            .unwrap_or(false)
    {
        return Ok(cache_file);
    }

    let temp_cache_file = cache_dir.join(format!("{cache_key}.tmp"));

    #[cfg(target_os = "macos")]
    {
        if let Ok(()) = macos_imageio::export_hardware_jpeg(raw_path, &temp_cache_file) {
            let _ = std::fs::rename(&temp_cache_file, &cache_file);
            return Ok(cache_file);
        }
    }

    // Fallback: software decode and encode
    let decoded = decode_raw_image(raw_path).map_err(|e| format!("RAW demosaicing failed: {e}"))?;

    {
        let file = std::fs::File::create(&temp_cache_file)
            .map_err(|e| format!("Failed to create temporary cache file: {e}"))?;
        let mut writer = std::io::BufWriter::new(file);
        let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut writer, 90);
        encoder
            .encode(
                decoded.to_rgb8().as_raw(),
                decoded.width(),
                decoded.height(),
                image::ExtendedColorType::Rgb8,
            )
            .map_err(|e| format!("Failed to encode demosaiced JPEG: {e}"))?;
    }

    let _ = std::fs::rename(&temp_cache_file, &cache_file);
    Ok(cache_file)
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

        let mut img = RgbaImage::new(64, 64);
        img.put_pixel(0, 0, Rgba([255, 0, 0, 255]));
        img.put_pixel(63, 63, Rgba([0, 255, 0, 255]));
        img.save(&img_path).expect("Failed to save test image");

        let decoded = decode_raw_image(&img_path).expect("decode_raw_image failed");
        assert_eq!(decoded.width(), 64);
        assert_eq!(decoded.height(), 64);

        let rgba = decoded.to_rgba8();
        let p0 = rgba.get_pixel(0, 0);
        assert!(p0[0] > 200, "Expected red at (0,0), got {:?}", p0);
        assert!(p0[1] < 50);
        assert!(p0[2] < 50);

        let p_end = rgba.get_pixel(63, 63);
        assert!(p_end[1] > 200, "Expected green at (63,63), got {:?}", p_end);
    }

    #[test]
    fn test_render_raw_to_cache_produces_valid_jpeg() {
        let dir = tempdir().expect("Failed to create tempdir");
        let img_path = dir.path().join("test_sample.png");
        let cache_dir = dir.path().join("cache");

        let mut img = RgbaImage::new(48, 32);
        img.put_pixel(0, 0, Rgba([255, 128, 0, 255]));
        img.save(&img_path).expect("Failed to save test image");

        let cached =
            render_raw_to_cache(&img_path, &cache_dir).expect("render_raw_to_cache failed");
        assert!(cached.exists());
        assert!(std::fs::metadata(&cached).unwrap().len() > 0);

        // Subsequent call should hit cache without error
        let cached2 = render_raw_to_cache(&img_path, &cache_dir)
            .expect("render_raw_to_cache second call failed");
        assert_eq!(cached, cached2);
    }
}
