import pytest
from mock import patch

from satsang import SpeechSegment

silent_ranges_and_splits = [
    [[(20, 40), (70, 80)],
     [(0, 0, 20 + 2), (20 + 2, 40 - 2, 70 + 2), (70 + 2, 80 - 2, 100)]],

    [[(0, 30), (70, 100)],
     [(0, 30 - 2, 70 + 2)]],

    [[(0, 100)], []],

    [[], [(0, 0, 100)]],
]


def test_margin_too_big():
    seg = SpeechSegment(range(100))
    with pytest.raises(AssertionError) as excinfo:
        seg.split_ranges(10, None, 5)
    assert 'is too big for' in str(excinfo.value)


@pytest.mark.parametrize('silent_ranges, splits', silent_ranges_and_splits)
def test_split_ranges(silent_ranges, splits):
    with patch('satsang.detect_silence') as detect_silence:
        detect_silence.return_value = silent_ranges

        seg = SpeechSegment(range(100))
        assert seg.split_ranges(10, None, 2) == splits

        seg.split(silence_margin=2)
        assert [s.speech_start for s in seg.children] == [ss - s for s, ss, e in splits]

        children_audio_chain = (x for child in seg.children
                                for x in child.audio_segment)
        assert all(x == y for x, y in zip(seg.audio_segment, children_audio_chain))
