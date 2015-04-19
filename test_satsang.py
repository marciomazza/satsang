from tempfile import NamedTemporaryFile

import pytest
from mock import patch

from satsang import SpeechSegment

___SPLIT___ = True
___NO_SPLIT___ = False

silent_ranges_and_splits = [
    [[[20, 40], [70, 80]],
     [(0, 0, 20 + 2), (20 + 2, 40 - 2, 70 + 2), (70 + 2, 80 - 2, 100)],
     ___SPLIT___],

    [[[0, 10], [20, 30], [70, 100]],
     [(0, 10 - 2, 20 + 2), (20 + 2, 30 - 2, 100)],
     ___SPLIT___],

    [[[0, 30], [70, 100]],
     [(0, 30 - 2, 100)],
     ___NO_SPLIT___],

    [[[0, 40]],
     [(0, 40 - 2, 100)],
     ___NO_SPLIT___],

    [[[0, 100]], [], ___NO_SPLIT___],

    [[], [(0, 0, 100)], ___NO_SPLIT___],
]


def test_margin_too_big():
    seg = SpeechSegment(range(100))
    with pytest.raises(AssertionError) as excinfo:
        seg.split_ranges(10, None, 5)
    assert 'is too big for' in str(excinfo.value)


def assert_equal_sequences(a1, a2):
    assert len(a1) == len(a2)
    assert all(x == y for x, y in zip(a1, a2))


@pytest.mark.parametrize('silent_ranges, splits, should_split', silent_ranges_and_splits)
def test_split(silent_ranges, splits, should_split):
    with patch('satsang.detect_silence') as detect_silence:
        detect_silence.return_value = silent_ranges

        seg = SpeechSegment(range(100))
        assert seg.split_ranges(10, None, 2) == splits

        assert seg.speech_start == 0
        seg.split(silence_margin=2)
        if should_split:
            assert [s.speech_start for s in seg.children] == [ss - s for s, ss, e in splits]

            assert len(seg.children) == len(splits)  # can be empty
            if seg.children:
                assert_equal_sequences(seg.audio_segment, [x for child in seg.children
                                                           for x in child.audio_segment])
        else:
            assert not seg.children
            if splits:
                [(_, expected_speech_start, _)] = splits
                assert seg.speech_start == expected_speech_start


def assert_equal_speech_data(r1, r2):
    assert r1.speech_start == r2.speech_start
    assert r1._recognized == r2._recognized
    assert_equal_sequences(r1.audio_segment, r2.audio_segment)

    assert len(r1.children) == len(r2.children)
    for c1, c2 in zip(r1.children, r2.children):
        assert_equal_speech_data(c1, c2)


@pytest.mark.parametrize('silent_ranges, splits, should_split', silent_ranges_and_splits)
def test_save_restore(silent_ranges, splits, should_split):
    with patch('satsang.detect_silence') as detect_silence:
        detect_silence.return_value = silent_ranges

        original_audio_segment = range(100)

        original = SpeechSegment(original_audio_segment)
        original.split(silence_margin=2)

        with NamedTemporaryFile("w+b", suffix=".json") as db_file:
            db_path = db_file.name
            original.save(db_path)
            restored = SpeechSegment(original_audio_segment)
            restored.restore(db_path)
            assert_equal_speech_data(original, restored)
