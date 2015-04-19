import pytest
from mock import patch

from satsang import SpeechSegment


@pytest.mark.parametrize('silent_ranges, expected', [
    [[(20, 40), (70, 80)],
     [(0, 0, 20+2), (20+2, 40-2, 70+2), (70+2, 80-2, 100)]],

    [[(0, 30), (70, 100)],
     [(0, 30-2, 70+2)]],

    [[(0, 100)], []],

    [[], [(0, 0, 100)]],
])
def test_split_ranges(silent_ranges, expected):
    with patch('satsang.detect_silence') as stub:
        stub.return_value = silent_ranges

        seg = SpeechSegment(range(100))
        assert seg.split_ranges(10, None, 2) == expected

        children_audio_chain = (x for child in seg.children
            for x in child.audio_segment)
        assert all(x == y for x, y in zip(seg.audio_segment, children_audio_chain))


def test_margin_too_big():
    seg = SpeechSegment(range(100))
    with pytest.raises(AssertionError) as excinfo:
        seg.split_ranges(10, None, 5)
    assert 'is too big for' in str(excinfo.value)
