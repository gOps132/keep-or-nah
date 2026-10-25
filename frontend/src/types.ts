export interface PhotoGroup {
  stem: string;
  members: string[];
  representative: string;
  index: number;
}

export interface ThumbnailData {
  path: string;
  data_url: string;
  sharpness: number;
  width: number;
  height: number;
}

export interface ExifMetadataDto {
  shutter_speed?: string | null;
  aperture?: string | null;
  iso?: string | null;
  focal_length?: string | null;
  camera_model?: string | null;
  lens_model?: string | null;
}
