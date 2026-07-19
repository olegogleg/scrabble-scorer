"""
Letter point values and board bonus-square positions for this Cyrillic
Scrabble set. Pulled out on its own since both the OCR step (to know
which codes are valid) and the scoring step (to know point values and
bonuses) need it.
"""

LETTERS = {
    "A": {"letter": "А", "points": 1},
    "B": {"letter": "Б", "points": 3},
    "V": {"letter": "В", "points": 2},
    "G": {"letter": "Г", "points": 3},
    "D": {"letter": "Д", "points": 2},
    "E": {"letter": "Е", "points": 1},
    "ZH": {"letter": "Ж", "points": 7},
    "Z": {"letter": "З", "points": 4},
    "I": {"letter": "И", "points": 1},
    "J": {"letter": "Й", "points": 5},
    "K": {"letter": "К", "points": 2},
    "L": {"letter": "Л", "points": 2},
    "M": {"letter": "М", "points": 2},
    "N": {"letter": "Н", "points": 2},
    "O": {"letter": "О", "points": 1},
    "P": {"letter": "П", "points": 2},
    "R": {"letter": "Р", "points": 2},
    "S": {"letter": "С", "points": 2},
    "T": {"letter": "Т", "points": 2},
    "U": {"letter": "У", "points": 3},
    "F": {"letter": "Ф", "points": 10},
    "H": {"letter": "Х", "points": 5},
    "TS": {"letter": "Ц", "points": 8},
    "CH": {"letter": "Ч", "points": 5},
    "SH": {"letter": "Ш", "points": 8},
    "SCH": {"letter": "Щ", "points": 9},
    "HARD": {"letter": "Ъ", "points": 10},
    "Y": {"letter": "Ы", "points": 4},
    "SOFT": {"letter": "Ь", "points": 5},
    "EH": {"letter": "Э", "points": 9},
    "YU": {"letter": "Ю", "points": 8},
    "YA": {"letter": "Я", "points": 3},
}

# Bonus square positions, (row, column), 0-indexed. row 0 = top, col 0 = left.
BONUS_DOTS = {
    "red": [(0, 0), (0, 7), (0, 14), (7, 0), (7, 14), (14, 0), (14, 7), (14, 14)],  # triple word
    "green": [(1, 1), (1, 13), (2, 2), (2, 12), (3, 3), (3, 11), (11, 3), (11, 11),
              (12, 2), (12, 12), (13, 1), (13, 13)],  # double word
    "yellow": [(2, 6), (2, 8), (4, 4), (4, 10), (5, 7), (7, 5), (7, 9), (9, 7),
               (10, 4), (10, 10), (12, 6), (12, 8)],  # triple letter
    "blue": [(3, 7), (6, 2), (6, 6), (6, 8), (6, 12), (7, 3), (7, 11), (8, 2),
             (8, 6), (8, 8), (8, 12), (11, 7)],  # double letter
}


def bonus_color(row: int, column: int) -> str:
    """Returns 'red' / 'green' / 'yellow' / 'blue' / 'no' for a board square."""
    for c, positions in BONUS_DOTS.items():
        if (row, column) in positions:
            return c
    return "no"
