from pydub.playback import play
from tempfile import NamedTemporaryFile

from speech_recognition import WavFile, Recognizer
from pydub.silence import detect_silence

en, pt = 'en-US', 'pt-BR'
DEFAULT_MIN_SILENCE_LEN = 300  # in ms
DEFAULT_SILENCE_MAX_DB = -50  # in dB
DEFAULT_SILENCE_MARGIN = 50  # in ms

def recognize_wav(filename, language="en-US", show_all=True):
    recognizer = Recognizer(language=language)
    with WavFile(filename) as source:
        audio_data = recognizer.record(source)
    return recognizer.recognize(audio_data, show_all)


def recognize_audio_segment(audio_segment, language="en-US", show_all=True):
    with NamedTemporaryFile("w+b", suffix=".wav") as f:
        audio_segment.export(f.name, "wav")
        try:
            return recognize_wav(f.name, language, show_all)
        except LookupError:
            return None


class SpeechSegment(object):

    def __init__(self, audio_segment, speech_start=0):
        self.audio_segment = audio_segment
        self.speech_start = speech_start

        self.splits = {}
        self._recognized = None

    def split(self, min_silence_len=DEFAULT_MIN_SILENCE_LEN,
              silence_max_db=DEFAULT_SILENCE_MAX_DB,
              silence_margin=DEFAULT_SILENCE_MARGIN):
        if (min_silence_len, silence_max_db) in self.splits:
            return
        split_ranges = self.split_ranges(min_silence_len, silence_max_db, silence_margin)
        segments = [
            SpeechSegment(self.audio_segment[start:end], speech_start - start)
            for (start, speech_start, end) in split_ranges]
        self.splits[(min_silence_len, silence_max_db, silence_margin)] = segments

    def split_ranges(self, min_silence_len, silence_max_db, silence_margin):
        """
        Based on see pydub.silence.detect_nonsilent
        """
        assert 2*silence_margin < min_silence_len, 'Margin (%s) is too big for min_silence_len (%s)' % (
            silence_margin, min_silence_len)

        silent_ranges = detect_silence(self.audio_segment, min_silence_len, silence_max_db)
        len_seg = len(self.audio_segment)

        # if there is no silence, the whole thing is nonsilent
        if not silent_ranges:
            return [(0, 0, len_seg)]

        # short circuit when the whole audio segment is silent
        if silent_ranges[0] == [0, len_seg]:
            return []

        # reduce silent ranges by margin at both ends,
        #  but not when they touch the edges of the segment
        def give_margin((start, end)):
            return [
                start + silence_margin if start > 0 else start,
                end - silence_margin if end < len_seg else end]
        silent_ranges = map(give_margin, silent_ranges)

        prev_start_i = 0
        prev_end_i = 0
        ranges = []
        for start_i, end_i in silent_ranges:
            ranges.append((prev_start_i, prev_end_i, start_i))
            prev_start_i, prev_end_i = start_i, end_i

        if end_i != len_seg:
            ranges.append((prev_start_i, prev_end_i, len_seg))

        if ranges[0] == (0, 0, 0):
            ranges.pop(0)

        return ranges

    def play(self, skip_silence=True, margin=100):
        if skip_silence:
            seg = self.audio_segment[self.speech_start:]
        else:
            seg = self.audio_segment
        play(seg)

    @property
    def recognized(self):
        if not self._recognized:
            self._recognized = {
                pt: recognize_audio_segment(self.audio_segment, pt),
                en: recognize_audio_segment(self.audio_segment, en),
            }
        return self._recognized

    # def confidence(self):
    #     if not alternatives:
    #         return -1
    #     else:
    #         return max(a['confidence'] for a in alternatives)


    # @property
    # def language(self):
    #     return self.recognized[en]

