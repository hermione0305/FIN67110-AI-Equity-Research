"""Presentation-only quote matching; numeric signs and punctuation remain significant."""
import html
import re


def quote_normalized(text):
    text = html.unescape(str(text)).translate(str.maketrans({'\u2010':'-', '\u2011':'-', '\ufe63':'-', '\uff0d':'-'}))
    # Do not merge separate numerical tokens. Minus, en/em dashes and punctuation
    # remain distinct: their equivalence can change a financial meaning.
    text = re.sub(r'(?<=\d)\s+(?=\d)', '\u241f', text)
    return re.sub(r'\s+', '', text)


def quote_matches(quote, original):
    return bool(str(quote).strip()) and quote_normalized(quote) in quote_normalized(original)
