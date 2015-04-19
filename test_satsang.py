import pytest
from mock import patch

from satsang import SpeechSegment


@pytest.mark.parametrize('silent_ranges, expected', [
    [[(2, 4), (7, 8)],
     [(0, 0, 2), (2, 4, 7), (7, 8, 10)]],

    [[(0, 3), (7, 10)],
     [(0, 3, 7)]],

    [[(0, 10)], []],

    [[], [(0, 0, 10)]],
])
def test_split_ranges(silent_ranges, expected):
    with patch('satsang.detect_silence') as stub:
        stub.return_value = silent_ranges

        seg = SpeechSegment(range(10))
        assert seg.split_ranges(None, None, None) == expected
