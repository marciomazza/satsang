from tempfile import NamedTemporaryFile

import speech_recognition as sr


def audio_from_wav(recognizer, filename):
    with sr.WavFile(filename) as source:
        audio = recognizer.record(source)
        return audio


def recognize_file(filename, language="en-US", show_all=False):
    recognizer = sr.Recognizer(language=language)
    audio = audio_from_wav(recognizer, filename)
    return recognizer.recognize(audio, show_all)


def recognize(audio_segment, language="en-US", show_all=False):
    with NamedTemporaryFile("w+b", suffix=".wav") as f:
        audio_segment.export(f.name, "wav")
        try:
            return recognize_file(f.name, language, show_all)
        except LookupError, e:
            return e.message

