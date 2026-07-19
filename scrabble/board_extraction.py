"""
Turns a raw board photo into a (15, 15) letter-code grid.
This is your original cut_out()/char_rec() logic, with two changes:
  1. No more `global board` -- the board array is built locally and returned.
  2. Debug image writing (the "goods"/"rejects" folders) is now optional,
     controlled by the debug_dir parameter, instead of always-on.
Empty squares are "" instead of "X" (matches the rest of the app).
"""

import math
from pathlib import Path

import cv2 as cv
import numpy as np

from scrabble.vision_utils import (
    fit_quad_to_contour,
    sort_points_clockwise,
    crop_with_expanded_rect,
    has_white_border_percentage,
    pad_binary_image,
)

DEFAULT_TEMPLATES_DIR = Path(__file__).parent / "templates"


def recognize_letter(image: np.ndarray, templates_dir: Path) -> tuple[str, float]:
    """
    Template-match a binary letter image against every template in
    templates_dir. Returns (letter_code, confidence). letter_code is ""
    if no templates were found.
    """
    best_confidence = -1.0
    best_stem = None

    for image_path in templates_dir.iterdir():
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
            continue

        data = np.fromfile(str(image_path), dtype=np.uint8)
        template = cv.imdecode(data, cv.IMREAD_GRAYSCALE)
        _, template = cv.threshold(template, 127, 255, cv.THRESH_BINARY)

        pixel_score = 1 - np.count_nonzero(image != template) / image.size
        intersection = np.logical_and(image > 0, template > 0).sum()
        union = np.logical_or(image > 0, template > 0).sum()
        iou_score = intersection / union if union > 0 else 0.0
        confidence = 0.1 * pixel_score + 0.9 * iou_score

        if confidence > best_confidence:
            best_confidence = confidence
            best_stem = image_path.stem

    if best_stem is None:
        return "", -1.0
    # template files can be named "A_1.png", "A_2.png" etc for multiple
    # examples of the same letter -- strip the "_1" suffix to get the code.
    return best_stem.split("_")[0], best_confidence


def extract_board_from_image(
    img: np.ndarray,
    templates_dir: Path = DEFAULT_TEMPLATES_DIR,
    debug_dir: Path | None = None,
) -> np.ndarray:
    """
    Parameters
    ----------
    img : raw BGR image (as read by cv.imread or cv.imdecode)
    templates_dir : folder of letter template images for recognize_letter()
    debug_dir : if given, saves per-tile crops into debug_dir/goods and
                debug_dir/rejects like your original script did. Leave as
                None in the deployed app -- there's no need to write these
                files on every turn.

    Returns
    -------
    board : np.ndarray, shape (15, 15), dtype '<U4'
        "" for empty squares, a letter code ("A", "SCH", ...) otherwise.
    """
    if debug_dir is not None:
        (debug_dir / "goods").mkdir(parents=True, exist_ok=True)
        (debug_dir / "rejects").mkdir(parents=True, exist_ok=True)

    h, w = img.shape[:2]
    new_height = 3000
    scale = new_height / h
    new_width = int(w * scale)

    resized = cv.resize(img, (new_width, new_height))
    resized2 = resized.copy()

    hsv = cv.cvtColor(resized, cv.COLOR_RGB2HSV)
    blur = cv.GaussianBlur(hsv[:, :, 0], (15, 15), 5)
    _, mask = cv.threshold(blur, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (7, 7))
    mask = cv.morphologyEx(mask, cv.MORPH_ERODE, kernel)
    edges = cv.Canny(mask, 100, 200)
    kernel = np.ones((7, 7), np.uint8)
    edges = cv.morphologyEx(edges, cv.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    best_contour = None
    max_area = 0
    for cnt in contours:
        area = cv.contourArea(cnt)
        if area > max_area:
            best_contour = cnt
            max_area = area

    if best_contour is None:
        raise ValueError("Could not find the board outline in this photo. Try retaking it.")

    best_box = fit_quad_to_contour(best_contour)
    if best_box is None:
        raise ValueError("Could not fit a rectangle to the board outline. Try retaking the photo.")
    best_box = np.round(best_box).astype(np.int32)
    best_box = sort_points_clockwise(np.float32(best_box))

    W = new_height
    H = W
    pts_dst = np.float32([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]])
    M = cv.getPerspectiveTransform(best_box, pts_dst)
    warped = cv.warpPerspective(resized2, M, (W, H))

    cropped = warped
    lab = cv.cvtColor(cropped, cv.COLOR_BGR2LAB)
    _, tile_mask = cv.threshold(lab[:, :, 0], 200, 255, cv.THRESH_BINARY)
    kernel = cv.getStructuringElement(cv.MORPH_RECT, (3, 3))
    tile_mask = cv.morphologyEx(tile_mask, cv.MORPH_ERODE, kernel)
    contours, _ = cv.findContours(tile_mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    centers = []
    for contour in contours:
        area = cv.contourArea(contour)
        x, y, cw, ch = cv.boundingRect(contour)
        if area > 16000 and 0.8 < cw / ch < 1.2:
            centers.append((x + cw / 2, y + ch / 2))

    dists = {}
    delta = W // 35
    for x0 in range(W // 30 - delta, W // 30 + delta, 5):
        for y0 in range(H // 30 - delta, H // 30 + delta, 5):
            for d0 in range(W // 15 - delta, W // 15 + delta, 5):
                if x0 < d0 // 2 or y0 < d0 // 2:
                    continue
                ds = []
                cntds = 0
                for x, y in centers:
                    nex = x0 + round((x - x0) / d0) * d0
                    ney = y0 + round((y - y0) / d0) * d0
                    ned = math.dist((nex, ney), (x, y))
                    ds.append(ned)
                    if ned < d0 / 10:
                        cntds += 1
                dists[(x0, y0, d0)] = (-cntds, np.mean(ds))

    sorted_dists = sorted(dists, key=lambda tt: dists[tt])
    x0, y0, d0 = sorted_dists[0]

    board = np.full((15, 15), "", dtype="<U4")

    for i in range(15):
        for j in range(15):
            xcord = x0 + d0 * i - d0 // 2
            ycord = y0 + d0 * j - d0 // 2
            size = d0
            tile = cropped[ycord:ycord + size, xcord:xcord + size]

            tile_l = cv.cvtColor(tile, cv.COLOR_BGR2LAB)[:, :, 0]
            blur = cv.GaussianBlur(tile_l, (5, 5), 0)
            kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (61, 61))
            blackhat = cv.morphologyEx(blur, cv.MORPH_BLACKHAT, kernel)
            inv_blackhat = cv.bitwise_not(blackhat)
            _, binary = cv.threshold(inv_blackhat, 230, 255, cv.THRESH_BINARY)
            inverted = cv.bitwise_not(binary)
            kernel = cv.getStructuringElement(cv.MORPH_RECT, (15, 15))
            inverted = cv.morphologyEx(inverted, cv.MORPH_CLOSE, kernel)
            kernel = cv.getStructuringElement(cv.MORPH_RECT, (5, 5))
            inverted = cv.morphologyEx(inverted, cv.MORPH_ERODE, kernel)

            contours, _ = cv.findContours(inverted, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
            better_contours = []
            for contour in contours:
                xx, yy, ww, hh = cv.boundingRect(contour)
                touches_edge = xx == 0 or xx + ww >= 195 - 1 or yy == 0 or yy + hh >= 195 - 1
                too_big = ww >= 195 - 1 or hh >= 195 - 1
                bad_area = not (1500 <= ww * hh <= 20000)
                bad_ratio = not (0.5 <= ww / hh <= 2)
                if touches_edge or too_big or bad_area or bad_ratio:
                    continue
                better_contours.append(contour)

            if not better_contours:
                if debug_dir is not None:
                    cv.imwrite(str(debug_dir / "rejects" / f"{i} {j}.png"), tile)
                continue

            largest = max(better_contours, key=cv.contourArea)
            xx, yy, ww, hh = cv.boundingRect(largest)
            pad = 3
            ratio = round(has_white_border_percentage(tile, xx, yy, ww, hh, 4, 170), 2)
            if ratio < 0.45:
                if debug_dir is not None:
                    cv.imwrite(str(debug_dir / "rejects" / f"{i} {j} {ratio}.png"), tile)
                continue

            simple = crop_with_expanded_rect(tile, (xx, yy, ww, hh), pad)
            simple_l = cv.cvtColor(simple, cv.COLOR_BGR2LAB)[:, :, 0]
            _, simple_otsu = cv.threshold(simple_l, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            simple_inverted = cv.bitwise_not(simple_otsu)

            contours, _ = cv.findContours(simple_inverted, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                xxx, yyy, www, hhh = cv.boundingRect(contour)
                if www * hhh < 1000 and yyy >= 0.4 * hh:
                    cv.rectangle(simple_inverted, (xxx, yyy), (xxx + www, yyy + hhh), 0, -1)

            simple_cropped = simple_inverted
            points = cv.findNonZero(simple_cropped)
            if points is not None:
                x, y, pw, ph = cv.boundingRect(points)
                simple_cropped = simple_cropped[y:y + ph, x:x + pw]
            else:
                simple_cropped = np.empty((0, 0), dtype=binary.dtype)

            final = pad_binary_image(simple_cropped, 195, 195)
            letter_code, confidence = recognize_letter(final, templates_dir)
            board[j, i] = letter_code

            if debug_dir is not None:
                cv.imwrite(str(debug_dir / "goods" / f"{i} {j} {letter_code}{confidence}.png"), final)

    return board
