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

SILENCE_SEEK_COUNT = 30

CONFIDENCE_MIN = 0.40
CONFIDENCE_MAX = 0.85

speech_segments = []


def register_segment(speech_segment):
    speech_segments.append(speech_segment)
    return len(speech_segments) - 1


class SpeechSegment(NodeMixin):

    def __init__(self, audio_segment, speech_start=0):
        super(SpeechSegment, self).__init__()
        self.id = register_segment(self)
        self.audio_segment = audio_segment
        self.speech_start = speech_start
        self._recognized = None
        self.silence_max_db_used = None

    #### SLIT ####

    def split(self,
              silence_min_len=DEFAULT_SILENCE_MIN_LEN,
              silence_max_db=DEFAULT_SILENCE_MAX_DB,
              silence_margin=DEFAULT_SILENCE_MARGIN):

        self.silence_max_db_used = silence_max_db
        self.children = []

        split_ranges = self.split_ranges(silence_min_len, silence_max_db, silence_margin)
        if not split_ranges:
            return
        if len(split_ranges) == 1:
            # just update speech_start
            [(_, self.speech_start, _)] = split_ranges
        else:
            self.children = [
                SpeechSegment(self.audio_segment[start:end], speech_start - start)
                for (start, speech_start, end) in split_ranges]

    def split_ranges(self,
                     silence_min_len=DEFAULT_SILENCE_MIN_LEN,
                     silence_max_db=DEFAULT_SILENCE_MAX_DB,
                     silence_margin=DEFAULT_SILENCE_MARGIN):
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

    def seek_split(self, initial_silence_max_db=DEFAULT_SILENCE_MAX_DB):
        if self.children:
            return
        message("Seeking split dB for segment...")
        for db in range(initial_silence_max_db, initial_silence_max_db + SILENCE_SEEK_COUNT):
            message("  Trying %d dB" % db)
            self.split(silence_max_db=db)
            if self.children:
                message('    >>> split done in %d dB' % db)
                return True
        return False

    def exhaust(self):
        if self.language():
            return  # done
        if self.children or self.seek_split():
            for child in self.children:
                child.exhaust()

    #### RECOGNITION ################################

    @property
    def recognized(self):
        if not self._recognized:
            self._recognized = {
                pt: recognize_audio_segment(self.audio_segment, pt),
                en: recognize_audio_segment(self.audio_segment, en),
            }
        return self._recognized

    def _best_alternative(self, alternatives):
        max_confidence, best = -1, None
        for alt in alternatives:
            if alt['confidence'] > max_confidence:
                max_confidence, best = alt['confidence'], alt
        return best

    @property
    def confidence(self):

        def max_confidence(alternatives):
            if not alternatives:
                return -1
            else:
                best = self._best_alternative(alternatives)
                return round(best['confidence'], 2)

        return {lang: max_confidence(alternatives) for lang, alternatives in self.recognized.iteritems()}

    def language(self, confidence_min=CONFIDENCE_MIN, confidence_max=CONFIDENCE_MAX):
        (min_value, _), (max_value, lang) = sorted(
            (v, l) for l, v in self.confidence.items())
        if min_value < confidence_min and max_value > confidence_max:
            return lang

    #### GENERAL PROPERTIES ################################

    @property
    def silence_dB(self):
        return(self.audio_segment[:self.speech_start].dBFS)

    @property
    def transcription(self):
        lang = self.language()
        if lang:
            best = self._best_alternative(self.recognized[lang])
            return best['text']
        else:
            return '???'

    # SAVE AND RESTORE ################################

    def _data_to_store(self):
        return dict(
            speech_start=self.speech_start,
            _recognized=self._recognized,
            silence_max_db_used=self.silence_max_db_used,
            children=[(child._data_to_store(), len(child.audio_segment))
                      for child in self.children],
        )

    def _restore_from_data(self, data):
        self.speech_start = data['speech_start']
        self._recognized = data['_recognized']
        self.silence_max_db_used = data['silence_max_db_used']

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

    #### FEEDBACK ################################

    def play(self, skip_silence=True):
        self.tree_view()
        if skip_silence:
            seg = self.audio_segment[self.speech_start:]
        else:
            seg = self.audio_segment
        print '-' * 40, self.language(), self.confidence, '[%s]' % self.transcription
        play(seg)

    def play_children(self, skip_silence=True):
        for child in self.children:
            print '\n' + '~' * 40, child.audio_segment.duration_seconds
            child.play(skip_silence)

    def tree_view(self, indent=0):
        lang = {en: 'en', pt: 'pt', None: '??'}[self.language()]
        conf = self.confidence[en], self.confidence[pt]
        print self.id, '  ' * indent, lang, round(self.silence_dB), \
            self.silence_max_db_used or '---', conf, round(self.audio_segment.duration_seconds), \
            '[%s]' % self.transcription
        for child in self.children:
            child.tree_view(indent + 1)


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


def message(msg):
    print msg


def play_id(id):
    speech_segments[id].play()

r = speech_from_wav('trecho.wav')
