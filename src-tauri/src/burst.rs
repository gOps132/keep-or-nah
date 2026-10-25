use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhotoBurstInfo {
    pub path: String,
    pub timestamp: f64,
    pub image_hash: u64,
    pub sharpness: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BurstCluster {
    pub id: String,
    pub photos: Vec<PhotoBurstInfo>,
    pub best_shot: String,
    pub is_burst: bool,
}

pub struct BurstClusterer {
    pub time_threshold_seconds: f64,
    pub hash_distance_threshold: u32,
}

impl Default for BurstClusterer {
    fn default() -> Self {
        Self {
            time_threshold_seconds: 2.5,
            hash_distance_threshold: 10,
        }
    }
}

impl BurstClusterer {
    pub fn new(time_threshold_seconds: f64, hash_distance_threshold: u32) -> Self {
        Self {
            time_threshold_seconds,
            hash_distance_threshold,
        }
    }

    #[inline]
    pub fn hamming_distance(h1: u64, h2: u64) -> u32 {
        (h1 ^ h2).count_ones()
    }

    pub fn cluster(&self, mut photos: Vec<PhotoBurstInfo>) -> Vec<BurstCluster> {
        if photos.is_empty() {
            return Vec::new();
        }

        photos.sort_by(|a, b| {
            a.timestamp
                .partial_cmp(&b.timestamp)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut groups: Vec<Vec<PhotoBurstInfo>> = Vec::new();
        let mut current_group = vec![photos[0].clone()];

        for photo in photos.into_iter().skip(1) {
            let prev = &current_group[current_group.len() - 1];
            let time_diff = (photo.timestamp - prev.timestamp).abs();
            let hash_dist = Self::hamming_distance(photo.image_hash, prev.image_hash);

            if time_diff <= self.time_threshold_seconds
                && hash_dist <= self.hash_distance_threshold
            {
                current_group.push(photo);
            } else {
                groups.push(current_group);
                current_group = vec![photo];
            }
        }
        if !current_group.is_empty() {
            groups.push(current_group);
        }

        let mut burst_idx = 0;
        let mut result = Vec::with_capacity(groups.len());
        for group in groups {
            let is_burst = group.len() >= 2;
            let best_photo = group
                .iter()
                .max_by(|a, b| {
                    a.sharpness
                        .partial_cmp(&b.sharpness)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap();
            let best_shot = best_photo.path.clone();

            let id = if is_burst {
                burst_idx += 1;
                format!("burst-{burst_idx}")
            } else {
                format!("solo-{}", group[0].path)
            };

            result.push(BurstCluster {
                id,
                photos: group,
                best_shot,
                is_burst,
            });
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hamming_distance() {
        assert_eq!(BurstClusterer::hamming_distance(0, 0), 0);
        assert_eq!(BurstClusterer::hamming_distance(0b1111, 0b1111), 0);
        assert_eq!(BurstClusterer::hamming_distance(0b1111, 0b0000), 4);
        assert_eq!(BurstClusterer::hamming_distance(0b1010, 0b1000), 1);
    }

    #[test]
    fn test_burst_clustering_and_best_shot_election() {
        let clusterer = BurstClusterer::new(2.0, 10);

        let p1 = PhotoBurstInfo {
            path: "/photos/burst1.jpg".to_string(),
            timestamp: 100.0,
            image_hash: 0x1234567890ABCDEF,
            sharpness: 50.0,
        };
        let p2 = PhotoBurstInfo {
            path: "/photos/burst2.jpg".to_string(),
            timestamp: 100.5,
            image_hash: 0x1234567890ABCDEF,
            sharpness: 120.0, // highest sharpness
        };
        let p3 = PhotoBurstInfo {
            path: "/photos/burst3.jpg".to_string(),
            timestamp: 101.0,
            image_hash: 0x1234567890ABCDEF,
            sharpness: 80.0,
        };
        let p4 = PhotoBurstInfo {
            path: "/photos/solo.jpg".to_string(),
            timestamp: 115.0, // outside 2.0s threshold
            image_hash: 0xFFFFFFFFFFFFFFFF,
            sharpness: 95.0,
        };

        let clusters = clusterer.cluster(vec![p1, p2, p3, p4]);
        assert_eq!(clusters.len(), 2);

        let burst = clusters.iter().find(|c| c.photos.len() == 3).unwrap();
        assert!(burst.is_burst);
        assert_eq!(burst.id, "burst-1");
        assert_eq!(burst.best_shot, "/photos/burst2.jpg");

        let solo = clusters.iter().find(|c| c.photos.len() == 1).unwrap();
        assert!(!solo.is_burst);
        assert_eq!(solo.best_shot, "/photos/solo.jpg");
    }

    #[test]
    fn test_empty_photos_returns_empty_clusters() {
        let clusterer = BurstClusterer::default();
        assert!(clusterer.cluster(Vec::new()).is_empty());
    }
}
