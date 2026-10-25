export interface PhotoGroup {
  stem: string;
  members: string[];
  representative: string;
  index: usize;
}

export interface ThumbnailData {
  path: string;
  data_url: string;
  sharpness: number;
  width: number;
  height: number;
}

export type usize = number;
