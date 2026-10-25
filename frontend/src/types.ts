export type ActionMode = "move" | "copy";
export type TriageDecision = "keep" | "nah" | "flag";

export interface PhotoGroup {
  stem: string;
  members: string[];
  representative: string;
  index: number;
}

export interface ThumbnailData {
  path: string;
  cache_path?: string;
  src_url?: string;
  data_url?: string | null;
  sharpness: number;
  image_hash?: number;
  timestamp?: number;
  width: number;
  height: number;
}

export interface PhotoBurstInfo {
  path: string;
  timestamp: number;
  image_hash: number;
  sharpness: number;
}

export interface BurstCluster {
  id: string;
  photos: PhotoBurstInfo[];
  best_shot: string;
  is_burst: boolean;
}

export interface ExifMetadataDto {
  shutter_speed?: string | null;
  aperture?: string | null;
  iso?: string | null;
  focal_length?: string | null;
  camera_model?: string | null;
  lens_model?: string | null;
}

export interface BatchItemSummary {
  stem: string;
  decision: string;
  file_count: number;
  total_bytes: number;
}

export interface BatchSummaryDto {
  total_groups: number;
  keep_count: number;
  nah_count: number;
  flag_count: number;
  total_files: number;
  total_reclaimed_bytes: number;
  items: BatchItemSummary[];
}

export interface CommitResultDto {
  successful_groups: number;
  successful_files: number;
  errors: string[];
}
