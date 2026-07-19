"""
Low-level image/geometry helpers used while extracting the straightened
board from a photo. These are unchanged from your original script, just
grouped together and documented. mask_contour() and union_rect() aren't
called anywhere currently (they were also unused in your original file)
-- kept in case you need them later, safe to delete otherwise.
"""

import cv2 as cv
import numpy as np


def fit_quad_to_contour(contour):
    hull = cv.convexHull(contour, returnPoints=True)
    hull_pts = hull[:, 0, :].astype(np.float32)
    n = len(hull_pts)

    peri = cv.arcLength(hull, True)
    epsilon = 0.02 * peri
    while True:
        approx = cv.approxPolyDP(hull, epsilon, True)
        if len(approx) <= 4:
            break
        epsilon *= 1.1

    corners_idx = []
    for corner in approx[:, 0, :]:
        dists = np.linalg.norm(hull_pts - corner, axis=1)
        corners_idx.append(int(np.argmin(dists)))
    corners_idx = sorted(set(corners_idx))

    def get_side_pts(start, end):
        if end > start:
            idx = list(range(start, end + 1))
        else:
            idx = list(range(start, n)) + list(range(0, end + 1))
        return idx

    def trim_by_curvature(idx, angle_thresh_deg=25):
        pts = hull_pts[idx]
        m = len(pts)
        if m < 4:
            return pts

        dirs = []
        for i in range(m - 1):
            d = pts[i + 1] - pts[i]
            norm = np.linalg.norm(d)
            dirs.append(d / norm if norm > 0 else np.array([0.0, 0.0]))

        mid = len(dirs) // 2
        ref = dirs[mid]

        def angle_diff(a, b):
            cos = np.clip(np.dot(a, b), -1, 1)
            return np.degrees(np.arccos(cos))

        thresh = angle_thresh_deg

        start_trim = 0
        for i in range(mid):
            if angle_diff(dirs[i], ref) > thresh:
                start_trim = i + 1

        end_trim = m
        for i in range(m - 2, mid, -1):
            if angle_diff(dirs[i], ref) > thresh:
                end_trim = i

        if end_trim - start_trim < 2:
            return pts[max(0, mid - 1):mid + 2]

        return pts[start_trim:end_trim]

    sides_idx = [get_side_pts(corners_idx[i], corners_idx[(i + 1) % 4]) for i in range(4)]
    sides = [trim_by_curvature(idx) for idx in sides_idx]

    cx, cy = hull_pts.mean(axis=0)

    def fit_and_push_line(pts):
        vx, vy, x0, y0 = cv.fitLine(pts, cv.DIST_L2, 0, 0.01, 0.01).flatten()
        nx, ny = -vy, vx
        if nx * (cx - x0) + ny * (cy - y0) > 0:
            nx, ny = -nx, -ny
        proj = [(p[0] - x0) * nx + (p[1] - y0) * ny for p in hull_pts]
        d = max(proj)
        return (vx, vy, x0 + nx * d, y0 + ny * d)

    lines = [fit_and_push_line(s) for s in sides]

    def intersect_lines(l1, l2):
        vx1, vy1, x1, y1 = l1
        vx2, vy2, x2, y2 = l2
        denom = vx1 * vy2 - vy1 * vx2
        if abs(denom) < 1e-8:
            return None
        dx, dy = x2 - x1, y2 - y1
        t = (dx * vy2 - dy * vx2) / denom
        return np.array([x1 + t * vx1, y1 + t * vy1])

    corners = []
    for i in range(4):
        pt = intersect_lines(lines[i], lines[(i + 1) % 4])
        if pt is None:
            return None
        corners.append(pt)

    return np.array(corners, dtype=np.float32)


def sort_points_clockwise(pts):
    pts = np.array(pts, dtype=np.float32)

    s = pts.sum(axis=1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]

    d = np.diff(pts, axis=1).ravel()
    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]

    return np.float32([tl, tr, br, bl])


def crop_with_expanded_rect(image, rect, expand):
    x, y, w, h = rect
    x1 = max(0, x - expand)
    y1 = max(0, y - expand)
    x2 = min(image.shape[1], x + w + expand)
    y2 = min(image.shape[0], y + h + expand)
    return image[y1:y2, x1:x2]


def mask_contour(image, contour):
    result = np.full_like(image, 255)
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv.drawContours(mask, [contour], -1, 255, thickness=cv.FILLED)
    result[mask == 255] = image[mask == 255]
    return result


def union_rect(rect1, rect2):
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    left = min(x1, x2)
    top = min(y1, y2)
    right = max(x1 + w1, x2 + w2)
    bottom = max(y1 + h1, y2 + h2)
    return (left, top, right - left, bottom - top)


def has_white_border_percentage(img, x, y, w, h, margin, white_color):
    H, W = img.shape[:2]

    ex1 = max(0, x - margin)
    ey1 = max(0, y - margin)
    ex2 = min(W, x + w + margin)
    ey2 = min(H, y + h + margin)

    region = img[ey1:ey2, ex1:ex2]
    mask = np.ones(region.shape[:2], dtype=bool)

    cx1 = max(0, x) - ex1
    cy1 = max(0, y) - ey1
    cx2 = min(W, x + w) - ex1
    cy2 = min(H, y + h) - ey1

    mask[cy1:cy2, cx1:cx2] = False
    pixels = region[mask]

    if len(pixels) == 0:
        return 0.0
    white_pixels = np.all(pixels > white_color, axis=1)
    return np.mean(white_pixels)


def pad_binary_image(img, target_width, target_height):
    h, w = img.shape
    if w > target_width or h > target_height:
        raise ValueError("Target size is smaller than image")

    top = (target_height - h) // 2
    bottom = target_height - h - top
    left = (target_width - w) // 2
    right = target_width - w - left

    return cv.copyMakeBorder(img, top, bottom, left, right, cv.BORDER_CONSTANT, value=0)
