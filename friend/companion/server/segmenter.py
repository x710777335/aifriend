"""Bounded per-session PCM speech segmentation for the ESP32 server."""
from collections import deque

import numpy as np


class PcmSegmenter:
    def __init__(self, settings):
        self.settings = settings
        self.prebuffer = deque()
        self.pre_samples = 0
        self.speech = []
        self.active = False
        self.voiced_samples = 0
        self.silent_samples = 0
        self.total_samples = 0

    def push(self, pcm, auto_finish=True):
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if not pcm.size:
            return None
        rate = self.settings.sample_rate
        voiced = float(np.sqrt(np.mean(np.square(pcm)))) > 0.012
        if not self.active:
            self.prebuffer.append(pcm)
            self.pre_samples += len(pcm)
            limit = rate * self.settings.vad_prebuffer_ms / 1000
            while len(self.prebuffer) > 1 and self.pre_samples - len(self.prebuffer[0]) >= limit:
                self.pre_samples -= len(self.prebuffer.popleft())
            self.voiced_samples = self.voiced_samples + len(pcm) if voiced else 0
            if self.voiced_samples * 1000 < rate * self.settings.vad_start_ms:
                return None
            self.active = True
            self.speech = list(self.prebuffer)
            self.total_samples = sum(len(part) for part in self.speech)
            self.prebuffer.clear()
            self.pre_samples = 0
            return None
        self.speech.append(pcm)
        self.total_samples += len(pcm)
        self.silent_samples = 0 if voiced else self.silent_samples + len(pcm)
        if (not auto_finish or self.silent_samples * 1000 < rate * self.settings.vad_silence_ms) and self.total_samples < rate * self.settings.vad_max_speech_s:
            return None
        return self.finish()

    def finish(self):
        if not self.active:
            return None
        result = np.concatenate(self.speech)
        self.__init__(self.settings)
        if len(result) * 1000 < self.settings.sample_rate * self.settings.vad_min_speech_ms:
            return None
        return result
