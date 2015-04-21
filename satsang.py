import os.path
import sys
from tempfile import NamedTemporaryFile

from leaves import NodeMixin
from pydub import AudioSegment
from pydub.playback import play
from pydub.silence import detect_silence
from speech_recognition import WavFile, Recognizer
from tinydb import TinyDB


THRESHOLD_LEN = range(300, 100, -10)  # in ms
THRESHOLD_DB = range(-50, -30)  # in dB
SILENCE_MARGIN = 50  # in ms
CONFIDENCE_LOW, CONFIDENCE_HIGH = 0.40, 0.85

assert SILENCE_MARGIN * 2 < min(THRESHOLD_LEN)

en, pt = 'en-US', 'pt-BR'
speech_segments = []


def register_segment(speech_segment):
    speech_segments.append(speech_segment)
    return len(speech_segments) - 1


def silence_thresholds():
    for length in THRESHOLD_LEN:
        for db in THRESHOLD_DB:
            yield length, db


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
              silence_min_len=THRESHOLD_LEN[0],
              silence_max_db=THRESHOLD_DB[0],
              silence_margin=SILENCE_MARGIN):

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
                     silence_min_len=THRESHOLD_LEN[0],
                     silence_max_db=THRESHOLD_DB[0],
                     silence_margin=SILENCE_MARGIN):
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

    def seek_split(self):
        if self.children:
            return True
        message("Seeking split for segment...")
        for length, db in silence_thresholds():
            self.split(length, db)
            if self.children:
                message('\n    >>> Split done with length, dB: [%s,  %s]' % (length, db))
                return True
            else:
                message_point()
        return False

    def exhaust(self):
        if self.language():
            return  # done
        if self.seek_split():
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

    def language(self):
        (min_value, _), (max_value, lang) = sorted(
            (v, l) for l, v in self.confidence.items())
        if min_value < CONFIDENCE_LOW and max_value > CONFIDENCE_HIGH:
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

    def tree_view(self, feedback_function=None, indent=0):
        lang = {en: 'en', pt: 'pt', None: '??'}[self.language()]
        conf = self.confidence[en], self.confidence[pt]
        msg = ' '.join(
            map(unicode, [lang,
                          round(self.silence_dB),
                          self.silence_max_db_used or '---',
                          conf,
                          round(self.audio_segment.duration_seconds),
                          '[%s]' % self.transcription]))
        if feedback_function:
            msg = '[[%s]] ' % feedback_function(self) + msg
        print self.id, '  ' * indent, msg
        for child in self.children:
            child.tree_view(feedback_function, indent + 1)


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


def message_point():
    sys.stdout.write('.')


def play_id(id):
    speech_segments[id].play()

r = speech_from_wav('trecho.wav')
