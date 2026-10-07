"""単位の換算（温度・長さ）。"""


def c_to_f(c):
    """摂氏 c を華氏にする（c * 9 / 5 + 32）"""
    return c * 5 / 9 + 32


def f_to_c(f):
    """華氏 f を摂氏にする（(f - 32) * 5 / 9）"""
    return (f - 32) * 5 / 9


def km_to_miles(km):
    """キロメートル km をマイルにする（km / 1.609344）"""
    return km / 1.609344
