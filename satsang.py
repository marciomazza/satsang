import os.path
from tempfile import NamedTemporaryFile

from leaves import NodeMixin
from pydub import AudioSegment
from pydub.playback import play
from pydub.silence import detect_silence
from speech_recognition import WavFile, Recognizer
from tinydb import TinyDB


en, pt = 'en-US', 'pt-BR'
DEFAULT_SILENCE_MIN_LEN = 300  # in ms
DEFAULT_SILENCE_MAX_DB = -50  # in dB
DEFAULT_SILENCE_MARGIN = 50  # in ms

CONFIDENCE_MIN = 0.40
CONFIDENCE_MAX = 0.85


class SpeechSegment(NodeMixin):

    def __init__(self, audio_segment, speech_start=0):
        super(SpeechSegment, self).__init__()
        self.audio_segment = audio_segment
        self.speech_start = speech_start
        self._recognized = None

    def split(self, silence_min_len=DEFAULT_SILENCE_MIN_LEN,
              silence_max_db=DEFAULT_SILENCE_MAX_DB,
              silence_margin=DEFAULT_SILENCE_MARGIN):
        split_ranges = self.split_ranges(silence_min_len, silence_max_db, silence_margin)
        self.children = [
            SpeechSegment(self.audio_segment[start:end], speech_start - start)
            for (start, speech_start, end) in split_ranges]

    def split_ranges(self, silence_min_len, silence_max_db, silence_margin):
        """
        Based on see pydub.silence.detect_nonsilent
        """
        assert 2 * silence_margin < silence_min_len, 'Margin (%s) is too big for silence_min_len (%s)' % (
            silence_margin, silence_min_len)

        silent_ranges = detect_silence(self.audio_segment, silence_min_len, silence_max_db)
        len_seg = len(self.audio_segment)

        # if there is no silence, the whole thing is nonsilent
        if not silent_ranges:
            return [(0, 0, len_seg)]

        # short circuit when the whole audio segment is silent
        if silent_ranges[0] == [0, len_seg]:
            return []

        # reduce silent ranges by margin at both ends,
        #  but not when they touch the edges of the segment
        def cut_margin((start, end)):
            return [
                start + silence_margin if start > 0 else start,
                end - silence_margin if end < len_seg else end]

        silent_ranges = map(cut_margin, silent_ranges)

        prev_start = 0
        prev_end = 0
        ranges = []
        for start, end in silent_ranges:
            ranges.append((prev_start, prev_end, start))
            prev_start, prev_end = start, end

        if end == len_seg:
            # if we have silence at the end, just join it to the last range
            s, ss, _ = ranges[-1]
            ranges[-1] = (s, ss, end)
        else:
            ranges.append((prev_start, prev_end, len_seg))

        if ranges[0] == (0, 0, 0):
            ranges.pop(0)

        return ranges

    def play(self, skip_silence=True):
        if skip_silence:
            seg = self.audio_segment[self.speech_start:]
        else:
            seg = self.audio_segment
        print '-' * 40, self.language(), self.confidence
        play(seg)

    def play_children(self, skip_silence=True):
        for child in self.children:
            print '\n' + '~' * 40, child.audio_segment.duration_seconds
            child.play(skip_silence)

    @property
    def recognized(self):
        if not self._recognized:
            self._recognized = {
                pt: recognize_audio_segment(self.audio_segment, pt),
                en: recognize_audio_segment(self.audio_segment, en),
            }
        return self._recognized

    @property
    def confidence(self):

        def max_confidence(alternatives):
            if not alternatives:
                return -1
            else:
                return round(max(a['confidence'] for a in alternatives), 2)

        return {lang: max_confidence(alternatives) for lang, alternatives in self.recognized.iteritems()}

    def language(self, confidence_min=CONFIDENCE_MIN, confidence_max=CONFIDENCE_MAX):
        (min_value, _), (max_value, lang) = sorted(
            (v, l) for l, v in self.confidence.items())
        if min_value < confidence_min and max_value > confidence_max:
            return lang

    def _data_to_store(self):
        return dict(
            speech_start=self.speech_start,
            _recognized=self._recognized,
            children=[(child._data_to_store(), len(child.audio_segment))
                      for child in self.children],
        )

    def _restore_from_data(self, data):
        self.speech_start = data['speech_start']
        self._recognized = data['_recognized']

        self.children = []
        start = 0
        for (child_data, audio_length) in data['children']:
            end = start + audio_length
            child = SpeechSegment(self.audio_segment[start:end])
            child._restore_from_data(child_data)
            self.children.append(child)
            start = end

    def save(self, db_path):
        db = TinyDB(db_path)
        db.purge()
        db.insert({'root': self._data_to_store()})

    def restore(self, db_path):
        db = TinyDB(db_path)
        data = db.all()[0]['root']
        self._restore_from_data(data)


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


def speech_from_wav(filename, split=True):
    audio_segment = AudioSegment.from_wav(filename)
    speech = SpeechSegment(audio_segment)
    db_path = 'db/%s.db.json' % os.path.splitext(filename)[0]
    if os.path.isfile(db_path):
        speech.restore(db_path)
    elif split:
        speech.split()
    return speech
