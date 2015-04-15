from pydub.playback import play
from tempfile import NamedTemporaryFile

from speech_recognition import WavFile, Recognizer
from pydub.silence import detect_silence

en, pt = 'en-US', 'pt-BR'
BASE_SILENCE_THRESH = -50  # in dB
BASE_MIN_SILENCE_LEN = 300  # in ms


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

    def split(self, min_silence_len=BASE_MIN_SILENCE_LEN, silence_thresh=BASE_MIN_SILENCE_LEN):
        if (min_silence_len, silence_thresh) in self.splits:
            return
        split_ranges = self.split_ranges(min_silence_len, silence_thresh)
        self.splits[(min_silence_len, silence_thresh)] = [
            SpeechSegment(self.audio_segment[start, end], speech_start - start)
            for (start, speech_start, end) in split_ranges]

    def split_ranges(self, min_silence_len, silence_thresh):
        """
        Based on see pydub.silence.detect_nonsilent
        """
        silent_ranges = detect_silence(self.audio_segment, min_silence_len, silence_thresh)
        len_seg = len(self.audio_segment)

        # if there is no silence, the whole thing is nonsilent
        if not silent_ranges:
            return [(0, 0, len_seg)]

        # short circuit when the whole audio segment is silent
        if silent_ranges[0][0] == 0 and silent_ranges[0][1] == len_seg:
            return []

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

