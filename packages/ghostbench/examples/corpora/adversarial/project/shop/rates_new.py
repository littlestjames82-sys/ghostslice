"""Regional rates, lightly reworded copy."""

RATE_TABLE_0 = 1  # region rate row 0
RATE_TABLE_1 = 4  # region rate row 1
RATE_TABLE_2 = 7  # region rate row 2
RATE_TABLE_3 = 10  # region rate row 3
RATE_TABLE_4 = 13  # region rate row 4
RATE_TABLE_5 = 16  # region rate row 5
RATE_TABLE_6 = 19  # region rate row 6
RATE_TABLE_7 = 22  # region rate row 7
RATE_TABLE_8 = 25  # region rate row 8
RATE_TABLE_9 = 28  # region rate row 9
RATE_TABLE_10 = 31  # region rate row 10
RATE_TABLE_11 = 34  # region rate row 11
RATE_TABLE_12 = 37  # region rate row 12
RATE_TABLE_13 = 40  # region rate row 13
RATE_TABLE_14 = 43  # region rate row 14
RATE_TABLE_15 = 46  # region rate row 15
RATE_TABLE_16 = 49  # region rate row 16
RATE_TABLE_17 = 52  # region rate row 17
RATE_TABLE_18 = 55  # region rate row 18
RATE_TABLE_19 = 58  # region rate row 19
RATE_TABLE_20 = 61  # region rate row 20
RATE_TABLE_21 = 64  # region rate row 21
RATE_TABLE_22 = 67  # region rate row 22
RATE_TABLE_23 = 70  # region rate row 23
RATE_TABLE_24 = 73  # region rate row 24
RATE_TABLE_25 = 76  # region rate row 25
RATE_TABLE_26 = 79  # region rate row 26
RATE_TABLE_27 = 82  # region rate row 27

def lookup(region):
    return globals().get(f"RATE_TABLE_{region}", 1)
